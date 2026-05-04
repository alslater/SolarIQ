import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from solariq.config import load_config
from solariq.optimizer.strategy import build_strategy_periods, _slot_to_time, build_rolling_window, current_window_start

SLOTS = 48


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def test_slot_to_time():
    assert _slot_to_time(0) == "00:00"
    assert _slot_to_time(5) == "02:30"
    assert _slot_to_time(10) == "05:00"
    assert _slot_to_time(47) == "23:30"


def test_all_self_use_gives_one_period(config):
    charge_mode = [False] * SLOTS
    soc = [config.battery.min_soc_kwh] * SLOTS
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    assert len(periods) == 1
    assert periods[0].mode == "Self Use"
    assert periods[0].start_time == "00:00"
    assert periods[0].end_time == "23:59"
    assert periods[0].is_default is True
    assert periods[0].min_soc_pct == 10


def test_one_charge_block_gives_three_periods(config):
    charge_mode = [False] * SLOTS
    for i in range(4, 10):  # 02:00-05:00
        charge_mode[i] = True
    soc = [config.battery.min_soc_kwh] * 4 + [12.0, 14.0, 16.0, 18.0, 20.0, 22.0] + [22.0] * 38
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    assert len(periods) == 3
    assert periods[0].mode == "Self Use"
    assert periods[1].mode == "Charge"
    assert periods[1].start_time == "02:00"
    assert periods[1].end_time == "05:00"
    assert periods[2].mode == "Self Use"
    assert periods[0].is_default is True


def test_charge_period_target_soc_is_end_soc_pct(config):
    charge_mode = [False] * 4 + [True] * 6 + [False] * 38
    # SOC rises from 10 to 15 kWh during charge (15/23.2*100 ≈ 65%)
    soc = [10.0] * 4 + [11.0, 12.0, 13.0, 14.0, 15.0, 15.0] + [15.0] * 38
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    charge_period = next(p for p in periods if p.mode == "Charge")
    # 15/23.2 * 100 = 64.6% → rounded to nearest 5 = 65%
    assert charge_period.target_soc_pct == 65


def test_max_periods_capped_at_10(config):
    # 6 charge blocks would give 7 self-use + 6 charge = 13 periods; should be capped at 10
    charge_mode = [False] * SLOTS
    for block in range(6):
        start = block * 8
        for i in range(start, start + 2):
            if i < SLOTS:
                charge_mode[i] = True
    soc = [10.0] * SLOTS
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    assert len(periods) <= 10


def test_self_use_period_has_min_soc(config):
    charge_mode = [False] * SLOTS
    soc = [config.battery.min_soc_kwh] * SLOTS
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    assert periods[0].min_soc_pct == 10


def test_explicit_self_use_period_can_be_above_default(config):
    charge_mode = [False] * SLOTS
    # Hold SOC around 50% all day -> explicit self-use min SOC should be > 10%.
    soc = [11.6] * SLOTS
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    assert len(periods) == 1
    assert periods[0].mode == "Self Use"
    assert periods[0].is_default is False
    assert periods[0].min_soc_pct > 10


def test_charge_period_has_max_charge_power(config):
    charge_mode = [False] * 4 + [True] * 6 + [False] * 38
    soc = [10.0] * SLOTS
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    charge_period = next(p for p in periods if p.mode == "Charge")
    assert charge_period.max_charge_w == 7500


# ── Rolling window tests ───────────────────────────────────────────────────────

def test_build_rolling_window_at_slot_0():
    """At slot 0, returns all of today's array."""
    today = list(range(48))
    tomorrow = [100 + i for i in range(48)]
    result = build_rolling_window(today, tomorrow, 0)
    assert result == today


def test_build_rolling_window_at_slot_36():
    """At slot 36 (18:00), first 12 from today[36:], last 36 from tomorrow[:36]."""
    today = list(range(48))
    tomorrow = [100 + i for i in range(48)]
    result = build_rolling_window(today, tomorrow, 36)
    assert result[:12] == list(range(36, 48))
    assert result[12:] == [100 + i for i in range(36)]


def test_build_rolling_window_at_slot_47():
    """At slot 47, 1 element from today, 47 from tomorrow."""
    today = list(range(48))
    tomorrow = [100 + i for i in range(48)]
    result = build_rolling_window(today, tomorrow, 47)
    assert result[0] == 47
    assert result[1:] == [100 + i for i in range(47)]


def test_build_rolling_window_returns_48_elements():
    today = [1.0] * 48
    tomorrow = [2.0] * 48
    for slot in [0, 1, 24, 36, 47]:
        result = build_rolling_window(today, tomorrow, slot)
        assert len(result) == 48


def test_current_window_start_returns_correct_slot():
    """current_window_start returns (slot, datetime) where slot matches hour/minute."""
    slot, ws = current_window_start("Europe/London")
    tz = ZoneInfo("Europe/London")
    now = datetime.now(tz)
    expected_slot = (now.hour * 60 + now.minute) // 30
    assert slot == expected_slot
    assert ws.tzinfo is not None
    assert ws.second == 0
    assert ws.microsecond == 0


def test_build_strategy_periods_with_window_start_18(config):
    """With window_start at 18:00, slot 6 start_time should be 21:00."""
    tz = ZoneInfo("Europe/London")
    window_start = datetime(2026, 4, 1, 18, 0, tzinfo=tz)
    charge_mode = [False] * 6 + [True] * 6 + [False] * 36
    soc = [10.0] * 6 + [12.0, 14.0, 16.0, 18.0, 20.0, 22.0] + [22.0] * 36
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config, window_start=window_start)
    charge_period = next(p for p in periods if p.mode == "Charge")
    # Slot 6 from 18:00 = 18:00 + 6*30min = 21:00
    assert charge_period.start_time == "21:00"
    # Slot 12 from 18:00 = 18:00 + 12*30min = 00:00 (next day)
    assert charge_period.end_time == "00:00"


def test_build_strategy_periods_with_window_start_none_unchanged(config):
    """Without window_start, behaviour is unchanged (midnight-anchored)."""
    charge_mode = [False] * 4 + [True] * 6 + [False] * 38
    soc = [10.0] * SLOTS
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    charge_period = next(p for p in periods if p.mode == "Charge")
    assert charge_period.start_time == "02:00"
    assert charge_period.end_time == "05:00"


def test_build_strategy_periods_end_sentinel_with_window_start(config):
    """With window_start, end of last period is window_start + 24h, not '23:59'."""
    tz = ZoneInfo("Europe/London")
    window_start = datetime(2026, 4, 1, 18, 0, tzinfo=tz)
    charge_mode = [False] * SLOTS  # all self-use, one period covering full window
    soc = [10.0] * SLOTS
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config, window_start=window_start)
    # Full window ends at 18:00 next day
    assert periods[-1].end_time == "18:00"


def test_charge_block_crossing_midnight_is_split(config):
    """A charge block that spans midnight is split into two periods at 00:00."""
    tz = ZoneInfo("Europe/London")
    # Window starts at 22:00; midnight falls at slot 4 (22:00 + 4*30min = 00:00)
    window_start = datetime(2026, 4, 1, 22, 0, tzinfo=tz)
    # Charge from slot 2 (23:00) to slot 6 (01:00) crosses midnight at slot 4
    charge_mode = [False] * 2 + [True] * 4 + [False] * 42
    soc = [10.0] * 2 + [11.0, 12.0, 13.0, 14.0] + [14.0] * 42
    prices = [10.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config, window_start=window_start)
    charge_periods = [p for p in periods if p.mode == "Charge"]
    assert len(charge_periods) == 2
    assert charge_periods[0].start_time == "23:00"
    assert charge_periods[0].end_time == "00:00"
    assert charge_periods[1].start_time == "00:00"
    assert charge_periods[1].end_time == "01:00"


def test_self_use_block_crossing_midnight_is_split(config):
    """A self-use block spanning midnight is also split at 00:00."""
    tz = ZoneInfo("Europe/London")
    # Window starts at 23:00; midnight at slot 2 (23:00 + 2*30min = 00:00)
    window_start = datetime(2026, 4, 1, 23, 0, tzinfo=tz)
    charge_mode = [False] * SLOTS
    soc = [10.0] * SLOTS
    prices = [10.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config, window_start=window_start)
    # The single self-use block must have been split at midnight
    times = [(p.start_time, p.end_time) for p in periods]
    assert ("23:00", "00:00") in times
    assert any(p.start_time == "00:00" for p in periods)


def test_block_not_crossing_midnight_is_not_split(config):
    """A charge block fully before midnight is not split."""
    tz = ZoneInfo("Europe/London")
    # Window starts at 22:00; midnight at slot 4
    window_start = datetime(2026, 4, 1, 22, 0, tzinfo=tz)
    # Charge from slot 0 (22:00) to slot 3 (23:30) — fully before midnight
    charge_mode = [True] * 3 + [False] * 45
    soc = [10.0, 12.0, 14.0] + [14.0] * 45
    prices = [10.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config, window_start=window_start)
    charge_periods = [p for p in periods if p.mode == "Charge"]
    assert len(charge_periods) == 1
    assert charge_periods[0].start_time == "22:00"
    assert charge_periods[0].end_time == "23:30"


def test_no_midnight_split_when_window_start_none(config):
    """Without window_start, midnight-split logic is skipped."""
    charge_mode = [True] * 4 + [False] * 44
    soc = [10.0, 11.0, 12.0, 13.0] + [13.0] * 44
    prices = [10.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    charge_periods = [p for p in periods if p.mode == "Charge"]
    assert len(charge_periods) == 1
