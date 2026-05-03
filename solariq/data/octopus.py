import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from solariq.config import SolarIQConfig

logger = logging.getLogger(__name__)

SLOTS = 48


def _date_to_utc_bounds(target_date: date, tz_name: str) -> tuple[str, str]:
    tz = ZoneInfo(tz_name)
    start = datetime(target_date.year, target_date.month, target_date.day, 0, 0, tzinfo=tz)
    # Use midnight of the next day as period_to so the Octopus API returns all 48 BST
    # slots, including 23:00 and 23:30 which were being excluded when period_to was 23:30 BST.
    end = start + timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (
        start.astimezone(timezone.utc).strftime(fmt),
        end.astimezone(timezone.utc).strftime(fmt),
    )


def _fetch_rates(url: str, api_key: str, from_utc: str, to_utc: str) -> list[dict]:
    logger.info("GET %s (period_from=%s, period_to=%s)", url, from_utc, to_utc)
    response = requests.get(
        url,
        params={"period_from": from_utc, "period_to": to_utc},
        auth=(api_key, ""),
    )
    response.raise_for_status()
    data = response.json()
    results = data.get("results", [])
    logger.info("Octopus API returned %d rate records", len(results))
    return results


_UNPUBLISHED_RATE_CAP_P = 100.0  # p/kWh — used for slots not yet published by Octopus


def _rates_to_48_slots(results: list[dict], target_date: date, tz_name: str, future_only: bool = False) -> list[float]:
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(ZoneInfo(tz_name))
    rate_map: dict[tuple[int, int], float] = {}
    for item in results:
        dt = datetime.fromisoformat(item["valid_from"].replace("Z", "+00:00"))
        local = dt.astimezone(tz)
        if local.date() == target_date:
            rate_map[(local.hour, local.minute)] = item["value_inc_vat"]

    slots: list[float] = []
    for slot in range(SLOTS):
        total_minutes = slot * 30
        h, m = divmod(total_minutes, 60)
        if (h, m) in rate_map:
            slots.append(rate_map[(h, m)])
        else:
            # Slot not returned by Octopus — either not yet published or genuinely zero.
            # Use the cap price so the optimizer never charges into an unknown slot.
            slots.append(_UNPUBLISHED_RATE_CAP_P)
    return slots


def fetch_agile_prices(config: SolarIQConfig, target_date: date) -> list[float]:
    logger.info("fetching agile import prices for %s", target_date)
    from_utc, to_utc = _date_to_utc_bounds(target_date, config.app.timezone)
    results = _fetch_rates(config.octopus.agile_rate_url, config.octopus.api_key, from_utc, to_utc)
    slots = _rates_to_48_slots(results, target_date, config.app.timezone)
    populated = sum(1 for s in slots if s > 0)
    logger.info("agile import: %d/48 slots populated for %s", populated, target_date)
    return slots


def fetch_export_prices(config: SolarIQConfig, target_date: date) -> list[float]:
    logger.info("fetching agile export prices for %s", target_date)
    from_utc, to_utc = _date_to_utc_bounds(target_date, config.app.timezone)
    results = _fetch_rates(config.octopus.agile_export_url, config.octopus.api_key, from_utc, to_utc)
    slots = _rates_to_48_slots(results, target_date, config.app.timezone)
    populated = sum(1 for s in slots if s > 0)
    logger.info("agile export: %d/48 slots populated for %s", populated, target_date)
    return slots


def _standing_charges_url(agile_rate_url: str) -> str:
    return agile_rate_url.replace("standard-unit-rates/", "standing-charges/")


def _fetch_standing_charge_results(config: SolarIQConfig, params: dict) -> list[dict]:
    url = _standing_charges_url(config.octopus.agile_rate_url)
    logger.info("fetching standing charges from %s params=%s", url, params)
    resp = requests.get(url, auth=(config.octopus.api_key, ""), params=params, timeout=10)
    resp.raise_for_status()
    results = resp.json().get("results", [])
    logger.info("standing charges: %d entries returned", len(results))
    return results


def fetch_standing_charge_p_per_day(config: SolarIQConfig) -> float:
    """Return current standing charge in pence/day (inc VAT)."""
    results = _fetch_standing_charge_results(config, {})
    now = datetime.now(timezone.utc)
    for entry in results:
        valid_from = datetime.fromisoformat(entry["valid_from"].replace("Z", "+00:00"))
        valid_to_str = entry.get("valid_to")
        valid_to = datetime.fromisoformat(valid_to_str.replace("Z", "+00:00")) if valid_to_str else None
        if valid_from <= now and (valid_to is None or now < valid_to):
            rate = float(entry["value_inc_vat"])
            logger.info("current standing charge: %.4f p/day", rate)
            return rate
    # Fallback: first result
    rate = float(results[0]["value_inc_vat"]) if results else config.octopus.standing_charge_p_per_day
    logger.info("standing charge fallback: %.4f p/day", rate)
    return rate


def fetch_total_standing_charge_gbp(config: SolarIQConfig, start_date: date, end_date: date) -> float:
    """Return total standing charge in £ for start_date..end_date inclusive.

    Fetches the full rate history for the period so mid-period rate changes are handled correctly.
    """
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    from_utc = datetime(start_date.year, start_date.month, start_date.day, 0, 0, tzinfo=timezone.utc).strftime(fmt)
    to_utc = datetime(end_date.year, end_date.month, end_date.day, 23, 59, tzinfo=timezone.utc).strftime(fmt)
    results = _fetch_standing_charge_results(config, {"period_from": from_utc, "period_to": to_utc})

    if not results:
        fallback = config.octopus.standing_charge_p_per_day * ((end_date - start_date).days + 1) / 100
        logger.warning("no standing charge data for range, using config fallback: %.2f £", fallback)
        return fallback

    # For each day find the applicable rate
    total_pence = 0.0
    cursor = start_date
    while cursor <= end_date:
        midday = datetime(cursor.year, cursor.month, cursor.day, 12, 0, tzinfo=timezone.utc)
        for entry in results:
            valid_from = datetime.fromisoformat(entry["valid_from"].replace("Z", "+00:00"))
            valid_to_str = entry.get("valid_to")
            valid_to = datetime.fromisoformat(valid_to_str.replace("Z", "+00:00")) if valid_to_str else None
            if valid_from <= midday and (valid_to is None or midday < valid_to):
                total_pence += float(entry["value_inc_vat"])
                break
        cursor += timedelta(days=1)

    logger.info(
        "total standing charge %s..%s: %.2f p (%.4f £)",
        start_date, end_date, total_pence, total_pence / 100,
    )
    return round(total_pence / 100, 4)


def fetch_octopus_export_consumption_kwh(
    config: SolarIQConfig, start_date: date, end_date: date
) -> float:
    """Return total kWh exported to grid for start_date..end_date per the Octopus smart meter.

    Uses export MPAN + serial from config. page_size=1500 covers 30 days × 48 slots without pagination.
    """
    tz = ZoneInfo(config.app.timezone)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    from_utc = datetime(start_date.year, start_date.month, start_date.day, 0, 0, tzinfo=tz).astimezone(timezone.utc).strftime(fmt)
    to_utc = datetime(end_date.year, end_date.month, end_date.day, 23, 30, tzinfo=tz).astimezone(timezone.utc).strftime(fmt)

    url = (
        f"https://api.octopus.energy/v1/electricity-meter-points/"
        f"{config.octopus.export_mpan}/meters/{config.octopus.export_serial_number}"
        f"/consumption/"
    )
    logger.info("fetching Octopus export consumption %s → %s", from_utc, to_utc)
    response = requests.get(
        url,
        params={"period_from": from_utc, "period_to": to_utc, "page_size": 1500},
        auth=(config.octopus.api_key, ""),
        timeout=30,
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    total_kwh = sum(float(r["consumption"]) for r in results)
    logger.info("Octopus export consumption: %.3f kWh (%d records)", total_kwh, len(results))
    return total_kwh
