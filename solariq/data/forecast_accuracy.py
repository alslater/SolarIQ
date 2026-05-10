"""Forecast accuracy computation for Solcast and forecast.solar vs actual PV."""

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta

from solariq.config import SolarIQConfig
from solariq.data.influx import load_solar_forecast_influx, query_solax_usage_day

logger = logging.getLogger(__name__)


@dataclass
class DayAccuracy:
    date: date
    actual_slots: list[float]           # 48 actual PV kWh/slot
    solcast_slots: list[float]          # 48 Solcast forecast kWh/slot
    forecast_solar_slots: list[float]   # 48 forecast.solar kWh/slot
    solcast_mae: float
    solcast_rmse: float
    forecast_solar_mae: float
    forecast_solar_rmse: float


def _mae(actual: list[float], forecast: list[float]) -> float:
    assert len(actual) == len(forecast)
    return sum(abs(f - a) for a, f in zip(actual, forecast)) / len(actual)


def _rmse(actual: list[float], forecast: list[float]) -> float:
    assert len(actual) == len(forecast)
    return math.sqrt(sum((f - a) ** 2 for a, f in zip(actual, forecast)) / len(actual))


def compute_daily_accuracy(config: SolarIQConfig, target: date) -> "DayAccuracy | None":
    actual = query_solax_usage_day(config, target)
    if all(v == 0.0 for v in actual):
        logger.warning("no actual PV data for %s, skipping", target)
        return None

    solcast = load_solar_forecast_influx(config, target, source="solcast")
    if solcast is None:
        logger.warning("no Solcast forecast for %s, skipping", target)
        return None

    fs = load_solar_forecast_influx(config, target, source="forecast_solar")
    if fs is None:
        logger.warning("no forecast.solar forecast for %s, skipping", target)
        return None

    return DayAccuracy(
        date=target,
        actual_slots=actual,
        solcast_slots=solcast,
        forecast_solar_slots=fs,
        solcast_mae=_mae(actual, solcast),
        solcast_rmse=_rmse(actual, solcast),
        forecast_solar_mae=_mae(actual, fs),
        forecast_solar_rmse=_rmse(actual, fs),
    )


def compute_range_accuracy(
    config: SolarIQConfig, start_date: date, end_date: date
) -> list[DayAccuracy]:
    results = []
    current = start_date
    while current <= end_date:
        day = compute_daily_accuracy(config, current)
        if day is not None:
            results.append(day)
        current += timedelta(days=1)
    return results
