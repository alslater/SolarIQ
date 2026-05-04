import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from solariq.config import load_config
from solariq.optimizer.solver import solve

SLOTS = 48

_WINDOW_START = datetime(2026, 1, 1, 18, 0, tzinfo=ZoneInfo("Europe/London"))


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def _flat(value: float) -> list[float]:
    return [value] * SLOTS


def test_solver_returns_48_slot_decisions(config):
    result = solve(
        agile_prices=_flat(15.0),
        export_prices=_flat(5.0),
        solar=_flat(0.0),
        load=_flat(0.3),
        initial_soc_kwh=10.0,
        config=config,
        window_start=_WINDOW_START,
    )
    assert len(result.battery_soc_forecast) == SLOTS
    assert len(result.charge_mode_slots) == SLOTS
    assert len(result.grid_import_forecast) == SLOTS


def test_solver_charges_in_cheapest_slots(config):
    """With cheap prices in slots 4-9 (02:00-05:00) and expensive elsewhere,
    solver should schedule charging in those slots."""
    prices = [25.0] * SLOTS
    for i in range(4, 10):
        prices[i] = 5.0  # cheap 02:00-05:00

    result = solve(
        agile_prices=prices,
        export_prices=_flat(3.0),
        solar=_flat(0.0),
        load=_flat(0.3),
        initial_soc_kwh=5.0,
        config=config,
        window_start=_WINDOW_START,
    )
    cheap_charge = sum(result.charge_mode_slots[4:10])
    expensive_charge = sum(result.charge_mode_slots[:4]) + sum(result.charge_mode_slots[10:])
    assert cheap_charge > expensive_charge


def test_solver_soc_stays_within_bounds(config):
    result = solve(
        agile_prices=_flat(15.0),
        export_prices=_flat(5.0),
        solar=_flat(0.0),
        load=_flat(0.5),
        initial_soc_kwh=10.0,
        config=config,
        window_start=_WINDOW_START,
    )
    min_soc = config.battery.min_soc_kwh
    max_soc = config.battery.capacity_kwh
    for soc in result.battery_soc_forecast:
        assert soc >= min_soc - 0.01
        assert soc <= max_soc + 0.01


def test_solver_no_discharge_during_charge_slots(config):
    result = solve(
        agile_prices=_flat(15.0),
        export_prices=_flat(5.0),
        solar=_flat(0.0),
        load=_flat(0.3),
        initial_soc_kwh=5.0,
        config=config,
        window_start=_WINDOW_START,
    )
    for t in range(SLOTS):
        if result.charge_mode_slots[t]:
            # battery_soc should be increasing or flat — can't discharge
            if t > 0:
                assert result.battery_soc_forecast[t] >= result.battery_soc_forecast[t - 1] - 0.01


def test_solver_end_soc_not_less_than_start(config):
    result = solve(
        agile_prices=_flat(15.0),
        export_prices=_flat(5.0),
        solar=_flat(0.0),
        load=_flat(0.3),
        initial_soc_kwh=10.0,
        config=config,
        window_start=_WINDOW_START,
    )
    assert result.battery_soc_forecast[-1] >= 10.0 - 0.01


def test_solver_reserves_soc_for_peak_window(config):
    """SOC before 16:00 should cover expected 16:00-19:00 net demand."""
    window_start = datetime(2026, 1, 1, 0, 0, tzinfo=ZoneInfo("Europe/London"))
    prices = [40.0] * 48
    for i in range(40, 48):
        prices[i] = 1.0  # cheap only after the peak window

    solar = [0.0] * 48
    load = [0.0] * 48
    for i in range(32, 38):  # 16:00-19:00
        load[i] = 1.0

    initial_soc = config.battery.min_soc_kwh
    result = solve(
        agile_prices=prices,
        export_prices=_flat(0.0),
        solar=solar,
        load=load,
        initial_soc_kwh=initial_soc,
        config=config,
        window_start=window_start,
    )

    expected_peak_demand = sum(load[32:38])
    required_soc = min(
        config.battery.capacity_kwh,
        config.battery.min_soc_kwh + expected_peak_demand,
    )
    # Slot 31 ends at 16:00; it is the last slot before the peak window starts.
    assert result.battery_soc_forecast[31] >= required_soc - 0.05
