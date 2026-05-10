"""Forecast accuracy computation for Solcast and forecast.solar vs actual PV."""

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from solariq.config import SolarIQConfig
from solariq.data.influx import load_solar_forecast_influx, query_solax_pv_day

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
    if len(actual) != len(forecast):
        raise ValueError(f"actual and forecast must have the same length ({len(actual)} vs {len(forecast)})")
    pairs = [(a, f) for a, f in zip(actual, forecast) if a > 0.0]
    if not pairs:
        return 0.0
    return sum(abs(f - a) for a, f in pairs) / len(pairs)


def _rmse(actual: list[float], forecast: list[float]) -> float:
    if len(actual) != len(forecast):
        raise ValueError(f"actual and forecast must have the same length ({len(actual)} vs {len(forecast)})")
    pairs = [(a, f) for a, f in zip(actual, forecast) if a > 0.0]
    if not pairs:
        return 0.0
    return math.sqrt(sum((f - a) ** 2 for a, f in pairs) / len(pairs))


def compute_daily_accuracy(config: SolarIQConfig, target: date) -> "DayAccuracy | None":
    actual = query_solax_pv_day(config, target)
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


ForecastSource = Literal["solcast", "forecast_solar"]


def _daylight_pairs(results: list[DayAccuracy], source: ForecastSource) -> list[tuple[float, float]]:
    if source == "solcast":
        return [(a, f) for r in results for a, f in zip(r.actual_slots, r.solcast_slots) if a > 0.0]
    if source == "forecast_solar":
        return [(a, f) for r in results for a, f in zip(r.actual_slots, r.forecast_solar_slots) if a > 0.0]
    raise ValueError(f"unknown source {source!r}; expected 'solcast' or 'forecast_solar'")


def overall_mae(results: list[DayAccuracy], source: ForecastSource) -> float:
    """True MAE across all daylight slots in the result set."""
    pairs = _daylight_pairs(results, source)
    if not pairs:
        return 0.0
    return sum(abs(f - a) for a, f in pairs) / len(pairs)


def overall_rmse(results: list[DayAccuracy], source: ForecastSource) -> float:
    """True RMSE across all daylight slots in the result set (single sqrt over pooled MSE)."""
    pairs = _daylight_pairs(results, source)
    if not pairs:
        return 0.0
    return math.sqrt(sum((f - a) ** 2 for a, f in pairs) / len(pairs))


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
