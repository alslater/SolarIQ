"""Standalone background worker.

Runs all scheduled data fetches so web instances share a single set of API
calls rather than each making their own.  Results are written to the shared
cache directory (cache/today.json and cache/strategy.json), which web
instances read every 30 seconds.

Usage:
    python -m solariq.worker          # production
    pipenv run python -m solariq.worker

Docker: uses the same image as the web service, different CMD:
    command: ["python", "-m", "solariq.worker"]
"""

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from solariq.cache import (
    load_calibration,
    load_solar_forecast_today,
    load_strategy,
    save_calibration,
    save_solar_forecast_today,
    save_strategy,
    save_today_snapshot,
)
from solariq.calibration import compute_export_factor
from solariq.config import SolarIQConfig, load_config
from solariq.data.influx import get_today_live_data
from solariq.data.load_profile import build_load_profile
from solariq.data.octopus import (
    fetch_agile_prices,
    fetch_export_prices,
    fetch_standing_charge_p_per_day,
)
from solariq.data.solcast import fetch_solar_forecast
from solariq.logging_config import setup_logging
from solariq.optimizer.solver import solve

logger = logging.getLogger(__name__)

# Module-level singletons initialised on first use
_config: SolarIQConfig | None = None
_standing_charge_p: float | None = None


def _get_config() -> SolarIQConfig:
    global _config
    if _config is None:
        _config = load_config()
        setup_logging(_config.app.log_file, _config.app.log_level)
    return _config


def _get_standing_charge() -> float:
    """Fetch standing charge from Octopus API once per session; cache result."""
    global _standing_charge_p
    if _standing_charge_p is None:
        config = _get_config()
        try:
            _standing_charge_p = fetch_standing_charge_p_per_day(config)
            logger.info("standing charge: %.4f p/day", _standing_charge_p)
        except Exception as exc:
            logger.warning("standing charge fetch failed, using config fallback: %s", exc)
            _standing_charge_p = config.octopus.standing_charge_p_per_day
    return _standing_charge_p


def _tomorrow(config: SolarIQConfig) -> date:
    tz = ZoneInfo(config.app.timezone)
    return (datetime.now(tz) + timedelta(days=1)).date()


def _after_refresh_time(config: SolarIQConfig) -> bool:
    tz = ZoneInfo(config.app.timezone)
    now = datetime.now(tz)
    h, m = (int(x) for x in config.app.refresh_time.split(":"))
    return now >= now.replace(hour=h, minute=m, second=0, microsecond=0)


def _strategy_needs_refresh(config: SolarIQConfig) -> bool:
    if not _after_refresh_time(config):
        return False
    cached = load_strategy()
    return cached is None or cached.target_date != _tomorrow(config).isoformat()


# ── Scheduled jobs ─────────────────────────────────────────────────────────────

def refresh_today() -> None:
    """Fetch live inverter data, build chart/price arrays, write cache/today.json."""
    config = _get_config()
    standing_charge_p = _get_standing_charge()
    logger.info("refresh_today starting")
    try:
        today_data = get_today_live_data(config)
        load_profile = build_load_profile(config, date.today())

        timestamps = today_data.timestamps
        solar_forecast = load_solar_forecast_today()
        if solar_forecast is None:
            # Cache is stale (new day) — refresh inline rather than showing zeros
            try:
                refresh_solar_forecast_today()
                solar_forecast = load_solar_forecast_today()
            except Exception as exc:
                logger.warning("inline solar forecast refresh failed: %s", exc)
        solar_forecast = solar_forecast or [0.0] * 48

        chart_data = []
        for i in range(48):
            chart_data.append({
                "time": timestamps[i],
                "grid_import": round(today_data.actual_grid_import[i] or 0.0, 3),
                "grid_export": round(today_data.actual_grid_export[i] or 0.0, 3),
                "solar": round(today_data.actual_solar[i] or 0.0, 3),
                "predicted_solar": round(solar_forecast[i], 3),
                "soc_pct": (
                    (today_data.actual_battery_soc_kwh[i] or 0.0) / config.battery.capacity_kwh * 100
                    if today_data.actual_battery_soc_kwh[i] is not None else None
                ),
                "predicted_usage": load_profile[i],
                "is_actual": i <= today_data.last_data_slot,
            })

        price_data = [
            {
                "time": timestamps[i],
                "import": today_data.agile_prices[i],
                "export": today_data.export_prices[i],
            }
            for i in range(48)
        ]

        snapshot = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "error": "",
            "battery_soc_pct": round(today_data.battery_soc_pct, 1),
            "battery_soc_kwh": round(today_data.battery_soc_kwh, 1),
            "solar_today_kwh": round(today_data.solar_today_kwh, 2),
            "grid_import_today_kwh": round(
                sum(v for v in today_data.actual_grid_import if v is not None), 2
            ),
            "grid_export_today_kwh": round(
                sum(v for v in today_data.actual_grid_export if v is not None), 2
            ),
            "grid_cost_gbp": round(today_data.grid_cost_pence / 100, 2),
            "grid_export_revenue_gbp": round(today_data.grid_export_revenue_pence / 100, 2),
            "net_daily_cost_gbp": round(
                (today_data.grid_cost_pence - today_data.grid_export_revenue_pence + standing_charge_p) / 100,
                2,
            ),
            "standing_charge_p_per_day": standing_charge_p,
            "current_rate_p": round(today_data.current_rate_p, 1),
            "current_export_rate_p": round(today_data.current_export_rate_p, 1),
            "chart_data": chart_data,
            "price_data": price_data,
        }
        save_today_snapshot(snapshot)
        logger.info("today snapshot saved (last_slot=%d)", today_data.last_data_slot)

    except Exception as exc:
        logger.error("refresh_today failed: %s", exc, exc_info=True)
        # Write an error snapshot so the web instances can surface it to the user
        save_today_snapshot({"error": str(exc), "fetched_at": datetime.now(timezone.utc).isoformat()})

    # Piggyback strategy refresh check onto the regular today poll
    _maybe_refresh_strategy()


def _maybe_refresh_strategy() -> None:
    """Compute and cache tomorrow's charging strategy if conditions are met."""
    config = _get_config()
    if not _strategy_needs_refresh(config):
        return
    target = _tomorrow(config)
    logger.info("refreshing strategy for %s", target)
    try:
        agile = fetch_agile_prices(config, target)
        export = fetch_export_prices(config, target)
        solar = fetch_solar_forecast(config, target)
        load = build_load_profile(config, target)
        today_data = get_today_live_data(config)
        initial_soc = today_data.battery_soc_kwh or (config.battery.capacity_kwh * 0.5)
        result = solve(agile, export, solar, load, initial_soc, config, target.isoformat())
        save_strategy(result)
        logger.info("strategy saved for %s, estimated cost £%.2f", target, result.estimated_cost_gbp)
    except Exception as exc:
        logger.error("strategy refresh failed: %s", exc, exc_info=True)


def refresh_solar_forecast_today() -> None:
    """Fetch today's Solcast forecast and cache it. Called twice daily to stay within API limits."""
    config = _get_config()
    today = date.today()
    logger.info("refreshing Solcast forecast for %s", today)
    try:
        slots = fetch_solar_forecast(config, today)
        save_solar_forecast_today(slots, today.isoformat())
        logger.info("solar forecast cached: total %.2f kWh", sum(slots))
    except Exception as exc:
        logger.warning("solar forecast refresh failed: %s", exc)


def refresh_calibration() -> None:
    """Recompute export correction factor and save to cache."""
    config = _get_config()
    logger.info("refreshing export calibration factor")
    try:
        result = compute_export_factor(config)
        save_calibration(result)
        logger.info("export factor saved: %.4f", result["factor"])
    except Exception as exc:
        logger.warning("calibration refresh failed: %s", exc, exc_info=True)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    # Initialise config + logging before the scheduler starts
    config = _get_config()
    logger.info("SolarIQ worker starting (refresh_time=%s)", config.app.refresh_time)

    # Fetch standing charge at startup
    _get_standing_charge()

    # Compute calibration factor on startup if not already cached
    if load_calibration() is None:
        logger.info("no cached calibration — computing on startup")
        refresh_calibration()

    # Fetch today's solar forecast on startup
    refresh_solar_forecast_today()

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        refresh_today,
        IntervalTrigger(minutes=5),
        id="refresh_today",
        next_run_time=datetime.now(timezone.utc),  # run immediately on startup
        misfire_grace_time=60,
    )
    scheduler.add_job(
        refresh_solar_forecast_today,
        CronTrigger(hour="0,5,12", minute=5, timezone="UTC"),  # ~1am, 6am, 1pm BST — 3 calls/day
        id="refresh_solar_forecast_today",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        refresh_calibration,
        CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="UTC"),
        id="refresh_calibration",
        misfire_grace_time=3600,
    )

    logger.info("scheduler started — polling every 5 minutes")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("worker stopped")


if __name__ == "__main__":
    main()
