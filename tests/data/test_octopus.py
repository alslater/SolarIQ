from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from unittest.mock import patch, MagicMock

import pytest

from solariq.config import load_config
from solariq.data.octopus import fetch_agile_prices, fetch_export_prices, fetch_octopus_export_consumption_kwh


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def _slot_utc(target_date: date, slot: int) -> str:
    """Return UTC valid_from string for a given local-time slot index."""
    tz = ZoneInfo("Europe/London")
    local_h = (slot * 30) // 60
    local_m = (slot * 30) % 60
    local_dt = datetime(target_date.year, target_date.month, target_date.day,
                        local_h, local_m, tzinfo=tz)
    return local_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mock_agile_response(target_date: date, base_price: float = 15.0):
    results = [
        {"valid_from": _slot_utc(target_date, slot), "value_inc_vat": base_price}
        for slot in range(48)
    ]
    return {"results": results, "next": None}


def test_fetch_agile_prices_returns_48_slots(config):
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = _mock_agile_response(date(2026, 5, 3), 12.5)
        mock_get.return_value.raise_for_status = MagicMock()
        prices = fetch_agile_prices(config, target_date=date(2026, 5, 3))
    assert len(prices) == 48


def test_fetch_agile_prices_ordered_by_time(config):
    target = date(2026, 5, 3)
    results = [
        {"valid_from": _slot_utc(target, 1), "value_inc_vat": 20.0},  # slot 1 = 00:30 BST
        {"valid_from": _slot_utc(target, 0), "value_inc_vat": 10.0},  # slot 0 = 00:00 BST
    ]
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = {"results": results, "next": None}
        mock_get.return_value.raise_for_status = MagicMock()
        prices = fetch_agile_prices(config, target_date=target)
    assert prices[0] == pytest.approx(10.0)
    assert prices[1] == pytest.approx(20.0)


def test_fetch_export_prices_returns_48_slots(config):
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = _mock_agile_response(date(2026, 5, 3), 5.0)
        mock_get.return_value.raise_for_status = MagicMock()
        prices = fetch_export_prices(config, target_date=date(2026, 5, 3))
    assert len(prices) == 48


def test_fetch_agile_prices_returns_partial_when_not_yet_published(config):
    """Returns 48 slots even when prices aren't published yet (100.0 cap for missing)."""
    target = date(2026, 5, 3)
    results = [
        {"valid_from": _slot_utc(target, 0), "value_inc_vat": 10.0},
    ]
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = {"results": results, "next": None}
        mock_get.return_value.raise_for_status = MagicMock()
        prices = fetch_agile_prices(config, target_date=target)
    assert len(prices) == 48
    assert prices[0] == pytest.approx(10.0)
    assert prices[1] == pytest.approx(100.0)  # capped — not published yet


def test_fetch_octopus_export_consumption_kwh(config):
    mock_results = [
        {"consumption": 0.5, "interval_start": "2026-04-01T00:00:00Z", "interval_end": "2026-04-01T00:30:00Z"},
        {"consumption": 0.3, "interval_start": "2026-04-01T00:30:00Z", "interval_end": "2026-04-01T01:00:00Z"},
        {"consumption": 0.0, "interval_start": "2026-04-01T01:00:00Z", "interval_end": "2026-04-01T01:30:00Z"},
    ]
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = {"results": mock_results}
        mock_get.return_value.raise_for_status = MagicMock()
        total = fetch_octopus_export_consumption_kwh(
            config,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
        )
    assert total == pytest.approx(0.8)
    # Verify page_size=1500 was requested
    call_params = mock_get.call_args[1]["params"]
    assert call_params["page_size"] == 1500


def test_fetch_octopus_export_consumption_kwh_empty_response(config):
    with patch("requests.get") as mock_get:
        mock_get.return_value.json.return_value = {"results": []}
        mock_get.return_value.raise_for_status = MagicMock()
        total = fetch_octopus_export_consumption_kwh(
            config,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 30),
        )
    assert total == pytest.approx(0.0)
