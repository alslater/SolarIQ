import json
from pathlib import Path

from solariq.config import load_config
from solariq.optimizer.types import OptimizationResult

DEFAULT_CACHE_DIR = "cache"
STRATEGY_FILENAME = "strategy.json"
TODAY_FILENAME = "today.json"
SOLAR_FORECAST_FILENAME = "solar_forecast_today.json"
TODAY_RATES_FILENAME = "today_rates.json"
CALIBRATION_FILENAME = "calibration.json"


def _configured_cache_dir() -> str:
    try:
        return load_config().app.cache_dir
    except Exception:
        return DEFAULT_CACHE_DIR


def _resolve_path(path: str | None, filename: str) -> Path:
    if path is not None:
        return Path(path)
    return Path(_configured_cache_dir()) / filename


def get_cache_paths(base_dir: str | None = None) -> tuple[str, str, str, str, str]:
    cache_dir = base_dir or _configured_cache_dir()
    return (
        str(Path(cache_dir) / TODAY_FILENAME),
        str(Path(cache_dir) / STRATEGY_FILENAME),
        str(Path(cache_dir) / SOLAR_FORECAST_FILENAME),
        str(Path(cache_dir) / CALIBRATION_FILENAME),
        str(Path(cache_dir) / TODAY_RATES_FILENAME),
    )


DEFAULT_STRATEGY_PATH = str(Path(DEFAULT_CACHE_DIR) / STRATEGY_FILENAME)
DEFAULT_TODAY_PATH = str(Path(DEFAULT_CACHE_DIR) / TODAY_FILENAME)

# Keep old name as alias so existing call-sites don't break
DEFAULT_CACHE_PATH = DEFAULT_STRATEGY_PATH


def save_strategy(result: OptimizationResult, path: str | None = None) -> None:
    target = _resolve_path(path, STRATEGY_FILENAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(result.to_dict(), f, indent=2)
    tmp.replace(target)


def load_strategy(path: str | None = None) -> OptimizationResult | None:
    target = _resolve_path(path, STRATEGY_FILENAME)
    try:
        with open(target) as f:
            data = json.load(f)
        return OptimizationResult.from_dict(data)
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None


def save_today_snapshot(data: dict, path: str | None = None) -> None:
    """Write the pre-computed today data snapshot produced by the worker."""
    target = _resolve_path(path, TODAY_FILENAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
    tmp.replace(target)  # atomic rename — avoids partial reads by the web instances


def load_today_snapshot(path: str | None = None) -> dict | None:
    """Read the latest today snapshot written by the worker. Returns None if absent."""
    target = _resolve_path(path, TODAY_FILENAME)
    try:
        with open(target) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


DEFAULT_SOLAR_FORECAST_PATH = str(Path(DEFAULT_CACHE_DIR) / SOLAR_FORECAST_FILENAME)


def save_solar_forecast_today(slots: list[float], for_date: str, path: str | None = None) -> None:
    """Atomically write today's Solcast forecast (48 kWh slots) to disk."""
    target = _resolve_path(path, SOLAR_FORECAST_FILENAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump({"date": for_date, "slots": slots}, f)
    tmp.replace(target)


def load_solar_forecast_today(path: str | None = None) -> list[float] | None:
    """Load today's cached Solcast forecast. Returns None if absent, corrupt, or stale (wrong date)."""
    from datetime import date as _date
    target = _resolve_path(path, SOLAR_FORECAST_FILENAME)
    try:
        with open(target) as f:
            data = json.load(f)
        if data.get("date") != _date.today().isoformat():
            return None
        slots = data["slots"]
        if len(slots) == 48:
            return slots
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


DEFAULT_TODAY_RATES_PATH = str(Path(DEFAULT_CACHE_DIR) / TODAY_RATES_FILENAME)


def save_today_rates(agile: list[float], export: list[float], for_date: str, path: str | None = None) -> None:
    """Atomically write today's agile import and export rates (48 slots each) to disk."""
    target = _resolve_path(path, TODAY_RATES_FILENAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump({"date": for_date, "agile": agile, "export": export}, f)
    tmp.replace(target)


def load_today_rates(for_date: str, path: str | None = None) -> tuple[list[float], list[float]] | None:
    """Load cached agile rates for for_date. Returns (agile, export) or None if absent/stale."""
    target = _resolve_path(path, TODAY_RATES_FILENAME)
    try:
        with open(target) as f:
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


DEFAULT_CALIBRATION_PATH = str(Path(DEFAULT_CACHE_DIR) / CALIBRATION_FILENAME)


def save_calibration(data: dict, path: str | None = None) -> None:
    """Atomically write calibration data to disk."""
    target = _resolve_path(path, CALIBRATION_FILENAME)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(target)


def load_calibration(path: str | None = None) -> dict | None:
    """Load calibration data. Returns None if file is absent or corrupt."""
    target = _resolve_path(path, CALIBRATION_FILENAME)
    try:
        with open(target) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
