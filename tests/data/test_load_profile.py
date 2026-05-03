from datetime import date
from unittest.mock import patch

import pytest

from solariq.config import load_config
from solariq.data.load_profile import build_load_profile


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def _make_48_slots(usage_per_slot: float) -> list[float]:
    return [usage_per_slot] * 48


def test_build_load_profile_returns_48_slots(config):
    with patch("solariq.data.load_profile.query_solax_usage_day") as mock_q, \
         patch("solariq.data.load_profile.fetch_daily_temperatures", side_effect=Exception("no weather")):
        mock_q.return_value = _make_48_slots(0.5)
        profile = build_load_profile(config, target_date=date(2026, 5, 4))  # Monday
    assert len(profile) == 48


def test_build_load_profile_averages_usage(config):
    with patch("solariq.data.load_profile.query_solax_usage_day") as mock_q, \
         patch("solariq.data.load_profile.fetch_daily_temperatures", side_effect=Exception("no weather")):
        mock_q.return_value = _make_48_slots(0.4)
        profile = build_load_profile(config, target_date=date(2026, 5, 4))
    assert all(pytest.approx(v, abs=0.01) == 0.4 for v in profile)


def test_build_load_profile_returns_fallback_on_no_data(config):
    with patch("solariq.data.load_profile.query_solax_usage_day") as mock_q, \
         patch("solariq.data.load_profile.fetch_daily_temperatures", side_effect=Exception("no weather")):
        mock_q.return_value = [0.0] * 48  # all zeros → no usable data → fallback
        profile = build_load_profile(config, target_date=date(2026, 5, 4))
    assert len(profile) == 48
    assert all(v > 0 for v in profile)


def test_build_load_profile_queries_same_weekday(config):
    """Should query 4 Mondays when target is a Monday."""
    with patch("solariq.data.load_profile.query_solax_usage_day") as mock_q, \
         patch("solariq.data.load_profile.fetch_daily_temperatures", side_effect=Exception("no weather")):
        mock_q.return_value = _make_48_slots(0.5)
        build_load_profile(config, target_date=date(2026, 5, 4))  # Monday
    assert mock_q.call_count == 4
