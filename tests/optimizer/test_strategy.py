import pytest
from solariq.config import load_config
from solariq.optimizer.strategy import build_strategy_periods, _slot_to_time

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
    soc = [10.0] * SLOTS
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    assert len(periods) == 1
    assert periods[0].mode == "Self Use"
    assert periods[0].start_time == "00:00"
    assert periods[0].end_time == "23:59"


def test_one_charge_block_gives_three_periods(config):
    charge_mode = [False] * SLOTS
    for i in range(4, 10):  # 02:00-05:00
        charge_mode[i] = True
    soc = [10.0] * 4 + [12.0, 14.0, 16.0, 18.0, 20.0, 22.0] + [22.0] * 38
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    assert len(periods) == 3
    assert periods[0].mode == "Self Use"
    assert periods[1].mode == "Charge"
    assert periods[1].start_time == "02:00"
    assert periods[1].end_time == "05:00"
    assert periods[2].mode == "Self Use"


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
    soc = [10.0] * SLOTS
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    assert periods[0].min_soc_pct == config.battery.min_soc_pct


def test_charge_period_has_max_charge_power(config):
    charge_mode = [False] * 4 + [True] * 6 + [False] * 38
    soc = [10.0] * SLOTS
    prices = [15.0] * SLOTS
    periods = build_strategy_periods(charge_mode, soc, prices, config)
    charge_period = next(p for p in periods if p.mode == "Charge")
    assert charge_period.max_charge_w == 7500
