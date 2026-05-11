from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from solariq.config import load_config
from solariq.data.influx import get_historical_range_data


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def _make_solax_point(date_str, hour, minute, pvpower=0.0, power_in=0.0, power_out=0.0, soc=None):
    point = {
        "time": f"{date_str}T{hour:02d}:{minute:02d}:00Z",
        "pvpower": pvpower,
        "power_in": power_in,
        "power_out": power_out,
    }
    if soc is not None:
        point["soc"] = soc
    return point


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


def test_avg_rate_correct_for_two_slots(config):
    """avg_import_rate_p and avg_export_rate_p reflect the rate for each individual 30m slot."""
    # UTC 11:00 and 11:30 on 2026-04-01 = BST 12:00 and 12:30 → two separate slot buckets
    solax_points = [
        _make_solax_point("2026-04-01", 11, 0, power_in=1.0),
        _make_solax_point("2026-04-01", 11, 30, power_in=1.0),
    ]
    rate_points = [
        _make_rate_point("2026-04-01", 11, 0, agile_rate=10.0, export_rate=4.0),
        _make_rate_point("2026-04-01", 11, 30, agile_rate=30.0, export_rate=8.0),
    ]

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
        rows = get_historical_range_data(config, start_date=date(2026, 4, 1), end_date=date(2026, 4, 1))

    rated_rows = [r for r in rows if r.get("avg_import_rate_p") is not None]
    assert len(rated_rows) == 2
    rates = sorted(r["avg_import_rate_p"] for r in rated_rows)
    assert rates == pytest.approx([10.0, 30.0], abs=0.001)
    export_rates = sorted(r["avg_export_rate_p"] for r in rated_rows)
    assert export_rates == pytest.approx([4.0, 8.0], abs=0.001)


def test_avg_rate_none_when_no_rate_data(config):
    """avg_import_rate_p and avg_export_rate_p are None when the rate query returns nothing."""
    solax_points = [_make_solax_point("2026-04-01", 11, 0, power_in=1.0)]

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
        rows = get_historical_range_data(config, start_date=date(2026, 4, 1), end_date=date(2026, 4, 1))

    assert all(r["avg_import_rate_p"] is None for r in rows)
    assert all(r["avg_export_rate_p"] is None for r in rows)


def test_avg_rate_includes_zero_and_negative_rates(config):
    """Zero and negative Agile rates must appear in per-slot buckets, not be treated as missing."""
    # Slots: -5p and 5p → two separate 30m buckets, each with their own rate
    solax_points = [
        _make_solax_point("2026-04-01", 11, 0, power_in=1.0),
        _make_solax_point("2026-04-01", 11, 30, power_in=1.0),
    ]
    rate_points = [
        _make_rate_point("2026-04-01", 11, 0, agile_rate=-5.0, export_rate=0.0),
        _make_rate_point("2026-04-01", 11, 30, agile_rate=5.0, export_rate=0.0),
    ]

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
        rows = get_historical_range_data(config, start_date=date(2026, 4, 1), end_date=date(2026, 4, 1))

    rated_rows = [r for r in rows if r.get("avg_import_rate_p") is not None]
    assert len(rated_rows) == 2
    rates = sorted(r["avg_import_rate_p"] for r in rated_rows)
    assert rates == pytest.approx([-5.0, 5.0], abs=0.001)
    # export_rate is 0.0 for both slots — must be retained, not treated as missing
    export_rated_rows = [r for r in rows if r.get("avg_export_rate_p") is not None]
    assert len(export_rated_rows) == 2
    export_rates = sorted(r["avg_export_rate_p"] for r in export_rated_rows)
    assert export_rates == pytest.approx([0.0, 0.0], abs=0.001)


def test_avg_rate_present_in_all_rows(config):
    """Every row contains avg_import_rate_p and avg_export_rate_p keys (value may be None)."""
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
        rows = get_historical_range_data(config, start_date=date(2026, 4, 1), end_date=date(2026, 4, 3))

    assert all("avg_import_rate_p" in r for r in rows)
    assert all("avg_export_rate_p" in r for r in rows)


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


def _empty_agile_mock():
    m = MagicMock()
    m.query.return_value.get_points.return_value = []
    return m


def _empty_forecast_mocks():
    s = MagicMock()
    s.query.return_value.get_points.return_value = []
    f = MagicMock()
    f.query.return_value.get_points.return_value = []
    return s, f


def test_soc_pct_present_in_all_rows(config):
    """Every row must have a soc_pct key (value may be None)."""
    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = []
    s, f = _empty_forecast_mocks()

    with patch(
        "solariq.data.influx.InfluxDBClient",
        side_effect=[solax_mock, _empty_agile_mock(), s, f],
    ):
        rows = get_historical_range_data(config, start_date=date(2026, 4, 1), end_date=date(2026, 4, 3))

    assert all("soc_pct" in r for r in rows)


def test_soc_pct_none_when_no_soc_in_data(config):
    """soc_pct is None for every row when the influx query returns no soc field."""
    solax_points = [_make_solax_point("2026-04-01", 11, 0, pvpower=1.0)]  # no soc= kwarg
    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = solax_points
    s, f = _empty_forecast_mocks()

    with patch(
        "solariq.data.influx.InfluxDBClient",
        side_effect=[solax_mock, _empty_agile_mock(), s, f],
    ):
        rows = get_historical_range_data(config, start_date=date(2026, 4, 1), end_date=date(2026, 4, 1))

    assert all(r["soc_pct"] is None for r in rows)


def test_soc_pct_reflects_last_soc_value(config):
    """soc_pct in the matching slot row equals the soc value from the influx point."""
    # UTC 11:00 = BST 12:00 → slot 24 (index for 12:00 local)
    solax_points = [_make_solax_point("2026-04-01", 11, 0, pvpower=0.0, soc=73.5)]
    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = solax_points
    s, f = _empty_forecast_mocks()

    with patch(
        "solariq.data.influx.InfluxDBClient",
        side_effect=[solax_mock, _empty_agile_mock(), s, f],
    ):
        rows = get_historical_range_data(config, start_date=date(2026, 4, 1), end_date=date(2026, 4, 1))

    # Exactly one row should have soc_pct set; the rest are None
    soc_rows = [r for r in rows if r["soc_pct"] is not None]
    assert len(soc_rows) == 1
    assert soc_rows[0]["soc_pct"] == pytest.approx(73.5, abs=0.05)


def test_soc_pct_rounded_to_one_decimal(config):
    """soc_pct is rounded to 1 decimal place."""
    solax_points = [_make_solax_point("2026-04-01", 11, 0, soc=66.666)]
    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = solax_points
    s, f = _empty_forecast_mocks()

    with patch(
        "solariq.data.influx.InfluxDBClient",
        side_effect=[solax_mock, _empty_agile_mock(), s, f],
    ):
        rows = get_historical_range_data(config, start_date=date(2026, 4, 1), end_date=date(2026, 4, 1))

    soc_rows = [r for r in rows if r["soc_pct"] is not None]
    assert len(soc_rows) == 1
    assert soc_rows[0]["soc_pct"] == round(66.666, 1)


def test_soc_pct_multi_day_only_present_in_matching_slot(config):
    """Over a multi-day query, soc_pct is None for all slots except the one with data."""
    # One point on day 1 at UTC 11:00; days 2 and 3 have no solax data
    solax_points = [_make_solax_point("2026-04-01", 11, 0, soc=50.0)]
    solax_mock = MagicMock()
    solax_mock.query.return_value.get_points.return_value = solax_points
    s, f = _empty_forecast_mocks()

    with patch(
        "solariq.data.influx.InfluxDBClient",
        side_effect=[solax_mock, _empty_agile_mock(), s, f],
    ):
        rows = get_historical_range_data(config, start_date=date(2026, 4, 1), end_date=date(2026, 4, 3))

    soc_rows = [r for r in rows if r["soc_pct"] is not None]
    # Only the BST-12:00 slot on day 1 should have soc_pct set
    assert len(soc_rows) == 1
    assert soc_rows[0]["soc_pct"] == pytest.approx(50.0, abs=0.05)
