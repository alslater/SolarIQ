import json
from pathlib import Path
import pytest
from solariq.cache import get_cache_paths, save_strategy, load_strategy
from solariq.optimizer.types import OptimizationResult, StrategyPeriod


def _sample_result() -> OptimizationResult:
    return OptimizationResult(
        periods=[StrategyPeriod(1, "00:00", "23:59", "Self Use", min_soc_pct=10)],
        estimated_cost_gbp=2.50,
        solar_forecast_kwh=15.0,
        grid_import_kwh=8.0,
        computed_at="2026-05-02T16:15:00+00:00",
        valid_until="2026-05-04T18:00:00+01:00",
        window_start="2026-05-03T18:00:00+01:00",
        agile_prices=[15.0] * 48,
        export_prices=[5.0] * 48,
        solar_forecast=[0.0] * 48,
        load_forecast=[0.3] * 48,
        battery_soc_forecast=[10.0] * 48,
        grid_import_forecast=[0.3] * 48,
        charge_mode_slots=[False] * 48,
    )


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "strategy.json")
    result = _sample_result()
    save_strategy(result, path)
    loaded = load_strategy(path)
    assert loaded is not None
    assert loaded.valid_until == "2026-05-04T18:00:00+01:00"
    assert loaded.window_start == "2026-05-03T18:00:00+01:00"
    assert loaded.estimated_cost_gbp == pytest.approx(2.50)
    assert len(loaded.periods) == 1
    assert loaded.periods[0].mode == "Self Use"


def test_load_returns_none_when_file_missing(tmp_path):
    result = load_strategy(str(tmp_path / "nonexistent.json"))
    assert result is None


def test_save_creates_valid_json(tmp_path):
    path = str(tmp_path / "strategy.json")
    save_strategy(_sample_result(), path)
    with open(path) as f:
        data = json.load(f)
    assert "valid_until" in data
    assert "window_start" in data
    assert "periods" in data


def test_get_cache_paths_uses_configured_base_dir():
    paths = get_cache_paths("/tmp/solariq-cache")
    assert paths == (
        "/tmp/solariq-cache/today.json",
        "/tmp/solariq-cache/strategy.json",
        "/tmp/solariq-cache/calibration.json",
        "/tmp/solariq-cache/today_rates.json",
    )


from solariq.cache import save_calibration, load_calibration


def test_save_and_load_calibration_roundtrip(tmp_path):
    path = str(tmp_path / "calibration.json")
    data = {
        "factor": 1.092,
        "computed_at": "2026-05-02T03:00:00+00:00",
        "octopus_kwh": 245.3,
        "influx_kwh": 224.5,
        "window_days": 30,
    }
    save_calibration(data, path)
    loaded = load_calibration(path)
    assert loaded is not None
    assert loaded["factor"] == pytest.approx(1.092)
    assert loaded["octopus_kwh"] == pytest.approx(245.3)
    assert loaded["window_days"] == 30


def test_load_calibration_returns_none_when_missing(tmp_path):
    result = load_calibration(str(tmp_path / "nonexistent.json"))
    assert result is None


def test_save_calibration_is_atomic(tmp_path):
    """Verify atomic write: .tmp file is cleaned up, final file exists."""
    path = str(tmp_path / "calibration.json")
    save_calibration({"factor": 1.0, "computed_at": "", "octopus_kwh": 0.0, "influx_kwh": 0.0, "window_days": 30}, path)
    assert Path(path).exists()
    assert not Path(path).with_suffix(".tmp").exists()
