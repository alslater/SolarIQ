from datetime import date
from unittest.mock import patch

import pytest

from solariq.app_settings import ForecastSettings
from solariq.config import load_config
from solariq.worker import refresh_forecast_solar_today


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def test_refresh_forecast_solar_today_skips_when_disabled(config):
    """When collect_forecast_solar is False the function returns early without any I/O."""
    with (
        patch("solariq.worker._get_config", return_value=config),
        patch(
            "solariq.worker._get_forecast_settings",
            return_value=ForecastSettings(collect_forecast_solar=False),
        ),
        patch("solariq.worker.load_solar_forecast_today") as load_mock,
        patch("solariq.worker.fetch_forecast_solar_with_coverage") as fetch_mock,
        patch("solariq.worker.save_solar_forecast_today") as save_mock,
    ):
        refresh_forecast_solar_today()

    load_mock.assert_not_called()
    fetch_mock.assert_not_called()
    save_mock.assert_not_called()


def test_refresh_forecast_solar_today_skips_when_present(config):
    """When a cached forecast already exists the function skips the fetch."""
    today = date.today().isoformat()

    with (
        patch("solariq.worker._get_config", return_value=config),
        patch(
            "solariq.worker._get_forecast_settings",
            return_value=ForecastSettings(collect_forecast_solar=True),
        ),
        patch("solariq.worker.load_solar_forecast_today", return_value=[0.1] * 48) as load_mock,
        patch("solariq.worker.fetch_forecast_solar_with_coverage") as fetch_mock,
        patch("solariq.worker.save_solar_forecast_today") as save_mock,
    ):
        refresh_forecast_solar_today()

    load_mock.assert_called_once_with(config, today, source="forecast_solar")
    fetch_mock.assert_not_called()
    save_mock.assert_not_called()


def test_refresh_forecast_solar_today_fetches_when_missing(config):
    """When no cached forecast exists the function fetches and saves."""
    today = date.today()
    slots = [0.3] * 48

    with (
        patch("solariq.worker._get_config", return_value=config),
        patch(
            "solariq.worker._get_forecast_settings",
            return_value=ForecastSettings(collect_forecast_solar=True),
        ),
        patch("solariq.worker.load_solar_forecast_today", return_value=None) as load_mock,
        patch(
            "solariq.worker.fetch_forecast_solar_with_coverage",
            return_value=(slots, set(range(48))),
        ) as fetch_mock,
        patch("solariq.worker.save_solar_forecast_today") as save_mock,
    ):
        refresh_forecast_solar_today()

    load_mock.assert_called_once_with(config, today.isoformat(), source="forecast_solar")
    fetch_mock.assert_called_once_with(config, today)
    save_mock.assert_called_once_with(config, slots, today.isoformat(), source="forecast_solar")


def test_refresh_forecast_solar_today_swallows_fetch_error(config):
    """A fetch failure is logged and swallowed; no exception propagates."""
    today = date.today()

    with (
        patch("solariq.worker._get_config", return_value=config),
        patch(
            "solariq.worker._get_forecast_settings",
            return_value=ForecastSettings(collect_forecast_solar=True),
        ),
        patch("solariq.worker.load_solar_forecast_today", return_value=None),
        patch(
            "solariq.worker.fetch_forecast_solar_with_coverage",
            side_effect=RuntimeError("API unreachable"),
        ),
        patch("solariq.worker.save_solar_forecast_today") as save_mock,
    ):
        refresh_forecast_solar_today()  # must not raise

    save_mock.assert_not_called()
