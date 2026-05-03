import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from solariq.config import SolarIQConfig
from solariq.data.influx import get_historical_range_data
from solariq.data.octopus import fetch_octopus_export_consumption_kwh

logger = logging.getLogger(__name__)

WINDOW_DAYS = 30


def compute_export_factor(config: SolarIQConfig) -> dict:
    """Compute export correction factor: octopus_kwh / influx_kwh over last 30 days.

    Returns a dict with factor, octopus_kwh, influx_kwh, computed_at, window_days.
    Returns factor=1.0 if config is incomplete or either data source yields zero.
    """
    if not config.octopus.export_mpan or not config.octopus.export_serial_number:
        logger.warning("export_mpan or export_serial_number not configured — skipping calibration")
        return _default_result()

    tz = ZoneInfo(config.app.timezone)
    end_date = (datetime.now(tz) - timedelta(days=1)).date()
    start_date = end_date - timedelta(days=WINDOW_DAYS - 1)

    logger.info("computing export factor for %s..%s", start_date, end_date)

    octopus_kwh = fetch_octopus_export_consumption_kwh(config, start_date, end_date)
    rows = get_historical_range_data(config, start_date, end_date)
    influx_kwh = sum(r["grid_export_kwh"] for r in rows)

    if influx_kwh <= 0:
        logger.warning("InfluxDB export total is zero for window — returning factor 1.0")
        return _default_result()

    if octopus_kwh <= 0:
        logger.warning("Octopus export total is zero for window — returning factor 1.0")
        return _default_result()

    factor = round(octopus_kwh / influx_kwh, 4)
    logger.info(
        "export factor: %.4f (octopus=%.2f kWh, influx=%.2f kWh)",
        factor, octopus_kwh, influx_kwh,
    )
    return {
        "factor": factor,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "octopus_kwh": round(octopus_kwh, 2),
        "influx_kwh": round(influx_kwh, 2),
        "window_days": WINDOW_DAYS,
    }


def _default_result() -> dict:
    return {
        "factor": 1.0,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "octopus_kwh": 0.0,
        "influx_kwh": 0.0,
        "window_days": WINDOW_DAYS,
    }
