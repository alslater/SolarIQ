import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from solariq.config import SolarIQConfig

logger = logging.getLogger(__name__)

SLOTS = 48


def _forecast_request_candidates(config: SolarIQConfig) -> list[tuple[str, dict | None]]:
    """Build candidate endpoint URLs in preferred order.

    Personal/professional keys use path-prefixed endpoints (/{apikey}/...).
    Public no-key calls use /estimate/watthours/....
    """
    lat = config.location.latitude
    lon = config.location.longitude
    decl = config.forecast_solar.declination
    az = config.forecast_solar.azimuth
    kw = config.forecast_solar.peak_power_kw
    base = config.forecast_solar.base_url.rstrip("/")
    api_key = (config.forecast_solar.api_key or "").strip()

    # All endpoints accept time=utc for unambiguous UTC timestamp responses.
    if api_key:
        return [
            # /{apikey}/estimate/watthours/... returns cumulative daily Wh.
            (f"{base}/{api_key}/estimate/watthours/{lat}/{lon}/{decl}/{az}/{kw}", {"time": "utc"}),
        ]

    return [
        # Public endpoint observed to return cumulative daily Wh as a flat result map.
        (f"{base}/estimate/watthours/{lat}/{lon}/{decl}/{az}/{kw}", {"time": "utc"}),
    ]


def _extract_series(payload: dict) -> tuple[dict, str]:
    """Extract timestamp->value map and series kind from known response shapes.

    Returns (series, kind) where kind is one of:
    - "period_wh": per-period energy in Wh  (watt_hours_period key)
    - "cumulative_wh": cumulative daily energy in Wh, resets to 0 at dawn
      (watt_hours key, or flat result dict from personal endpoint)
    - "power_w": instantaneous power values in W
    """
    result = payload.get("result", {})
    if not isinstance(result, dict):
        return {}, "period_wh"

    if isinstance(result.get("watt_hours_period"), dict):
        return result["watt_hours_period"], "period_wh"
    if isinstance(result.get("watt_hours"), dict):
        # Cumulative daily total — must be differenced to get per-period energy.
        return result["watt_hours"], "cumulative_wh"
    if isinstance(result.get("watts"), dict) and _looks_like_timeseries_map(result["watts"]):
        return result["watts"], "power_w"
    if _looks_like_timeseries_map(result):
        # Personal endpoint returns series directly as flat result dict.
        # Values are cumulative daily Wh, resetting to 0 at dawn each day.
        return result, "cumulative_wh"
    return {}, "period_wh"


def _parse_datetime(raw: str, tz_name: str) -> datetime:
    # Handle both RFC3339 and forecast.solar style keys.
    ts = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(ZoneInfo(tz_name))


def _looks_like_timeseries_map(data: dict) -> bool:
    if not data:
        return False
    sample_items = list(data.items())[:3]
    for key, value in sample_items:
        try:
            # Ensure the key looks like a timestamp and value is numeric-like.
            datetime.fromisoformat(str(key).replace("Z", "+00:00"))
            float(value or 0.0)
        except Exception:
            return False
    return True


def fetch_forecast_solar_with_coverage(
    config: SolarIQConfig, target_date: date
) -> tuple[list[float], set[int]]:
    """Return 48 forecast slots plus the slot indexes present in the response.

        Uses forecast.solar watthours endpoints and normalizes cumulative/period responses
        into 48 half-hour kWh slots.
    """
    payload = None
    candidates = _forecast_request_candidates(config)
    last_error: Exception | None = None
    for idx, (url, params) in enumerate(candidates):
        try:
            logger.info("fetching forecast.solar for %s (%s)", target_date, url)
            response = requests.get(url, params=params, timeout=20)
            response.raise_for_status()
            payload = response.json()
            break
        except requests.HTTPError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else None
            can_fallback = idx < len(candidates) - 1
            # Fallback only for endpoint-shape style failures.
            if can_fallback and status in {400, 404, 405}:
                logger.info("forecast.solar endpoint not supported at %s (HTTP %s), trying fallback", url, status)
                continue
            raise
        except requests.RequestException as exc:
            last_error = exc
            if idx < len(candidates) - 1:
                continue
            raise

    if payload is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("forecast.solar request failed without a response")

    series, series_kind = _extract_series(payload)

    slots = [0.0] * SLOTS
    covered_slots: set[int] = set()
    tz_name = config.app.timezone

    parsed_points: list[tuple[datetime, float]] = []
    for ts, value in series.items():
        try:
            parsed_points.append((_parse_datetime(str(ts), tz_name), float(value or 0.0)))
        except Exception:
            pass
    parsed_points.sort(key=lambda p: p[0])

    # forecast.solar timestamps are end-of-period markers.
    # Infer period length from samples, preferring exact spacing between points.
    period_minutes = 60
    deltas = []
    for idx in range(1, len(parsed_points)):
        delta_m = int((parsed_points[idx][0] - parsed_points[idx - 1][0]).total_seconds() // 60)
        if delta_m in {30, 60, 120}:
            deltas.append(delta_m)
    if deltas:
        period_minutes = min(deltas)
    else:
        parsed_minutes = {dt.minute for dt, _ in parsed_points}
        if 30 in parsed_minutes:
            period_minutes = 30

    slots_per_period = period_minutes // 30  # 1 or 2

    prev_value: float | None = None
    for end_dt, numeric in parsed_points:
        try:
            if end_dt.date() < target_date:
                prev_value = numeric
                continue
            start_dt = end_dt - timedelta(minutes=period_minutes)

            if series_kind == "cumulative_wh":
                if prev_value is None:
                    energy_wh = numeric
                else:
                    delta = numeric - prev_value
                    # Negative delta = daily reset to 0 at dawn — treat numeric as fresh start.
                    energy_wh = numeric if delta < 0 else delta
            elif series_kind == "power_w":
                energy_wh = numeric * (period_minutes / 60.0)
            else:
                energy_wh = numeric

            prev_value = numeric
            energy_per_slot = (energy_wh / 1000.0) / slots_per_period

            for offset in range(slots_per_period):
                slot_dt = start_dt + timedelta(minutes=offset * 30)
                if slot_dt.date() != target_date:
                    continue
                slot = (slot_dt.hour * 60 + slot_dt.minute) // 30
                if not 0 <= slot < SLOTS:
                    continue
                slots[slot] += energy_per_slot
                covered_slots.add(slot)
        except Exception:
            continue

    logger.info(
        "forecast.solar for %s: %d/48 slots, total %.2f kWh",
        target_date,
        len(covered_slots),
        sum(slots),
    )
    return slots, covered_slots


def fetch_forecast_solar(config: SolarIQConfig, target_date: date) -> list[float]:
    slots, _ = fetch_forecast_solar_with_coverage(config, target_date)
    return slots