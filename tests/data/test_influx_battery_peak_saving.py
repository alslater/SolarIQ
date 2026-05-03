from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from solariq.config import load_config
from solariq.data.influx import get_historical_range_data


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def _make_solax_point(date_str, hour, minute, pvpower=0.0, power_in=0.0, power_out=0.0, battery_power=0.0):
    return {
        "time": f"{date_str}T{hour:02d}:{minute:02d}:00Z",
        "pvpower": pvpower,
        "power_in": power_in,
        "power_out": power_out,
        "battery_power": battery_power,
    }


def _make_rate_point(date_str, hour, minute, agile_rate=0.0, export_rate=0.0):
    return {
        "time": f"{date_str}T{hour:02d}:{minute:02d}:00Z",
        "agile_rate": agile_rate,
        "export_rate": export_rate,
    }


def test_battery_peak_saving_in_peak_slot(config):
    """battery_peak_saving_gbp = battery_to_load × import_rate / 100 during 16:00–19:00."""
    # UTC 15:00 = BST 16:00 → peak window, slot 32 (hour 16)
    # battery_power = -2.0 kW (discharging), power_out = 0.0 → battery_to_load = 1.0 kWh
    # agile_rate = 20p → saving = 1.0 × 20 / 100 = £0.20
    solax_points = [_make_solax_point("2026-04-01", 15, 0, battery_power=-2.0)]
    rate_points = [_make_rate_point("2026-04-01", 15, 0, agile_rate=20.0)]

    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = solax_points

    agile_mock = MagicMock()
    agile_mock.query.return_value.get_points.return_value = rate_points

    with patch("solariq.data.influx.InfluxDBClient", side_effect=[solax_mock, agile_mock]):
        rows = get_historical_range_data(
            config,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 1),
        )

    assert "battery_peak_saving_gbp" in rows[0]
    total_saving = sum(r["battery_peak_saving_gbp"] for r in rows)
    assert total_saving == pytest.approx(0.20, abs=0.001)


def test_battery_peak_saving_zero_outside_peak(config):
    """battery_peak_saving_gbp is 0 for slots outside 16:00–19:00."""
    # UTC 09:00 = BST 10:00 → not in peak window
    solax_points = [_make_solax_point("2026-04-01", 9, 0, battery_power=-2.0)]
    rate_points = [_make_rate_point("2026-04-01", 9, 0, agile_rate=20.0)]

    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = solax_points

    agile_mock = MagicMock()
    agile_mock.query.return_value.get_points.return_value = rate_points

    with patch("solariq.data.influx.InfluxDBClient", side_effect=[solax_mock, agile_mock]):
        rows = get_historical_range_data(
            config,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 1),
        )

    total_saving = sum(r["battery_peak_saving_gbp"] for r in rows)
    assert total_saving == pytest.approx(0.0, abs=0.001)


def test_battery_peak_saving_excludes_export_portion(config):
    """battery_to_load excludes the portion exported to grid."""
    # UTC 15:00 = BST 16:00 → peak window
    # battery_power = -2.0 kW → discharge 1.0 kWh
    # power_out = 1.0 kW → export 0.5 kWh
    # battery_to_load = max(0, 1.0 - 0.5) = 0.5 kWh
    # saving = 0.5 × 20p / 100 = £0.10
    solax_points = [_make_solax_point("2026-04-01", 15, 0, battery_power=-2.0, power_out=1.0)]
    rate_points = [_make_rate_point("2026-04-01", 15, 0, agile_rate=20.0)]

    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = solax_points

    agile_mock = MagicMock()
    agile_mock.query.return_value.get_points.return_value = rate_points

    with patch("solariq.data.influx.InfluxDBClient", side_effect=[solax_mock, agile_mock]):
        rows = get_historical_range_data(
            config,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 1),
        )

    total_saving = sum(r["battery_peak_saving_gbp"] for r in rows)
    assert total_saving == pytest.approx(0.10, abs=0.001)


def test_battery_peak_saving_present_in_all_rows(config):
    """Every row contains battery_peak_saving_gbp, including empty buckets."""
    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = []

    agile_mock = MagicMock()
    agile_mock.query.return_value.get_points.return_value = []

    with patch("solariq.data.influx.InfluxDBClient", side_effect=[solax_mock, agile_mock]):
        rows = get_historical_range_data(
            config,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 3),
        )

    assert all("battery_peak_saving_gbp" in r for r in rows)
