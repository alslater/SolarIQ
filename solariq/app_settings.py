from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


OPTIMIZATION_SOURCE_SOLCAST = "solcast"
OPTIMIZATION_SOURCE_FORECAST_SOLAR = "forecast_solar"


@dataclass(frozen=True)
class ForecastSettings:
    collect_solcast: bool = True
    collect_forecast_solar: bool = False
    optimization_source: str = OPTIMIZATION_SOURCE_SOLCAST
    today_show_solcast: bool = True
    today_show_forecast_solar: bool = False


_DEFAULTS: dict[str, str] = {
    "collect_solcast": "1",
    "collect_forecast_solar": "0",
    "optimization_source": OPTIMIZATION_SOURCE_SOLCAST,
    "today_show_solcast": "1",
    "today_show_forecast_solar": "0",
}


def _connect(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_app_settings_db(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        now = _utcnow()
        for key, value in _DEFAULTS.items():
            conn.execute(
                """
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO NOTHING
                """,
                (key, value, now),
            )


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_forecast_settings(db_path: str) -> ForecastSettings:
    init_app_settings_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    values = {str(r["key"]): str(r["value"]) for r in rows}

    optimization_source = values.get("optimization_source", OPTIMIZATION_SOURCE_SOLCAST)
    if optimization_source not in {OPTIMIZATION_SOURCE_SOLCAST, OPTIMIZATION_SOURCE_FORECAST_SOLAR}:
        optimization_source = OPTIMIZATION_SOURCE_SOLCAST

    return ForecastSettings(
        collect_solcast=_parse_bool(values.get("collect_solcast", _DEFAULTS["collect_solcast"]), True),
        collect_forecast_solar=_parse_bool(
            values.get("collect_forecast_solar", _DEFAULTS["collect_forecast_solar"]),
            False,
        ),
        optimization_source=optimization_source,
        today_show_solcast=_parse_bool(values.get("today_show_solcast", _DEFAULTS["today_show_solcast"]), True),
        today_show_forecast_solar=_parse_bool(
            values.get("today_show_forecast_solar", _DEFAULTS["today_show_forecast_solar"]),
            False,
        ),
    )


def _set_value(db_path: str, key: str, value: str) -> None:
    init_app_settings_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
              value = excluded.value,
              updated_at = excluded.updated_at
            """,
            (key, value, _utcnow()),
        )


def set_collect_solcast(db_path: str, enabled: bool) -> None:
    _set_value(db_path, "collect_solcast", "1" if enabled else "0")


def set_collect_forecast_solar(db_path: str, enabled: bool) -> None:
    _set_value(db_path, "collect_forecast_solar", "1" if enabled else "0")


def set_optimization_source(db_path: str, source: str) -> None:
    if source not in {OPTIMIZATION_SOURCE_SOLCAST, OPTIMIZATION_SOURCE_FORECAST_SOLAR}:
        raise ValueError("Unsupported optimization source.")
    _set_value(db_path, "optimization_source", source)


def set_today_show_solcast(db_path: str, enabled: bool) -> None:
    _set_value(db_path, "today_show_solcast", "1" if enabled else "0")


def set_today_show_forecast_solar(db_path: str, enabled: bool) -> None:
    _set_value(db_path, "today_show_forecast_solar", "1" if enabled else "0")