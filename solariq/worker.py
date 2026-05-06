"""Standalone background worker.

Runs all scheduled data fetches so web instances share a single set of API
calls rather than each making their own.  Results are written to the shared
cache directory (cache/today.json and cache/strategy.json), which web
instances read every 30 seconds.

Usage:
    python -m solariq.worker          # production
    uv run python -m solariq.worker

Docker: uses the same image as the web service, different CMD:
    command: ["uv", "run", "python", "-m", "solariq.worker"]
"""

import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from solariq.app_settings import (
    OPTIMIZATION_SOURCE_FORECAST_SOLAR,
    ForecastSettings,
    get_forecast_settings,
)
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
from solariq.data.forecast_solar import fetch_forecast_solar, fetch_forecast_solar_with_coverage
from solariq.data.influx import get_today_live_data, load_solar_forecast_influx, save_solar_forecast_influx
from solariq.data.load_profile import build_load_profile
from solariq.data.octopus import (
    UNPUBLISHED_RATE_CAP_P,
    fetch_agile_prices,
    fetch_export_prices,
    fetch_standing_charge_p_per_day,
    fill_unpublished_slots,
)
from solariq.data.solcast import fetch_solar_forecast, fetch_solar_forecast_with_coverage
from solariq.logging_config import setup_logging
from solariq.optimizer.solver import solve
from solariq.optimizer.strategy import build_rolling_window, current_window_start

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


def _get_forecast_settings() -> ForecastSettings:
    config = _get_config()
    return get_forecast_settings(config.app.auth_db_path)


def _selected_forecast(
    settings: ForecastSettings,
    solcast_slots: list[float] | None,
    forecast_solar_slots: list[float] | None,
) -> tuple[list[float], bool]:
    """Return selected forecast slots and whether data was estimated/missing."""
    if settings.optimization_source == OPTIMIZATION_SOURCE_FORECAST_SOLAR:
        if forecast_solar_slots is not None:
            return forecast_solar_slots, False
        if solcast_slots is not None:
            return solcast_slots, False
        return [0.0] * 48, True

    if solcast_slots is not None:
        return solcast_slots, False
    if forecast_solar_slots is not None:
        return forecast_solar_slots, False
    return [0.0] * 48, True


def _load_or_refresh_today_forecast(
    config: SolarIQConfig,
    today_str: str,
    *,
    enabled: bool,
    source: str,
    refresh_fn,
    label: str,
) -> list[float] | None:
    if not enabled:
        return None

    slots = load_solar_forecast_today(config, today_str, source=source)
    if slots is not None:
        return slots

    try:
        refresh_fn()
        return load_solar_forecast_today(config, today_str, source=source)
    except Exception as exc:
        logger.warning("inline %s refresh failed: %s", label, exc)
        return None


def _tomorrow(config: SolarIQConfig) -> date:
    tz = ZoneInfo(config.app.timezone)
    return (datetime.now(tz) + timedelta(days=1)).date()


def _after_refresh_time(config: SolarIQConfig) -> bool:
    tz = ZoneInfo(config.app.timezone)
    now = datetime.now(tz)
    h, m = (int(x) for x in config.app.refresh_time.split(":"))
    return now >= now.replace(hour=h, minute=m, second=0, microsecond=0)


def _strategy_needs_refresh(config: SolarIQConfig, agile_tomorrow: list[float]) -> bool:
    """Return True if we should recompute the strategy.

    Blocks if tomorrow's prices aren't published (all at the unpublished cap),
    unless test_strategy_mode is enabled.
    Regenerates if no cached strategy exists or the cached window has expired.
    """
    if not config.app.test_strategy_mode and all(p >= UNPUBLISHED_RATE_CAP_P for p in agile_tomorrow):
        return False  # prices not yet published
    cached = load_strategy()
    if cached is None:
        return True
    tz = ZoneInfo(config.app.timezone)
    try:
        valid_until = datetime.fromisoformat(cached.valid_until).astimezone(tz)
    except (ValueError, AttributeError):
        return True  # malformed or old cache without valid_until
    return datetime.now(tz) >= valid_until


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
        today_str = date.today().isoformat()
        settings = _get_forecast_settings()

        solcast_forecast = _load_or_refresh_today_forecast(
            config,
            today_str,
            enabled=settings.collect_solcast,
            source="solcast",
            refresh_fn=refresh_solar_forecast_today,
            label="Solcast",
        )

        forecast_solar_forecast = _load_or_refresh_today_forecast(
            config,
            today_str,
            enabled=settings.collect_forecast_solar,
            source="forecast_solar",
            refresh_fn=refresh_forecast_solar_today,
            label="forecast.solar",
        )

        selected_forecast, _ = _selected_forecast(settings, solcast_forecast, forecast_solar_forecast)
        solcast_for_chart = solcast_forecast or [0.0] * 48
        forecast_solar_for_chart = forecast_solar_forecast or [0.0] * 48

        chart_data = []
        for i in range(48):
            chart_data.append({
                "time": timestamps[i],
                "grid_import": round(today_data.actual_grid_import[i] or 0.0, 3),
                "grid_export": round(today_data.actual_grid_export[i] or 0.0, 3),
                "solar": round(today_data.actual_solar[i] or 0.0, 3),
                "predicted_solar": round(selected_forecast[i], 3),
                "predicted_solar_solcast": round(solcast_for_chart[i], 3),
                "predicted_solar_forecast_solar": round(forecast_solar_for_chart[i], 3),
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
                "import": 0.0 if today_data.agile_prices[i] >= UNPUBLISHED_RATE_CAP_P else today_data.agile_prices[i],
                "export": 0.0 if today_data.export_prices[i] >= UNPUBLISHED_RATE_CAP_P else today_data.export_prices[i],
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
    """Compute and cache a rolling 48-slot strategy if conditions are met."""
    config = _get_config()
    tz = ZoneInfo(config.app.timezone)
    tomorrow = _tomorrow(config)
    try:
        agile_tomorrow = fetch_agile_prices(config, tomorrow)
    except Exception as exc:
        logger.warning("could not fetch tomorrow's agile prices for strategy check: %s", exc)
        return
    if not _strategy_needs_refresh(config, agile_tomorrow):
        return

    logger.info("refreshing rolling window strategy%s", " [TEST MODE]" if config.app.test_strategy_mode else "")
    try:
        settings = _get_forecast_settings()
        today = datetime.now(tz).date()
        current_slot, window_start = current_window_start(config.app.timezone)

        agile_today = fetch_agile_prices(config, today)
        export_today = fetch_export_prices(config, today)
        export_tomorrow = fetch_export_prices(config, tomorrow)

        solcast_today = load_solar_forecast_influx(config, today, source="solcast") if settings.collect_solcast else None
        solcast_tomorrow = load_solar_forecast_influx(config, tomorrow, source="solcast") if settings.collect_solcast else None
        if settings.collect_solcast and solcast_tomorrow is None:
            try:
                solcast_tomorrow = fetch_solar_forecast(config, tomorrow)
                try:
                    save_solar_forecast_influx(config, solcast_tomorrow, tomorrow, source="solcast")
                except Exception as exc:
                    logger.warning("failed to cache tomorrow's Solcast forecast: %s", exc)
            except Exception as exc:
                logger.warning("Solcast unavailable for strategy: %s", exc)

        forecast_solar_today = (
            load_solar_forecast_influx(config, today, source="forecast_solar")
            if settings.collect_forecast_solar
            else None
        )
        forecast_solar_tomorrow = (
            load_solar_forecast_influx(config, tomorrow, source="forecast_solar")
            if settings.collect_forecast_solar
            else None
        )
        if settings.collect_forecast_solar and forecast_solar_tomorrow is None:
            try:
                forecast_solar_tomorrow = fetch_forecast_solar(config, tomorrow)
                try:
                    save_solar_forecast_influx(
                        config,
                        forecast_solar_tomorrow,
                        tomorrow,
                        source="forecast_solar",
                    )
                except Exception as exc:
                    logger.warning("failed to cache tomorrow's forecast.solar forecast: %s", exc)
            except Exception as exc:
                logger.warning("forecast.solar unavailable for strategy: %s", exc)

        solar_today_selected, _ = _selected_forecast(settings, solcast_today, forecast_solar_today)
        solar_tomorrow_selected, solar_estimated = _selected_forecast(settings, solcast_tomorrow, forecast_solar_tomorrow)

        load_today = build_load_profile(config, today)
        load_tomorrow = build_load_profile(config, tomorrow)

        if config.app.test_strategy_mode:
            tomorrow_agile_published = any(p < UNPUBLISHED_RATE_CAP_P for p in agile_tomorrow)
            agile_for_today = fill_unpublished_slots(agile_today)
            agile_for_tomorrow = agile_tomorrow if tomorrow_agile_published else fill_unpublished_slots(agile_today)
            export_today_eff = fill_unpublished_slots(export_today)
            tomorrow_export_published = any(p < UNPUBLISHED_RATE_CAP_P for p in export_tomorrow)
            export_tomorrow_eff = export_tomorrow if tomorrow_export_published else fill_unpublished_slots(export_today)
            logger.info(
                "[TEST MODE] agile tomorrow: %s, export tomorrow: %s",
                "published" if tomorrow_agile_published else "using today's",
                "published" if tomorrow_export_published else "using today's",
            )
        else:
            agile_for_today = agile_today
            agile_for_tomorrow = agile_tomorrow
            export_today_eff = export_today
            export_tomorrow_eff = export_tomorrow
        agile = build_rolling_window(agile_for_today, agile_for_tomorrow, current_slot)
        export = build_rolling_window(export_today_eff, export_tomorrow_eff, current_slot)
        solar = build_rolling_window(solar_today_selected, solar_tomorrow_selected, current_slot)
        load = build_rolling_window(load_today, load_tomorrow, current_slot)

        today_data = get_today_live_data(config)
        initial_soc = today_data.battery_soc_kwh or (config.battery.capacity_kwh * 0.5)

        result = solve(agile, export, solar, load, initial_soc, config, window_start)
        result.solar_forecast_estimated = solar_estimated
        save_strategy(result)
        logger.info("strategy saved, valid until %s, estimated cost £%.2f", result.valid_until, result.estimated_cost_gbp)
    except Exception as exc:
        logger.error("strategy refresh failed: %s", exc, exc_info=True)


def refresh_solar_forecast_today() -> None:
    """Fetch today's Solcast forecast only when enabled and absent from InfluxDB."""
    config = _get_config()
    settings = _get_forecast_settings()
    if not settings.collect_solcast:
        logger.info("Solcast collection disabled in settings; skipping")
        return
    today = date.today()
    cached_slots = load_solar_forecast_today(config, today.isoformat(), source="solcast")
    if cached_slots is not None:
        logger.info("today's Solcast forecast already present in InfluxDB for %s; skipping refresh", today)
        return

    logger.info("refreshing Solcast forecast for %s", today)
    try:
        slots, covered_slots = fetch_solar_forecast_with_coverage(config, today)
        save_solar_forecast_today(config, slots, today.isoformat(), source="solcast")
        logger.info(
            "solar forecast saved to InfluxDB: total %.2f kWh (%d API slots)",
            sum(slots),
            len(covered_slots),
        )
    except Exception as exc:
        logger.warning("solar forecast refresh failed: %s", exc)


def refresh_forecast_solar_today() -> None:
    """Fetch today's forecast.solar forecast only when enabled and absent from InfluxDB."""
    config = _get_config()
    settings = _get_forecast_settings()
    if not settings.collect_forecast_solar:
        logger.info("forecast.solar collection disabled in settings; skipping")
        return

    today = date.today()
    cached_slots = load_solar_forecast_today(config, today.isoformat(), source="forecast_solar")
    if cached_slots is not None:
        logger.info("today's forecast.solar already present in InfluxDB for %s; skipping refresh", today)
        return

    logger.info("refreshing forecast.solar for %s", today)
    try:
        slots, covered_slots = fetch_forecast_solar_with_coverage(config, today)
        save_solar_forecast_today(config, slots, today.isoformat(), source="forecast_solar")
        logger.info(
            "forecast.solar saved to InfluxDB: total %.2f kWh (%d API slots)",
            sum(slots),
            len(covered_slots),
        )
    except Exception as exc:
        logger.warning("forecast.solar refresh failed: %s", exc)


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

    # Fetch today's solar forecast sources on startup
    refresh_solar_forecast_today()
    refresh_forecast_solar_today()

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
        refresh_forecast_solar_today,
        CronTrigger(hour="0,5,12", minute=7, timezone="UTC"),
        id="refresh_forecast_solar_today",
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
