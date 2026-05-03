import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from solariq.config import SolarIQConfig

logger = logging.getLogger(__name__)

SLOTS = 48
SOLCAST_BASE = "https://api.solcast.com.au/rooftop_sites"


def fetch_solar_forecast(config: SolarIQConfig, target_date: date) -> list[float]:
    """Return 48-slot solar generation forecast in kWh/slot for target_date.

    Slots are local-time anchored (using config.app.timezone), matching the
    Octopus price fetcher so that solar[t] and agile_price[t] refer to the same slot.
    """
    logger.info("fetching solar forecast for %s (resource=%s)", target_date, config.solcast.resource_id)
    url = f"{SOLCAST_BASE}/{config.solcast.resource_id}/forecasts"
    response = requests.get(
        url,
        params={"format": "json"},
        headers={"Authorization": f"Bearer {config.solcast.api_key}"},
    )
    response.raise_for_status()
    forecasts = response.json().get("forecasts", [])
    logger.info("Solcast returned %d forecast records", len(forecasts))

    tz = ZoneInfo(config.app.timezone)
    slot_map: dict[tuple[int, int], float] = {}

    for item in forecasts:
        # period_end is the end of the 30-min period (UTC)
        period_end_str = item["period_end"].replace(".0000000Z", "Z").replace("Z", "+00:00")
        period_end = datetime.fromisoformat(period_end_str)
        period_start = period_end - timedelta(minutes=30)
        local_start = period_start.astimezone(tz)

        if local_start.date() == target_date:
            kwh = item["pv_estimate"] * 0.5  # kW * 0.5h = kWh
            slot_map[(local_start.hour, local_start.minute)] = kwh

    result: list[float] = []
    for slot in range(SLOTS):
        total_minutes = slot * 30
        h, m = divmod(total_minutes, 60)
        result.append(slot_map.get((h, m), 0.0))

    populated = sum(1 for v in result if v > 0)
    total_kwh = sum(result)
    logger.info(
        "solar forecast for %s: %d/48 non-zero slots, total %.2f kWh",
        target_date, populated, total_kwh,
    )
    return result
