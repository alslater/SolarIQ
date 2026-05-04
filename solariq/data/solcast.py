import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from solariq.config import SolarIQConfig

logger = logging.getLogger(__name__)

SLOTS = 48
SOLCAST_BASE = "https://api.solcast.com.au/rooftop_sites"


def fetch_solar_forecast_with_coverage(
    config: SolarIQConfig, target_date: date
) -> tuple[list[float], set[int]]:
    """Return 48 forecast slots plus the slot indexes actually present in the API response."""
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
    slots = [0.0] * SLOTS
    covered_slots: set[int] = set()

    for item in forecasts:
        period_end_str = item["period_end"].replace(".0000000Z", "Z").replace("Z", "+00:00")
        period_end = datetime.fromisoformat(period_end_str)
        period_start = period_end - timedelta(minutes=30)
        local_start = period_start.astimezone(tz)

        if local_start.date() != target_date:
            continue

        slot = (local_start.hour * 60 + local_start.minute) // 30
        if 0 <= slot < SLOTS:
            slots[slot] = item["pv_estimate"] * 0.5
            covered_slots.add(slot)

    populated = sum(1 for v in slots if v > 0)
    total_kwh = sum(slots)
    logger.info(
        "solar forecast for %s: %d/48 API slots, %d/48 non-zero slots, total %.2f kWh",
        target_date,
        len(covered_slots),
        populated,
        total_kwh,
    )
    return slots, covered_slots


def fetch_solar_forecast(config: SolarIQConfig, target_date: date) -> list[float]:
    """Return 48-slot solar generation forecast in kWh/slot for target_date.

    Slots are local-time anchored (using config.app.timezone), matching the
    Octopus price fetcher so that solar[t] and agile_price[t] refer to the same slot.
    """
    slots, _ = fetch_solar_forecast_with_coverage(config, target_date)
    return slots
