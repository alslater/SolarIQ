import pytest
from solariq.config import load_config
from solariq.optimizer.solver import solve

SLOTS = 48


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
    )
    assert result.battery_soc_forecast[-1] >= 10.0 - 0.01
