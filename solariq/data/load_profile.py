import logging
from datetime import date, timedelta

from solariq.config import SolarIQConfig
from solariq.data.influx import query_solax_usage_day
from solariq.data.weather import fetch_daily_temperatures

logger = logging.getLogger(__name__)

SLOTS = 48
FALLBACK_KWH_PER_SLOT = 0.3
CANDIDATE_DAYS = 8   # same-weekday candidates to gather before temperature ranking
PROFILE_DAYS = 4     # how many to average after ranking


def build_load_profile(config: SolarIQConfig, target_date: date) -> list[float]:
    """Return 48-slot average load profile for target_date.

    Gathers the last CANDIDATE_DAYS same-weekday dates, then selects the
    PROFILE_DAYS with the closest daily mean temperature to target_date's
    forecast. Falls back to the 4 most recent if the temperature fetch fails.
    """
    day_of_week = target_date.weekday()
    logger.info("building load profile for %s (weekday %d)", target_date, day_of_week)

    # Gather more candidates than we need so temperature can filter them
    candidates: list[date] = []
    cursor = target_date - timedelta(days=7)
    while len(candidates) < CANDIDATE_DAYS:
        if cursor.weekday() == day_of_week:
            candidates.append(cursor)
        cursor -= timedelta(days=1)

    # Temperature-ranked selection
    selected = _select_by_temperature(config, target_date, candidates)

    # Build profiles from selected dates
    profiles: list[list[float]] = []
    for d in selected:
        slots = query_solax_usage_day(config, d)
        total = sum(slots)
        if total > 0:
            profiles.append(slots)
            logger.debug("load profile %s: total %.2f kWh", d, total)
        else:
            logger.debug("skipping %s: no usage data", d)

    if not profiles:
        logger.warning(
            "no usable historical data for load profile, using fallback %.1f kWh/slot",
            FALLBACK_KWH_PER_SLOT,
        )
        return [FALLBACK_KWH_PER_SLOT] * SLOTS

    logger.info("load profile built from %d days", len(profiles))
    return [
        sum(profile[i] for profile in profiles) / len(profiles)
        for i in range(SLOTS)
    ]


def _select_by_temperature(
    config: SolarIQConfig, target_date: date, candidates: list[date]
) -> list[date]:
    """Return up to PROFILE_DAYS candidates ranked by temperature proximity to target_date.

    Falls back to the PROFILE_DAYS most recent candidates if the temperature
    fetch fails or target_date temperature is unavailable.
    """
    try:
        temps = fetch_daily_temperatures(config, candidates + [target_date])
        target_temp = temps.get(target_date)
        if target_temp is None:
            logger.warning("no temperature data for %s, using most recent days", target_date)
            return candidates[:PROFILE_DAYS]

        ranked = sorted(
            [d for d in candidates if d in temps],
            key=lambda d: abs(temps[d] - target_temp),
        )
        selected = ranked[:PROFILE_DAYS]
        logger.info(
            "temperature selection: target=%.1f°C, selected %s",
            target_temp,
            [(d.isoformat(), round(temps[d], 1)) for d in selected],
        )
        return selected

    except Exception as exc:
        logger.warning("temperature fetch failed (%s), using most recent days", exc)
        return candidates[:PROFILE_DAYS]
