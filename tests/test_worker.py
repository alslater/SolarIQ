from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from solariq.app_settings import ForecastSettings
from solariq.config import load_config
from solariq.worker import refresh_solar_forecast_today


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def test_refresh_solar_forecast_today_skips_when_present(config):
    today = date.today().isoformat()

    with (
        patch("solariq.worker._get_config", return_value=config),
        patch("solariq.worker._get_forecast_settings", return_value=ForecastSettings(collect_solcast=True)),
        patch("solariq.worker.load_solar_forecast_today", return_value=[0.1] * 48) as load_mock,
        patch("solariq.worker.fetch_solar_forecast_with_coverage") as fetch_mock,
        patch("solariq.worker.save_solar_forecast_today") as save_mock,
    ):
        refresh_solar_forecast_today()

    load_mock.assert_called_once_with(config, today, source="solcast")
    fetch_mock.assert_not_called()
    save_mock.assert_not_called()


def test_refresh_solar_forecast_today_fetches_when_missing(config):
    today = date.today()
    slots = [0.2] * 48

    with (
        patch("solariq.worker._get_config", return_value=config),
        patch("solariq.worker._get_forecast_settings", return_value=ForecastSettings(collect_solcast=True)),
        patch("solariq.worker.load_solar_forecast_today", return_value=None) as load_mock,
        patch(
            "solariq.worker.fetch_solar_forecast_with_coverage",
            return_value=(slots, set(range(48))),
        ) as fetch_mock,
        patch("solariq.worker.save_solar_forecast_today") as save_mock,
    ):
        refresh_solar_forecast_today()

    load_mock.assert_called_once_with(config, today.isoformat(), source="solcast")
    fetch_mock.assert_called_once_with(config, today)
    save_mock.assert_called_once_with(config, slots, today.isoformat(), source="solcast")