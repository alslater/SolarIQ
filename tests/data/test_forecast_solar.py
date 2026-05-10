"""Tests for solariq/data/forecast_solar.py — slot mapping and period handling."""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import requests

from solariq.config import load_config
from solariq.data.forecast_solar import fetch_forecast_solar, fetch_forecast_solar_with_coverage


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def _make_response(series: dict) -> dict:
    return {"result": {"watt_hours_period": series}}


# ── end-of-period mapping ─────────────────────────────────────────────────────

def test_hourly_timestamps_mapped_to_correct_slots(config):
    """Hourly end-of-period timestamps split energy across the two preceding 30-min slots."""
    # "09:00" = end of 08:00-09:00 period → slots 16 and 17 each get 0.5 kWh
    series = {"2026-05-05 09:00:00": 1000.0}  # 1000 Wh = 1 kWh
    payload = _make_response(series)

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status = MagicMock()
        slots, covered = fetch_forecast_solar_with_coverage(config, date(2026, 5, 5))

    assert slots[16] == pytest.approx(0.5)   # 08:00 slot
    assert slots[17] == pytest.approx(0.5)   # 08:30 slot
    assert 16 in covered and 17 in covered
    # nothing bleeds into the next hour
    assert slots[18] == pytest.approx(0.0)


def test_half_hourly_timestamps_mapped_to_correct_slot(config):
    """Half-hourly end-of-period timestamps map the energy to the single preceding slot."""
    # "08:30" = end of 08:00-08:30 period → slot 16 gets 0.5 kWh
    # "09:00" = end of 08:30-09:00 period → slot 17 gets 0.5 kWh (30-min detected via :30 key)
    series = {
        "2026-05-05 08:30:00": 500.0,  # 500 Wh → slot 16
        "2026-05-05 09:00:00": 600.0,  # 600 Wh → slot 17
    }
    payload = _make_response(series)

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status = MagicMock()
        slots, covered = fetch_forecast_solar_with_coverage(config, date(2026, 5, 5))

    assert slots[16] == pytest.approx(0.5)   # 08:00 slot
    assert slots[17] == pytest.approx(0.6)   # 08:30 slot
    assert 16 in covered and 17 in covered


def test_no_sawtooth_in_hourly_data(config):
    """With hourly data, no slot should be zero while its neighbour is non-zero within daylight."""
    # Build a full hourly response for midday
    series = {f"2026-05-05 {h:02d}:00:00": 2000.0 for h in range(7, 20)}
    payload = _make_response(series)

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status = MagicMock()
        slots, _ = fetch_forecast_solar_with_coverage(config, date(2026, 5, 5))

    # Slots 12-37 (06:00-18:30) should all be equal (no zeros interspersed)
    daylight_slots = slots[14:38]  # 07:00-18:30
    assert all(v == pytest.approx(1.0) for v in daylight_slots), (
        f"Sawtooth detected in hourly data: {daylight_slots}"
    )


def test_returns_48_slots(config):
    series = {"2026-05-05 12:00:00": 1000.0}
    payload = _make_response(series)

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status = MagicMock()
        slots, _ = fetch_forecast_solar_with_coverage(config, date(2026, 5, 5))

    assert len(slots) == 48


def test_wh_converted_to_kwh(config):
    """Values from the API (Wh) are divided by 1000 to produce kWh."""
    series = {"2026-05-05 10:00:00": 3000.0}  # 3000 Wh = 3 kWh split over 2 slots
    payload = _make_response(series)

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status = MagicMock()
        slots, _ = fetch_forecast_solar_with_coverage(config, date(2026, 5, 5))

    assert sum(slots) == pytest.approx(3.0)


def test_other_date_entries_ignored(config):
    """Timestamps from dates other than the target are ignored."""
    series = {
        "2026-05-04 12:00:00": 9999.0,   # yesterday — must be ignored
        "2026-05-05 10:00:00": 1000.0,   # today
    }
    payload = _make_response(series)

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status = MagicMock()
        slots, _ = fetch_forecast_solar_with_coverage(config, date(2026, 5, 5))

    assert sum(slots) == pytest.approx(1.0)


def test_fetch_forecast_solar_returns_list(config):
    series = {"2026-05-05 10:00:00": 500.0}
    payload = _make_response(series)

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status = MagicMock()
        result = fetch_forecast_solar(config, date(2026, 5, 5))

    assert isinstance(result, list)
    assert len(result) == 48


def test_cumulative_watthours_series_is_differenced_not_summed(config):
    """watt_hours (cumulative daily) must be differenced to get per-period energy."""
    payload = {
        "result": {
            "watt_hours": {
                "2026-05-05 08:00:00": 1000.0,  # first point: energy_wh = 1000 (no prev)
                "2026-05-05 09:00:00": 3000.0,  # delta = 2000
                "2026-05-05 10:00:00": 5000.0,  # delta = 2000
            }
        }
    }

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status = MagicMock()
        slots, _ = fetch_forecast_solar_with_coverage(config, date(2026, 5, 5))

    # End-of-hour timestamps map to the preceding hour, split across two 30-min slots.
    assert slots[14] == pytest.approx(0.5)  # 07:00
    assert slots[15] == pytest.approx(0.5)  # 07:30
    assert slots[16] == pytest.approx(1.0)  # 08:00
    assert slots[17] == pytest.approx(1.0)  # 08:30
    assert slots[18] == pytest.approx(1.0)  # 09:00
    assert slots[19] == pytest.approx(1.0)  # 09:30
    assert sum(slots) == pytest.approx(5.0)


def test_flat_personal_endpoint_response_treated_as_cumulative(config):
    """Personal endpoint returns series directly in result (no watt_hours sub-key).
    Values are cumulative daily Wh and must be differenced.
    """
    # Mirrors the actual API shape: timestamps as direct keys of result.
    payload = {
        "result": {
            "2026-05-05T07:00:00+00:00": 500.0,   # first point
            "2026-05-05T07:30:00+00:00": 1000.0,  # delta = 500
            "2026-05-05T08:00:00+00:00": 1600.0,  # delta = 600
        }
    }

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status = MagicMock()
        slots, covered = fetch_forecast_solar_with_coverage(config, date(2026, 5, 5))

    # UTC times are converted to Europe/London (BST = UTC+1 in May).
    # 07:00 UTC → 08:00 BST end-of-period → start 07:30 BST → slot 15
    # 07:30 UTC → 08:30 BST end-of-period → start 08:00 BST → slot 16
    # 08:00 UTC → 09:00 BST end-of-period → start 08:30 BST → slot 17
    assert slots[15] == pytest.approx(0.5)   # 500 Wh first point
    assert slots[16] == pytest.approx(0.5)   # delta 500 Wh
    assert slots[17] == pytest.approx(0.6)   # delta 600 Wh
    assert sum(slots) == pytest.approx(1.6)


def test_uses_personal_endpoint_when_api_key_present(config):
    """With api_key configured, use /{apikey}/estimate/watthours/... and pass time=utc."""
    series = {"2026-05-05 10:00:00": 500.0}
    payload = _make_response(series)

    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = payload
        mock_get.return_value.raise_for_status = MagicMock()
        fetch_forecast_solar_with_coverage(config, date(2026, 5, 5))

    called_url = mock_get.call_args[0][0]
    called_params = mock_get.call_args[1].get("params")
    assert "/test_forecast_solar_key/estimate/watthours/" in called_url
    assert "/watthours/period/" not in called_url
    assert called_params.get("time") == "utc"


def test_personal_endpoint_http_error_is_raised(config):
    """If personal endpoint returns 404, the HTTP error is propagated."""
    not_found_response = MagicMock(status_code=404)
    first = MagicMock()
    first.raise_for_status.side_effect = requests.HTTPError(response=not_found_response)

    with patch("requests.get", side_effect=[first]) as mock_get:
        with pytest.raises(requests.HTTPError):
            fetch_forecast_solar_with_coverage(config, date(2026, 5, 5))

    assert mock_get.call_count == 1
    first_url = mock_get.call_args_list[0][0][0]
    assert "/test_forecast_solar_key/estimate/watthours/" in first_url


def test_uses_public_watthours_endpoint_without_api_key(config):
    """Without api_key, use /estimate/watthours/... and pass time=utc."""
    config.forecast_solar.api_key = ""
    series = {"2026-05-05 10:00:00": 500.0}
    payload = _make_response(series)

    with patch("requests.get") as mock_get:
        mock_get.return_value.raise_for_status.return_value = None
        mock_get.return_value.json.return_value = payload
        fetch_forecast_solar_with_coverage(config, date(2026, 5, 5))

    assert mock_get.call_count == 1
    called_url = mock_get.call_args[0][0]
    called_params = mock_get.call_args[1].get("params")
    assert "/estimate/watthours/" in called_url
    assert "/watthours/period/" not in called_url
    assert called_params.get("time") == "utc"
