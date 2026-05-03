from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from solariq.config import load_config
from solariq.data.influx import load_solar_forecast_influx, save_solar_forecast_influx


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def test_save_solar_forecast_influx_writes_48_points(config):
    """save_solar_forecast_influx writes exactly 48 points with correct structure."""
    slots = [float(i) * 0.1 for i in range(48)]
    mock_client = MagicMock()

    with patch("solariq.data.influx.InfluxDBClient", return_value=mock_client):
        save_solar_forecast_influx(config, slots, date(2026, 4, 1))

    mock_client.write_points.assert_called_once()
    points = mock_client.write_points.call_args[0][0]
    assert len(points) == 48
    assert all(p["measurement"] == "solar_forecast" for p in points)
    assert all(p["tags"] == {"source": "solcast"} for p in points)
    assert all("pv_estimate_kwh" in p["fields"] for p in points)
    assert points[0]["fields"]["pv_estimate_kwh"] == pytest.approx(0.0)
    assert points[1]["fields"]["pv_estimate_kwh"] == pytest.approx(0.1)


def test_load_solar_forecast_influx_returns_slots(config):
    """load_solar_forecast_influx returns 48-slot list when data present."""
    from datetime import datetime, timezone, timedelta
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/London")
    base = datetime(2026, 4, 1, 0, 0, tzinfo=tz)
    points = []
    for i in range(48):
        t_local = base + timedelta(minutes=i * 30)
        t_utc = t_local.astimezone(timezone.utc)
        points.append({
            "time": t_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pv_estimate_kwh": float(i) * 0.1,
        })

    mock_client = MagicMock()
    mock_client.query.return_value.get_points.return_value = points

    with patch("solariq.data.influx.InfluxDBClient", return_value=mock_client):
        result = load_solar_forecast_influx(config, date(2026, 4, 1))

    assert result is not None
    assert len(result) == 48
    assert result[0] == pytest.approx(0.0)
    assert result[1] == pytest.approx(0.1)


def test_load_solar_forecast_influx_returns_none_when_empty(config):
    """load_solar_forecast_influx returns None when query returns no points."""
    mock_client = MagicMock()
    mock_client.query.return_value.get_points.return_value = []

    with patch("solariq.data.influx.InfluxDBClient", return_value=mock_client):
        result = load_solar_forecast_influx(config, date(2026, 4, 1))

    assert result is None


def test_load_solar_forecast_influx_returns_none_when_partial(config):
    """load_solar_forecast_influx returns None when fewer than 48 points returned."""
    from datetime import datetime, timezone, timedelta
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/London")
    base = datetime(2026, 4, 1, 0, 0, tzinfo=tz)
    points = []
    for i in range(10):
        t_local = base + timedelta(minutes=i * 30)
        t_utc = t_local.astimezone(timezone.utc)
        points.append({
            "time": t_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "pv_estimate_kwh": float(i) * 0.1,
        })

    mock_client = MagicMock()
    mock_client.query.return_value.get_points.return_value = points

    with patch("solariq.data.influx.InfluxDBClient", return_value=mock_client):
        result = load_solar_forecast_influx(config, date(2026, 4, 1))

    assert result is None
