from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from solariq.config import load_config
from solariq.data.influx import get_historical_range_data


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def _make_solax_point(date_str, hour, minute, pvpower=0.0, power_in=0.0, power_out=0.0):
    return {
        "time": f"{date_str}T{hour:02d}:{minute:02d}:00Z",
        "pvpower": pvpower,
        "power_in": power_in,
        "power_out": power_out,
    }


def _make_rate_point(date_str, hour, minute, agile_rate=0.0, export_rate=0.0):
    return {
        "time": f"{date_str}T{hour:02d}:{minute:02d}:00Z",
        "agile_rate": agile_rate,
        "export_rate": export_rate,
    }


def _make_forecast_point(date_str, hour, minute, pv_estimate_kwh=0.0):
    return {
        "time": f"{date_str}T{hour:02d}:{minute:02d}:00Z",
        "pv_estimate_kwh": pv_estimate_kwh,
    }


def test_solar_saving_gbp_in_rows(config):
    """solar_saving_gbp = solar_kwh × import_rate / 100 per slot, summed per bucket."""
    # One slot: 2 kW solar mean → 1 kWh; import rate 20p/kWh → saving = 0.20 £
    # Use UTC 11:00 on 2026-04-01 = 12:00 BST, slot 24 (index 24 = 12:00 local)
    solax_points = [_make_solax_point("2026-04-01", 11, 0, pvpower=2.0)]
    rate_points = [_make_rate_point("2026-04-01", 11, 0, agile_rate=20.0)]

    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = solax_points

    agile_mock = MagicMock()
    agile_mock.query.return_value.get_points.return_value = rate_points

    solcast_mock = MagicMock()
    solcast_mock.query.return_value.get_points.return_value = []
    forecast_solar_mock = MagicMock()
    forecast_solar_mock.query.return_value.get_points.return_value = []

    with patch(
        "solariq.data.influx.InfluxDBClient",
        side_effect=[solax_mock, agile_mock, solcast_mock, forecast_solar_mock],
    ):
        rows = get_historical_range_data(
            config,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 1),
        )

    assert "solar_saving_gbp" in rows[0]
    # 2 kW × 0.5 h = 1 kWh; 1 kWh × 20 p = 20 p = £0.20
    # UTC 11:00 = BST 12:00 → hourly bucket index 12 for a single-day query
    total_saving = sum(r["solar_saving_gbp"] for r in rows)
    assert total_saving == pytest.approx(0.20, abs=0.001)


def test_solar_saving_gbp_zero_when_no_rates(config):
    """solar_saving_gbp is 0.0 for all rows when the rate query returns no data."""
    solax_points = [_make_solax_point("2026-04-01", 11, 0, pvpower=2.0)]

    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = solax_points

    agile_mock = MagicMock()
    agile_mock.query.return_value.get_points.return_value = []

    solcast_mock = MagicMock()
    solcast_mock.query.return_value.get_points.return_value = []
    forecast_solar_mock = MagicMock()
    forecast_solar_mock.query.return_value.get_points.return_value = []

    with patch(
        "solariq.data.influx.InfluxDBClient",
        side_effect=[solax_mock, agile_mock, solcast_mock, forecast_solar_mock],
    ):
        rows = get_historical_range_data(
            config,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 1),
        )

    assert rows[0]["solar_saving_gbp"] == pytest.approx(0.0)


def test_solar_saving_gbp_present_in_all_rows(config):
    """Every row contains solar_saving_gbp, including empty buckets."""
    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = []

    agile_mock = MagicMock()
    agile_mock.query.return_value.get_points.return_value = []

    solcast_mock = MagicMock()
    solcast_mock.query.return_value.get_points.return_value = []
    forecast_solar_mock = MagicMock()
    forecast_solar_mock.query.return_value.get_points.return_value = []

    with patch(
        "solariq.data.influx.InfluxDBClient",
        side_effect=[solax_mock, agile_mock, solcast_mock, forecast_solar_mock],
    ):
        rows = get_historical_range_data(
            config,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 3),
        )

    assert all("solar_saving_gbp" in r for r in rows)


def test_predicted_solar_kwh_in_rows(config):
    """predicted_solar_kwh from solar_forecast is aggregated into output rows."""
    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = []

    agile_mock = MagicMock()
    agile_mock.query.return_value.get_points.return_value = []

    forecast_points = [_make_forecast_point("2026-04-01", 11, 0, pv_estimate_kwh=1.25)]
    solcast_mock = MagicMock()
    solcast_mock.query.return_value.get_points.return_value = forecast_points
    forecast_solar_points = [_make_forecast_point("2026-04-01", 11, 0, pv_estimate_kwh=0.75)]
    forecast_solar_mock = MagicMock()
    forecast_solar_mock.query.return_value.get_points.return_value = forecast_solar_points

    with patch(
        "solariq.data.influx.InfluxDBClient",
        side_effect=[solax_mock, agile_mock, solcast_mock, forecast_solar_mock],
    ):
        rows = get_historical_range_data(
            config,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 1),
        )

    total_pred = sum(r["predicted_solar_kwh"] for r in rows)
    assert total_pred == pytest.approx(1.25, abs=0.001)
    total_solcast = sum(r["predicted_solar_solcast_kwh"] for r in rows)
    total_forecast_solar = sum(r["predicted_solar_forecast_solar_kwh"] for r in rows)
    assert total_solcast == pytest.approx(1.25, abs=0.001)
    assert total_forecast_solar == pytest.approx(0.75, abs=0.001)
