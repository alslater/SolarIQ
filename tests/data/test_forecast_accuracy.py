import math
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from solariq.data.forecast_accuracy import (
    _mae,
    _rmse,
    compute_daily_accuracy,
    compute_range_accuracy,
)


def test_mae_perfect_forecast():
    actual = [1.0, 2.0, 3.0]
    forecast = [1.0, 2.0, 3.0]
    assert _mae(actual, forecast) == pytest.approx(0.0)

def test_mae_constant_error():
    actual = [1.0, 2.0, 3.0]
    forecast = [2.0, 3.0, 4.0]
    assert _mae(actual, forecast) == pytest.approx(1.0)

def test_mae_mixed_errors():
    actual =   [0.0, 1.0, 2.0]
    forecast = [1.0, 1.0, 1.0]
    assert _mae(actual, forecast) == pytest.approx(2.0 / 3.0, rel=1e-6)

def test_rmse_perfect_forecast():
    actual = [1.0, 2.0, 3.0]
    forecast = [1.0, 2.0, 3.0]
    assert _rmse(actual, forecast) == pytest.approx(0.0)

def test_rmse_constant_error():
    actual = [0.0, 0.0, 0.0]
    forecast = [2.0, 2.0, 2.0]
    assert _rmse(actual, forecast) == pytest.approx(2.0)

def test_rmse_penalises_large_errors():
    actual =   [0.0, 0.0, 0.0, 0.0]
    forecast = [4.0, 0.0, 0.0, 0.0]
    assert _mae(actual, forecast) == pytest.approx(1.0)
    assert _rmse(actual, forecast) == pytest.approx(2.0)
    assert _rmse(actual, forecast) > _mae(actual, forecast)


def _make_config():
    return MagicMock()

def test_compute_daily_accuracy_returns_none_when_actual_all_zeros():
    config = _make_config()
    target = date(2026, 5, 1)
    actual = [0.0] * 48
    solcast = [0.1] * 48
    fs = [0.1] * 48
    with patch("solariq.data.forecast_accuracy.query_solax_usage_day", return_value=actual), \
         patch("solariq.data.forecast_accuracy.load_solar_forecast_influx", side_effect=[solcast, fs]):
        result = compute_daily_accuracy(config, target)
    assert result is None

def test_compute_daily_accuracy_returns_none_when_solcast_missing():
    config = _make_config()
    target = date(2026, 5, 1)
    actual = [0.0] * 44 + [0.5, 0.5, 0.5, 0.5]
    with patch("solariq.data.forecast_accuracy.query_solax_usage_day", return_value=actual), \
         patch("solariq.data.forecast_accuracy.load_solar_forecast_influx", side_effect=[None, [0.1] * 48]):
        result = compute_daily_accuracy(config, target)
    assert result is None

def test_compute_daily_accuracy_returns_none_when_forecast_solar_missing():
    config = _make_config()
    target = date(2026, 5, 1)
    actual = [0.0] * 44 + [0.5, 0.5, 0.5, 0.5]
    with patch("solariq.data.forecast_accuracy.query_solax_usage_day", return_value=actual), \
         patch("solariq.data.forecast_accuracy.load_solar_forecast_influx", side_effect=[[0.1] * 48, None]):
        result = compute_daily_accuracy(config, target)
    assert result is None

def test_compute_daily_accuracy_computes_metrics():
    config = _make_config()
    target = date(2026, 5, 1)
    actual = [0.0] * 40 + [1.0] * 8
    solcast = [0.0] * 40 + [1.5] * 8
    fs = [0.0] * 40 + [0.5] * 8
    with patch("solariq.data.forecast_accuracy.query_solax_usage_day", return_value=actual), \
         patch("solariq.data.forecast_accuracy.load_solar_forecast_influx", side_effect=[solcast, fs]):
        result = compute_daily_accuracy(config, target)
    assert result is not None
    assert result.date == target
    assert result.actual_slots == actual
    assert result.solcast_slots == solcast
    assert result.forecast_solar_slots == fs
    expected_mae = (8 * 0.5) / 48
    assert result.solcast_mae == pytest.approx(expected_mae, rel=1e-6)
    assert result.forecast_solar_mae == pytest.approx(expected_mae, rel=1e-6)
    expected_rmse = math.sqrt((8 * 0.25) / 48)
    assert result.solcast_rmse == pytest.approx(expected_rmse, rel=1e-6)
    assert result.forecast_solar_rmse == pytest.approx(expected_rmse, rel=1e-6)


def test_compute_range_accuracy_skips_missing_days():
    config = _make_config()
    start = date(2026, 5, 1)
    end = date(2026, 5, 3)

    actual_good = [0.0] * 40 + [1.0] * 8
    solcast_good = [0.0] * 40 + [1.2] * 8
    fs_good = [0.0] * 40 + [0.9] * 8

    def fake_query_solax(cfg, d):
        if d == date(2026, 5, 2):
            return [0.0] * 48
        return actual_good

    def fake_load_forecast(cfg, d, source="solcast"):
        if source == "solcast":
            return solcast_good
        return fs_good

    with patch("solariq.data.forecast_accuracy.query_solax_usage_day", side_effect=fake_query_solax), \
         patch("solariq.data.forecast_accuracy.load_solar_forecast_influx", side_effect=fake_load_forecast):
        results = compute_range_accuracy(config, start, end)

    assert len(results) == 2
    assert results[0].date == date(2026, 5, 1)
    assert results[1].date == date(2026, 5, 3)

def test_compute_range_accuracy_returns_empty_list_when_no_valid_days():
    config = _make_config()
    start = date(2026, 5, 1)
    end = date(2026, 5, 1)

    with patch("solariq.data.forecast_accuracy.query_solax_usage_day", return_value=[0.0] * 48), \
         patch("solariq.data.forecast_accuracy.load_solar_forecast_influx", return_value=[0.1] * 48):
        results = compute_range_accuracy(config, start, end)

    assert results == []
