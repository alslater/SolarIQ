import json
from pathlib import Path

from solariq.optimizer.types import OptimizationResult

DEFAULT_STRATEGY_PATH = "cache/strategy.json"
DEFAULT_TODAY_PATH = "cache/today.json"

# Keep old name as alias so existing call-sites don't break
DEFAULT_CACHE_PATH = DEFAULT_STRATEGY_PATH


def save_strategy(result: OptimizationResult, path: str = DEFAULT_STRATEGY_PATH) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(result.to_dict(), f, indent=2)


def load_strategy(path: str = DEFAULT_STRATEGY_PATH) -> OptimizationResult | None:
    try:
        with open(path) as f:
            data = json.load(f)
        return OptimizationResult.from_dict(data)
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None


def save_today_snapshot(data: dict, path: str = DEFAULT_TODAY_PATH) -> None:
    """Write the pre-computed today data snapshot produced by the worker."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(path).with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
    tmp.replace(path)  # atomic rename — avoids partial reads by the web instances


def load_today_snapshot(path: str = DEFAULT_TODAY_PATH) -> dict | None:
    """Read the latest today snapshot written by the worker. Returns None if absent."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


DEFAULT_SOLAR_FORECAST_PATH = "cache/solar_forecast_today.json"


def save_solar_forecast_today(slots: list[float], for_date: str, path: str = DEFAULT_SOLAR_FORECAST_PATH) -> None:
    """Atomically write today's Solcast forecast (48 kWh slots) to disk."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(path).with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump({"date": for_date, "slots": slots}, f)
    tmp.replace(path)


def load_solar_forecast_today(path: str = DEFAULT_SOLAR_FORECAST_PATH) -> list[float] | None:
    """Load today's cached Solcast forecast. Returns None if absent, corrupt, or stale (wrong date)."""
    from datetime import date as _date
    try:
        with open(path) as f:
            data = json.load(f)
        if data.get("date") != _date.today().isoformat():
            return None
        slots = data["slots"]
        if len(slots) == 48:
            return slots
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


DEFAULT_TODAY_RATES_PATH = "cache/today_rates.json"


def save_today_rates(agile: list[float], export: list[float], for_date: str, path: str = DEFAULT_TODAY_RATES_PATH) -> None:
    """Atomically write today's agile import and export rates (48 slots each) to disk."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(path).with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump({"date": for_date, "agile": agile, "export": export}, f)
    tmp.replace(path)


def load_today_rates(for_date: str, path: str = DEFAULT_TODAY_RATES_PATH) -> tuple[list[float], list[float]] | None:
    """Load cached agile rates for for_date. Returns (agile, export) or None if absent/stale."""
    try:
        with open(path) as f:
            data = json.load(f)
        if data.get("date") != for_date:
            return None
        agile = data["agile"]
        export = data["export"]
        if len(agile) == 48 and len(export) == 48:
            return agile, export
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


DEFAULT_CALIBRATION_PATH = "cache/calibration.json"


def save_calibration(data: dict, path: str = DEFAULT_CALIBRATION_PATH) -> None:
    """Atomically write calibration data to disk."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(path).with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)


def load_calibration(path: str = DEFAULT_CALIBRATION_PATH) -> dict | None:
    """Load calibration data. Returns None if file is absent or corrupt."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
