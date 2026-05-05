import pytest

from solariq.app_settings import (
    OPTIMIZATION_SOURCE_FORECAST_SOLAR,
    OPTIMIZATION_SOURCE_SOLCAST,
    ForecastSettings,
    get_forecast_settings,
    init_app_settings_db,
    set_collect_forecast_solar,
    set_collect_solcast,
    set_optimization_source,
    set_today_show_forecast_solar,
    set_today_show_solcast,
)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_auth.db")


# ── init ──────────────────────────────────────────────────────────────────────

def test_init_creates_table_and_defaults(db_path):
    """init_app_settings_db creates the table and inserts default values."""
    init_app_settings_db(db_path)
    settings = get_forecast_settings(db_path)

    assert settings.collect_solcast is True
    assert settings.collect_forecast_solar is False
    assert settings.optimization_source == OPTIMIZATION_SOURCE_SOLCAST
    assert settings.today_show_solcast is True
    assert settings.today_show_forecast_solar is False


def test_init_is_idempotent(db_path):
    """Calling init_app_settings_db twice does not raise or overwrite existing values."""
    init_app_settings_db(db_path)
    set_collect_solcast(db_path, False)
    init_app_settings_db(db_path)  # second call must not reset the value

    settings = get_forecast_settings(db_path)
    assert settings.collect_solcast is False


# ── get round-trips ───────────────────────────────────────────────────────────

def test_get_forecast_settings_returns_frozen_dataclass(db_path):
    settings = get_forecast_settings(db_path)
    assert isinstance(settings, ForecastSettings)
    with pytest.raises(Exception):
        settings.collect_solcast = True  # frozen=True


# ── boolean setter round-trips ────────────────────────────────────────────────

def test_set_collect_solcast_roundtrip(db_path):
    set_collect_solcast(db_path, False)
    assert get_forecast_settings(db_path).collect_solcast is False

    set_collect_solcast(db_path, True)
    assert get_forecast_settings(db_path).collect_solcast is True


def test_set_collect_forecast_solar_roundtrip(db_path):
    set_collect_forecast_solar(db_path, True)
    assert get_forecast_settings(db_path).collect_forecast_solar is True

    set_collect_forecast_solar(db_path, False)
    assert get_forecast_settings(db_path).collect_forecast_solar is False


def test_set_today_show_solcast_roundtrip(db_path):
    set_today_show_solcast(db_path, False)
    assert get_forecast_settings(db_path).today_show_solcast is False

    set_today_show_solcast(db_path, True)
    assert get_forecast_settings(db_path).today_show_solcast is True


def test_set_today_show_forecast_solar_roundtrip(db_path):
    set_today_show_forecast_solar(db_path, True)
    assert get_forecast_settings(db_path).today_show_forecast_solar is True

    set_today_show_forecast_solar(db_path, False)
    assert get_forecast_settings(db_path).today_show_forecast_solar is False


# ── optimization source ───────────────────────────────────────────────────────

def test_set_optimization_source_roundtrip(db_path):
    set_optimization_source(db_path, OPTIMIZATION_SOURCE_FORECAST_SOLAR)
    assert get_forecast_settings(db_path).optimization_source == OPTIMIZATION_SOURCE_FORECAST_SOLAR

    set_optimization_source(db_path, OPTIMIZATION_SOURCE_SOLCAST)
    assert get_forecast_settings(db_path).optimization_source == OPTIMIZATION_SOURCE_SOLCAST


def test_set_optimization_source_rejects_invalid(db_path):
    with pytest.raises(ValueError):
        set_optimization_source(db_path, "bogus_source")


def test_get_forecast_settings_coerces_invalid_source_to_solcast(db_path):
    """A corrupted DB value falls back to solcast rather than surfacing an invalid string."""
    import sqlite3
    init_app_settings_db(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE app_settings SET value = 'unknown' WHERE key = 'optimization_source'"
        )

    settings = get_forecast_settings(db_path)
    assert settings.optimization_source == OPTIMIZATION_SOURCE_SOLCAST
