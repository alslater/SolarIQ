from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

import pytest

from solariq.config import load_config
from solariq.data.solcast import fetch_solar_forecast, fetch_solar_forecast_with_coverage


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def _slot_period_end_utc(target_date: date, slot: int) -> str:
    """Return UTC period_end string for a given local-time slot index."""
    tz = ZoneInfo("Europe/London")
    local_h = (slot * 30) // 60
    local_m = (slot * 30) % 60
    # period_end is end of slot, so add 30 minutes to slot start
    local_start = datetime(target_date.year, target_date.month, target_date.day,
                           local_h, local_m, tzinfo=tz)
    local_end = local_start + timedelta(minutes=30)
    utc_end = local_end.astimezone(timezone.utc)
    return utc_end.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")


def _mock_solcast_response(target_date: date, pv_kw: float = 1.0):
    forecasts = []
    for slot in range(48):
        local_h = (slot * 30) // 60
        pv = pv_kw if 6 <= local_h < 20 else 0.0
        forecasts.append({
            "pv_estimate": pv,
            "period_end": _slot_period_end_utc(target_date, slot),
            "period": "PT30M",
        })
    return {"forecasts": forecasts}


def test_fetch_solar_forecast_returns_48_slots(config):
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = _mock_solcast_response(date(2026, 5, 3), 2.0)
        mock_get.return_value.raise_for_status = MagicMock()
        forecast = fetch_solar_forecast(config, target_date=date(2026, 5, 3))
    assert len(forecast) == 48


def test_fetch_solar_forecast_converts_kw_to_kwh(config):
    """pv_estimate is kW average; multiply by 0.5 for 30-min kWh."""
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = _mock_solcast_response(date(2026, 5, 3), 2.0)
        mock_get.return_value.raise_for_status = MagicMock()
        forecast = fetch_solar_forecast(config, target_date=date(2026, 5, 3))
    # slot 12 = 06:00 local BST: 2.0 kW * 0.5h = 1.0 kWh
    assert forecast[12] == pytest.approx(1.0)


def test_fetch_solar_forecast_zero_at_night(config):
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = _mock_solcast_response(date(2026, 5, 3), 2.0)
        mock_get.return_value.raise_for_status = MagicMock()
        forecast = fetch_solar_forecast(config, target_date=date(2026, 5, 3))
    # slot 0 = 00:00 local: should be 0
    assert forecast[0] == pytest.approx(0.0)


def test_fetch_solar_forecast_uses_bearer_auth(config):
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = _mock_solcast_response(date(2026, 5, 3))
        mock_get.return_value.raise_for_status = MagicMock()
        fetch_solar_forecast(config, target_date=date(2026, 5, 3))
    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["Authorization"] == f"Bearer {config.solcast.api_key}"


def test_fetch_solar_forecast_with_coverage_marks_missing_slots(config):
    target_date = date(2026, 5, 3)
    payload = _mock_solcast_response(target_date, 2.0)
    payload["forecasts"] = payload["forecasts"][12:]

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status = MagicMock()
        forecast, covered_slots = fetch_solar_forecast_with_coverage(config, target_date=target_date)

    assert len(forecast) == 48
    assert 0 not in covered_slots
    assert 11 not in covered_slots
    assert 12 in covered_slots
    assert forecast[12] == pytest.approx(1.0)
