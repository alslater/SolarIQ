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


def test_solver_result_has_standby_mode_slots(config):
    result = solve(
        agile_prices=_flat(15.0),
        export_prices=_flat(5.0),
        solar=_flat(0.0),
        load=_flat(0.3),
        initial_soc_kwh=10.0,
        config=config,
        window_start=_WINDOW_START,
    )
    assert hasattr(result, "standby_mode_slots")
    assert len(result.standby_mode_slots) == SLOTS
    assert all(isinstance(v, bool) for v in result.standby_mode_slots)


def test_solver_uses_standby_when_export_exceeds_storage_value(config):
    """When the battery is full and export price is low (not worth discharging),
    solar surplus exports directly and the optimizer produces standby slots
    (battery idle, solar routes straight to grid)."""
    window_start = datetime(2026, 1, 1, 8, 0, tzinfo=ZoneInfo("Europe/London"))

    agile = [20.0] * SLOTS
    # Low export price — discharging the battery to export is not economically
    # worthwhile, so the MILP leaves the battery idle during solar surplus slots.
    export = [2.0] * SLOTS

    solar = [0.0] * SLOTS
    for i in range(12):
        solar[i] = 1.5       # 1.5 kWh/slot solar in morning

    load = [0.3] * SLOTS

    # Battery fully charged — no headroom to absorb solar surplus by charging
    initial_soc_kwh = config.battery.capacity_kwh

    result = solve(
        agile_prices=agile,
        export_prices=export,
        solar=solar,
        load=load,
        initial_soc_kwh=initial_soc_kwh,
        config=config,
        window_start=window_start,
    )

    # Should have some standby slots during the solar morning period
    morning_standby = sum(result.standby_mode_slots[:12])
    assert morning_standby > 0, (
        f"Expected standby slots in morning solar period. "
        f"standby_mode_slots[:12]={result.standby_mode_slots[:12]}"
    )

    # During standby, SOC should stay approximately flat
    for t in range(1, SLOTS):
        if result.standby_mode_slots[t] and result.standby_mode_slots[t - 1]:
            soc_delta = abs(result.battery_soc_forecast[t] - result.battery_soc_forecast[t - 1])
            assert soc_delta < 0.1, f"SOC changed by {soc_delta:.3f} kWh during standby slot {t}"
