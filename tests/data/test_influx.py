from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from solariq.config import load_config
from solariq.data.influx import get_today_live_data


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def _make_mock_point(hour, minute, pvpower=0.0, soc_pct=0.0, power_in=0.5, power_out=0.0):
    return {
        "time": f"2026-05-02T{hour:02d}:{minute:02d}:00Z",
        "pvpower": pvpower,
        "soc": soc_pct,
        "power_in": power_in,
        "power_out": power_out,
    }


def test_get_today_live_data_returns_correct_soc(config):
    # soc field is a percentage; battery at 15 kWh out of 23.2 kWh capacity
    soc_pct = 15.0 / 23.2 * 100
    mock_points = [_make_mock_point(h, m, soc_pct=soc_pct) for h in range(24) for m in (0, 30)]
    mock_client = MagicMock()
    mock_client.query.return_value.get_points.return_value = mock_points

    with patch("solariq.data.influx.InfluxDBClient", return_value=mock_client), \
         patch("solariq.data.influx.fetch_agile_prices", return_value=[15.0] * 48), \
         patch("solariq.data.octopus.fetch_export_prices", return_value=[5.0] * 48):
        result = get_today_live_data(config, today=date(2026, 5, 2))

    assert result.battery_soc_pct == pytest.approx(15.0 / 23.2 * 100, abs=0.1)
    assert result.battery_soc_kwh == pytest.approx(15.0, abs=0.1)


def test_get_today_live_data_sums_solar(config):
    # pvpower is kW mean; code converts to kWh via × 0.5h per slot
    mock_points = [_make_mock_point(h, m, pvpower=0.4) for h in range(24) for m in (0, 30)]
    mock_client = MagicMock()
    mock_client.query.return_value.get_points.return_value = mock_points

    with patch("solariq.data.influx.InfluxDBClient", return_value=mock_client), \
         patch("solariq.data.influx.fetch_agile_prices", return_value=[15.0] * 48), \
         patch("solariq.data.octopus.fetch_export_prices", return_value=[5.0] * 48):
        result = get_today_live_data(config, today=date(2026, 5, 2))

    # 2 UTC slots (23:00, 23:30) roll into May 3 in Europe/London (BST, UTC+1) and are filtered
    assert result.solar_today_kwh == pytest.approx(0.4 * 0.5 * 46, abs=0.01)


def test_get_today_live_data_empty_returns_zeros(config):
    mock_client = MagicMock()
    mock_client.query.return_value.get_points.return_value = []

    with patch("solariq.data.influx.InfluxDBClient", return_value=mock_client), \
         patch("solariq.data.influx.fetch_agile_prices", return_value=[15.0] * 48), \
         patch("solariq.data.octopus.fetch_export_prices", return_value=[5.0] * 48):
        result = get_today_live_data(config, today=date(2026, 5, 2))

    assert result.battery_soc_kwh == 0.0
    assert result.solar_today_kwh == 0.0
    assert result.last_data_slot == -1
