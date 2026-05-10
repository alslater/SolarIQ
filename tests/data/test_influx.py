from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from solariq.config import load_config
from solariq.data.influx import get_today_live_data


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def _make_mock_point(hour, minute, pvpower=0.0, soc_pct=0.0, power_in=0.5, power_out=0.0):
    return {
        "time": f"2026-05-02T{hour:02d}:{minute:02d}:00Z",
        "pvpower": pvpower,
        "soc": soc_pct,
        "power_in": power_in,
        "power_out": power_out,
    }


def test_get_today_live_data_returns_correct_soc(config):
    # soc field is a percentage; battery at 15 kWh out of 23.2 kWh capacity
    soc_pct = 15.0 / 23.2 * 100
    mock_points = [_make_mock_point(h, m, soc_pct=soc_pct) for h in range(24) for m in (0, 30)]
    mock_client = MagicMock()
    mock_client.query.return_value.get_points.return_value = mock_points

    with patch("solariq.data.influx.InfluxDBClient", return_value=mock_client), \
         patch("solariq.data.influx.fetch_agile_prices", return_value=[15.0] * 48), \
         patch("solariq.data.octopus.fetch_export_prices", return_value=[5.0] * 48):
        result = get_today_live_data(config, today=date(2026, 5, 2))

    assert result.battery_soc_pct == pytest.approx(15.0 / 23.2 * 100, abs=0.1)
    assert result.battery_soc_kwh == pytest.approx(15.0, abs=0.1)


def test_get_today_live_data_sums_solar(config):
    # pvpower is kW mean; code converts to kWh via × 0.5h per slot
    mock_points = [_make_mock_point(h, m, pvpower=0.4) for h in range(24) for m in (0, 30)]
    mock_client = MagicMock()
    mock_client.query.return_value.get_points.return_value = mock_points

    with patch("solariq.data.influx.InfluxDBClient", return_value=mock_client), \
         patch("solariq.data.influx.fetch_agile_prices", return_value=[15.0] * 48), \
         patch("solariq.data.octopus.fetch_export_prices", return_value=[5.0] * 48):
        result = get_today_live_data(config, today=date(2026, 5, 2))

    # 2 UTC slots (23:00, 23:30) roll into May 3 in Europe/London (BST, UTC+1) and are filtered
    assert result.solar_today_kwh == pytest.approx(0.4 * 0.5 * 46, abs=0.01)


def test_get_today_live_data_partial_slot_scales_by_elapsed_time(config):
    """The current in-progress slot must use elapsed minutes, not a full 0.5h.

    At 13:14 BST (12:14 UTC), slot 26 (13:00–13:30) is 14 minutes in.
    A data point at 13:00 UTC (= 14:00 BST) would be slot 28 — so we use
    12:00 UTC (= 13:00 BST) for slot 26, and 11:00 UTC (= 12:00 BST) for slot 24.
    pvpower = 2.0 kW throughout.

    Slot 26 (current): 2.0 kW × (14/60) h ≈ 0.467 kWh
    Slot 24 (complete): 2.0 kW × (30/60) h = 1.0 kWh
    """
    today = date(2026, 5, 2)
    # 13:14 BST = 12:14 UTC (Europe/London is UTC+1 in May)
    tz = ZoneInfo("Europe/London")
    fake_now = datetime(2026, 5, 2, 13, 14, 0, tzinfo=tz)

    mock_points = [
        # slot 24 (12:00 BST = 11:00 UTC) — completed
        {**_make_mock_point(11, 0, pvpower=2.0), "time": "2026-05-02T11:00:00Z"},
        # slot 26 (13:00 BST = 12:00 UTC) — current in-progress
        {**_make_mock_point(12, 0, pvpower=2.0), "time": "2026-05-02T12:00:00Z"},
    ]
    mock_client = MagicMock()
    mock_client.query.return_value.get_points.return_value = mock_points

    with patch("solariq.data.influx.InfluxDBClient", return_value=mock_client), \
         patch("solariq.data.influx.fetch_agile_prices", return_value=[15.0] * 48), \
         patch("solariq.data.octopus.fetch_export_prices", return_value=[5.0] * 48), \
         patch("solariq.data.influx.datetime", wraps=datetime) as mock_dt:
        mock_dt.now.return_value = fake_now
        result = get_today_live_data(config, today=today)

    assert result.actual_solar[24] == pytest.approx(2.0 * 30 / 60, abs=0.001)  # complete
    assert result.actual_solar[26] == pytest.approx(2.0 * 14 / 60, abs=0.001)  # partial


def test_get_today_live_data_historical_date_uses_full_slots(config):
    """When today is a past date, all slots use full 0.5h regardless of current time."""
    historical = date(2026, 4, 1)
    tz = ZoneInfo("Europe/London")
    # Freeze wall clock to a fixed recent date so the test is deterministic
    # even if the suite happens to run on 2026-04-01.
    fake_now = datetime(2026, 5, 2, 10, 0, 0, tzinfo=tz)
    mock_points = [
        {**_make_mock_point(11, 0, pvpower=2.0), "time": "2026-04-01T11:00:00Z"},
    ]
    mock_client = MagicMock()
    mock_client.query.return_value.get_points.return_value = mock_points

    with patch("solariq.data.influx.InfluxDBClient", return_value=mock_client), \
         patch("solariq.data.influx.fetch_agile_prices", return_value=[15.0] * 48), \
         patch("solariq.data.octopus.fetch_export_prices", return_value=[5.0] * 48), \
         patch("solariq.data.influx.datetime", wraps=datetime) as mock_dt:
        mock_dt.now.return_value = fake_now
        result = get_today_live_data(config, today=historical)

    assert result.actual_solar[24] == pytest.approx(2.0 * 0.5, abs=0.001)


def test_get_today_live_data_empty_returns_zeros(config):
    mock_client = MagicMock()
    mock_client.query.return_value.get_points.return_value = []

    with patch("solariq.data.influx.InfluxDBClient", return_value=mock_client), \
         patch("solariq.data.influx.fetch_agile_prices", return_value=[15.0] * 48), \
         patch("solariq.data.octopus.fetch_export_prices", return_value=[5.0] * 48):
        result = get_today_live_data(config, today=date(2026, 5, 2))

    assert result.battery_soc_kwh == 0.0
    assert result.solar_today_kwh == 0.0
    assert result.last_data_slot == -1
