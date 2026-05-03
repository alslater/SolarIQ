from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from solariq.config import load_config
from solariq.calibration import compute_export_factor


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def _mock_influx_rows(export_kwh_per_day: float, days: int = 30) -> list[dict]:
    """Return fake get_historical_range_data rows."""
    return [
        {
            "date": f"2026-{(i // 30) + 4:02d}-{(i % 28) + 1:02d}",
            "solar_kwh": 10.0,
            "grid_import_kwh": 5.0,
            "grid_export_kwh": export_kwh_per_day,
            "grid_cost_gbp": 1.0,
            "grid_export_revenue_gbp": 0.5,
        }
        for i in range(days)
    ]


def test_compute_export_factor_typical(config):
    """Factor = octopus_total / influx_total."""
    influx_rows = _mock_influx_rows(export_kwh_per_day=8.0, days=30)  # 240 kWh total
    octopus_total = 261.6  # ~9% more

    with patch("solariq.calibration.fetch_octopus_export_consumption_kwh", return_value=octopus_total), \
         patch("solariq.calibration.get_historical_range_data", return_value=influx_rows):
        result = compute_export_factor(config)

    assert result["factor"] == pytest.approx(261.6 / 240.0, rel=1e-3)
    assert result["octopus_kwh"] == pytest.approx(261.6)
    assert result["influx_kwh"] == pytest.approx(240.0)
    assert result["window_days"] == 30
    assert "computed_at" in result


def test_compute_export_factor_returns_one_when_influx_zero(config):
    """Avoid division by zero — return factor 1.0 and do not save."""
    influx_rows = _mock_influx_rows(export_kwh_per_day=0.0, days=30)

    with patch("solariq.calibration.fetch_octopus_export_consumption_kwh", return_value=50.0), \
         patch("solariq.calibration.get_historical_range_data", return_value=influx_rows):
        result = compute_export_factor(config)

    assert result["factor"] == pytest.approx(1.0)


def test_compute_export_factor_zero_octopus(config):
    """Return factor 1.0 when Octopus API returns zero (empty results, API issue, etc)."""
    influx_rows = _mock_influx_rows(export_kwh_per_day=8.0, days=30)  # 240 kWh total

    with patch("solariq.calibration.fetch_octopus_export_consumption_kwh", return_value=0.0), \
         patch("solariq.calibration.get_historical_range_data", return_value=influx_rows):
        result = compute_export_factor(config)

    assert result["factor"] == pytest.approx(1.0)


def test_compute_export_factor_skips_when_mpan_missing(test_ini_path):
    """Returns factor 1.0 without hitting any API if export_mpan is not configured."""
    from configparser import ConfigParser
    from pathlib import Path
    from solariq.config import load_config

    # Write a temp ini without export_mpan
    ini = ConfigParser()
    ini.read(test_ini_path)
    ini.remove_option("octopus", "export_mpan")
    ini.remove_option("octopus", "export_serial_number")

    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
        ini.write(f)
        tmp_path = f.name
    try:
        cfg = load_config(tmp_path)
        result = compute_export_factor(cfg)
        assert result["factor"] == pytest.approx(1.0)
    finally:
        os.unlink(tmp_path)
