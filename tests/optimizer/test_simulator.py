# tests/optimizer/test_simulator.py
import pytest
from solariq.config import load_config
from solariq.optimizer.simulator import simulate, validate_periods
from solariq.optimizer.types import UserPeriod

SLOTS = 48


@pytest.fixture
def config(test_ini_path):
    return load_config(test_ini_path)


def _flat(value: float) -> list[float]:
    return [value] * SLOTS


def _make_forecast(
    agile: float = 15.0,
    export: float = 5.0,
    solar: float = 0.0,
    load: float = 0.3,
    initial_soc_kwh: float = 5.0,
):
    """Return a minimal dict that simulate() can use in place of OptimizationResult."""
    from dataclasses import dataclass

    @dataclass
    class FakeForecast:
        agile_prices: list
        export_prices: list
        solar_forecast: list
        load_forecast: list
        battery_soc_forecast: list

    return FakeForecast(
        agile_prices=_flat(agile),
        export_prices=_flat(export),
        solar_forecast=_flat(solar),
        load_forecast=_flat(load),
        battery_soc_forecast=[initial_soc_kwh] * SLOTS,
    )


# --- validate_periods tests ---

def test_validate_accepts_full_day_single_period():
    periods = [UserPeriod("00:00", "24:00", "Self Use")]
    assert validate_periods(periods) is None


def test_validate_accepts_two_contiguous_periods():
    periods = [
        UserPeriod("00:00", "05:00", "Charge"),
        UserPeriod("05:00", "24:00", "Self Use"),
    ]
    assert validate_periods(periods) is None


def test_validate_rejects_gap():
    periods = [
        UserPeriod("00:00", "04:00", "Charge"),
        UserPeriod("05:00", "24:00", "Self Use"),
    ]
    error = validate_periods(periods)
    assert error is not None
    assert "gap" in error.lower()


def test_validate_rejects_overlap():
    periods = [
        UserPeriod("00:00", "06:00", "Charge"),
        UserPeriod("05:00", "24:00", "Self Use"),
    ]
    error = validate_periods(periods)
    assert error is not None
    assert "overlap" in error.lower()


def test_validate_rejects_too_many_periods():
    periods = [
        UserPeriod(f"{h:02d}:00", f"{h+1:02d}:00", "Self Use")
        for h in range(11)
    ]
    error = validate_periods(periods)
    assert error is not None
    assert "10" in error


def test_validate_rejects_start_not_less_than_end():
    periods = [UserPeriod("06:00", "05:00", "Charge")]
    error = validate_periods(periods)
    assert error is not None


def test_validate_rejects_incomplete_coverage():
    periods = [UserPeriod("00:00", "23:00", "Self Use")]
    error = validate_periods(periods)
    assert error is not None
    assert "24:00" in error or "cover" in error.lower()


def test_validate_rejects_zero_max_charge_kw():
    periods = [UserPeriod("00:00", "24:00", "Charge", max_charge_kw=0.0)]
    error = validate_periods(periods)
    assert error is not None
    assert "max_charge_kw" in error


def test_validate_rejects_negative_max_charge_kw():
    periods = [UserPeriod("00:00", "24:00", "Charge", max_charge_kw=-1.0)]
    error = validate_periods(periods)
    assert error is not None
    assert "max_charge_kw" in error


def test_validate_rejects_max_charge_kw_exceeds_battery(config):
    periods = [UserPeriod("00:00", "24:00", "Charge", max_charge_kw=config.battery.max_charge_kw + 1.0)]
    error = validate_periods(periods, battery=config.battery)
    assert error is not None
    assert "exceeds" in error


def test_validate_accepts_max_charge_kw_at_battery_limit(config):
    periods = [UserPeriod("00:00", "24:00", "Charge", max_charge_kw=config.battery.max_charge_kw)]
    assert validate_periods(periods, battery=config.battery) is None


def test_validate_rejects_target_soc_below_battery_min(config):
    below_min = config.battery.min_soc_pct - 1
    periods = [UserPeriod("00:00", "24:00", "Charge", target_soc_pct=below_min)]
    error = validate_periods(periods, battery=config.battery)
    assert error is not None
    assert "minimum" in error


def test_validate_accepts_target_soc_at_battery_min(config):
    periods = [UserPeriod("00:00", "24:00", "Charge", target_soc_pct=config.battery.min_soc_pct)]
    assert validate_periods(periods, battery=config.battery) is None


def test_validate_battery_checks_skipped_without_battery():
    """Battery-aware checks must not run when battery is not passed."""
    # max_charge_kw > any real battery max — would fail if battery were passed
    periods = [UserPeriod("00:00", "24:00", "Charge", max_charge_kw=999.0, target_soc_pct=0)]
    assert validate_periods(periods) is None


def test_simulate_raises_on_invalid_start_slot(config):
    periods = [UserPeriod("00:00", "24:00", "Self Use")]
    forecast = _make_forecast()
    with pytest.raises(ValueError, match="start_slot"):
        simulate(periods, forecast, config.battery, start_slot=-1)
    with pytest.raises(ValueError, match="start_slot"):
        simulate(periods, forecast, config.battery, start_slot=48)


def test_simulate_raises_if_periods_do_not_cover_window(config):
    """simulate() must raise ValueError if periods leave a gap, rather than producing
    a silent IndexError or misaligned results — defensive check for direct callers
    that skip validate_periods().
    """
    # Period only covers half the day — gap from 12:00 to 24:00
    periods = [UserPeriod("00:00", "12:00", "Self Use")]
    forecast = _make_forecast()
    with pytest.raises(ValueError, match="validate_periods"):
        simulate(periods, forecast, config.battery)


# --- simulate tests ---

def test_simulate_returns_48_slots(config):
    periods = [UserPeriod("00:00", "24:00", "Self Use")]
    forecast = _make_forecast()
    result = simulate(periods, forecast, config.battery)
    assert len(result.battery_soc_forecast) == SLOTS
    assert len(result.grid_import_forecast) == SLOTS
    assert len(result.grid_export_forecast) == SLOTS
    assert len(result.charge_mode_slots) == SLOTS


def test_simulate_charge_period_fills_battery(config):
    """A full-day Charge period with no solar should grid-import to reach target SOC."""
    periods = [UserPeriod("00:00", "24:00", "Charge", target_soc_pct=100, max_charge_kw=7.5)]
    capacity = config.battery.capacity_kwh   # 23.2 kWh
    forecast = _make_forecast(solar=0.0, load=0.0, initial_soc_kwh=0.0)
    result = simulate(periods, forecast, config.battery)
    # Battery should have charged up significantly
    assert result.battery_soc_forecast[-1] > capacity * 0.8


def test_simulate_self_use_discharges_to_min_soc(config):
    """Self Use with no solar and a load should discharge battery to min_soc floor."""
    min_soc_pct = 10
    periods = [UserPeriod("00:00", "24:00", "Self Use", min_soc_pct=min_soc_pct)]
    capacity = config.battery.capacity_kwh
    min_soc_kwh = capacity * min_soc_pct / 100
    forecast = _make_forecast(solar=0.0, load=0.5, initial_soc_kwh=capacity)
    result = simulate(periods, forecast, config.battery)
    # SOC should not drop below min_soc floor
    assert all(soc >= min_soc_kwh - 0.01 for soc in result.battery_soc_forecast)


def test_simulate_energy_balance_holds_each_slot(config):
    """grid_import + solar + discharge == load + charge + grid_export (per slot, approx)."""
    periods = [
        UserPeriod("00:00", "06:00", "Charge", target_soc_pct=80, max_charge_kw=3.6),
        UserPeriod("06:00", "24:00", "Self Use", min_soc_pct=10),
    ]
    forecast = _make_forecast(solar=0.3, load=0.3, initial_soc_kwh=5.0)
    result = simulate(periods, forecast, config.battery)
    solar = forecast.solar_forecast
    load = forecast.load_forecast
    soc = result.battery_soc_forecast
    gi = result.grid_import_forecast
    ge = result.grid_export_forecast

    # Derive charge/discharge from SOC delta
    prev_soc = forecast.battery_soc_forecast[0]
    for t in range(SLOTS):
        delta = soc[t] - prev_soc
        charge = max(delta, 0.0)
        discharge = max(-delta, 0.0)
        lhs = gi[t] + solar[t] + discharge
        rhs = load[t] + charge + ge[t]
        assert abs(lhs - rhs) < 0.001, f"Energy balance violated at slot {t}: {lhs} != {rhs}"
        prev_soc = soc[t]


def test_simulate_cost_calculation(config):
    """Cost = sum(import * agile - export * export_price) / 100."""
    periods = [UserPeriod("00:00", "24:00", "Self Use", min_soc_pct=10)]
    agile_p = 20.0
    export_p = 5.0
    forecast = _make_forecast(agile=agile_p, export=export_p, solar=0.0, load=0.3, initial_soc_kwh=10.0)
    result = simulate(periods, forecast, config.battery)
    expected_cost = sum(
        result.grid_import_forecast[t] * agile_p - result.grid_export_forecast[t] * export_p
        for t in range(SLOTS)
    ) / 100
    assert abs(result.estimated_cost_gbp - expected_cost) < 0.001


def test_simulate_no_grid_import_when_solar_exceeds_load(config):
    """When solar > load and battery is full, excess is exported — no grid import."""
    periods = [UserPeriod("00:00", "24:00", "Self Use", min_soc_pct=10)]
    capacity = config.battery.capacity_kwh
    forecast = _make_forecast(solar=1.0, load=0.1, initial_soc_kwh=capacity)
    result = simulate(periods, forecast, config.battery)
    assert all(gi < 0.001 for gi in result.grid_import_forecast)


def test_simulate_copies_forecast_arrays_to_result(config):
    """EvaluationResult must include agile_prices, export_prices, solar_forecast from input."""
    periods = [UserPeriod("00:00", "24:00", "Self Use")]
    forecast = _make_forecast(agile=12.0, export=4.0, solar=0.5)
    result = simulate(periods, forecast, config.battery)
    assert result.agile_prices == forecast.agile_prices
    assert result.export_prices == forecast.export_prices
    assert result.solar_forecast == forecast.solar_forecast


def test_simulate_charge_respects_battery_physical_limit(config):
    """max_charge_kw on a Charge period is user intent, but simulate() must not exceed
    battery.max_charge_kwh_per_slot regardless of what validate_periods was called with.
    """
    battery = config.battery  # max_charge_kwh_per_slot = 3.6 / 2 = 1.8 kWh
    # Set max_charge_kw far above battery physical limit; skip battery= in validate so
    # validate_periods does NOT catch it — simulate() must still clamp.
    oversized_kw = battery.max_charge_kw * 10
    periods = [UserPeriod("00:00", "24:00", "Charge", target_soc_pct=100, max_charge_kw=oversized_kw)]
    forecast = _make_forecast(solar=0.0, load=0.0, initial_soc_kwh=0.0)
    result = simulate(periods, forecast, battery)
    max_imported_per_slot = max(result.grid_import_forecast)
    assert max_imported_per_slot <= battery.max_charge_kwh_per_slot + 1e-9


def test_simulate_charge_mode_exports_excess_solar(config):
    """During a Charge period, solar exceeding load + charge target should be exported."""
    # Battery already at target, solar > load — surplus should be exported not dropped
    capacity = config.battery.capacity_kwh
    periods = [UserPeriod("00:00", "24:00", "Charge", target_soc_pct=50, max_charge_kw=7.5)]
    target_soc_kwh = capacity * 0.5
    forecast = _make_forecast(solar=2.0, load=0.1, initial_soc_kwh=target_soc_kwh)
    result = simulate(periods, forecast, config.battery)
    # Battery is already at target — all solar above load should be exported
    assert sum(result.grid_export_forecast) > 0
    # And grid import should be minimal (only load when battery already full)
    assert sum(result.grid_import_forecast) < 0.1 * SLOTS


def test_validate_rejects_invalid_start_slot():
    periods = [UserPeriod("00:00", "24:00", "Self Use")]
    assert validate_periods(periods, start_slot=-1) is not None
    assert validate_periods(periods, start_slot=48) is not None
    assert validate_periods(periods, start_slot=49) is not None


def test_validate_accepts_partial_day_from_slot():
    """validate_periods with start_slot=12 (06:00) should accept periods starting at 06:00."""
    periods = [
        UserPeriod("06:00", "10:00", "Charge"),
        UserPeriod("10:00", "24:00", "Self Use"),
    ]
    assert validate_periods(periods, start_slot=12) is None


def test_validate_rejects_wrong_start_for_partial_day():
    """validate_periods with start_slot=12 should reject periods starting at 00:00."""
    periods = [UserPeriod("00:00", "24:00", "Self Use")]
    error = validate_periods(periods, start_slot=12)
    assert error is not None
    assert "06:00" in error


def test_simulate_start_slot_zeros_past_slots(config):
    """Slots before start_slot should be 0.0 in all output arrays."""
    start_slot = 10
    periods = [UserPeriod("05:00", "24:00", "Self Use", min_soc_pct=10)]
    forecast = _make_forecast(solar=0.3, load=0.3, initial_soc_kwh=10.0)
    result = simulate(periods, forecast, config.battery, start_slot=start_slot)
    for t in range(start_slot):
        assert result.grid_import_forecast[t] == 0.0
        assert result.grid_export_forecast[t] == 0.0
        assert result.battery_soc_forecast[t] == 0.0
        assert result.charge_mode_slots[t] is False


def test_simulate_start_slot_uses_correct_initial_soc(config):
    """simulate with start_slot should use battery_soc_forecast[start_slot] as initial SOC."""
    start_slot = 10
    initial_soc = 15.0
    forecast = _make_forecast(initial_soc_kwh=5.0)
    forecast.battery_soc_forecast[start_slot] = initial_soc
    periods = [UserPeriod("05:00", "24:00", "Self Use", min_soc_pct=10)]
    result = simulate(periods, forecast, config.battery, start_slot=start_slot)
    # First simulated slot SOC should be <= initial_soc (battery discharged a bit for load)
    assert result.battery_soc_forecast[start_slot] <= initial_soc
    assert result.battery_soc_forecast[start_slot] > 0.0


def test_simulate_start_slot_cost_covers_only_simulated_slots(config):
    """Cost should only cover slots start_slot..47, not the zero-padded past."""
    start_slot = 24  # noon
    periods = [UserPeriod("12:00", "24:00", "Self Use", min_soc_pct=10)]
    forecast = _make_forecast(agile=20.0, export=5.0, solar=0.0, load=0.3, initial_soc_kwh=5.0)
    result_half = simulate(periods, forecast, config.battery, start_slot=start_slot)
    # Compute expected cost from only the simulated slots (start_slot to 47)
    expected_cost = sum(
        result_half.grid_import_forecast[t] * forecast.agile_prices[t] - result_half.grid_export_forecast[t] * forecast.export_prices[t]
        for t in range(start_slot, SLOTS)
    ) / 100
    # Assert the computed value equals the result cost (within float tolerance)
    assert result_half.estimated_cost_gbp == pytest.approx(expected_cost)
    # Past slots contribute zero grid import
    assert sum(result_half.grid_import_forecast[:start_slot]) == 0.0


# --- Integration: today-mode data flow ---

def test_validate_rejects_malformed_time():
    """Malformed time strings (e.g. '16::00') should return an error, not silently pass.

    evaluate_schedule wraps validate_periods in a try/except for genuine parse errors,
    but validate_periods now catches bad boundaries itself and returns a string error.
    """
    periods = [UserPeriod("00:00", "16::00", "Self Use")]
    error = validate_periods(periods)
    assert error is not None


def test_validate_rejects_out_of_range_minutes():
    """'23:60' has minutes >= 60 — _time_to_slot would map it to slot 48 (24:00),
    silently treating a malformed time as end-of-day.
    """
    periods = [UserPeriod("00:00", "23:60", "Self Use")]
    error = validate_periods(periods)
    assert error is not None
    assert "23:60" in error


def test_validate_rejects_unknown_mode():
    periods = [UserPeriod("00:00", "24:00", "Discharge")]
    error = validate_periods(periods)
    assert error is not None
    assert "Discharge" in error


def test_simulate_raises_on_unknown_mode(config):
    """simulate() must raise rather than silently treat an unknown mode as Self Use."""
    periods = [UserPeriod("00:00", "24:00", "Discharge")]
    forecast = _make_forecast(solar=0.0, load=0.0, initial_soc_kwh=0.0)
    with pytest.raises(ValueError, match="Discharge"):
        simulate(periods, forecast, config.battery)


def test_validate_rejects_non_half_hour_boundary():
    """Times that don't fall on a half-hour boundary (e.g. '21:45') must be rejected.

    _time_to_slot() truncates minutes to the nearest half-hour, so '21:45' silently
    becomes slot 43 (21:30). Without this check a period split at '21:45' would be
    accepted but the 15-minute partial slot would be silently ignored.
    """
    periods = [
        UserPeriod("00:00", "21:45", "Self Use"),
        UserPeriod("21:45", "24:00", "Charge"),
    ]
    error = validate_periods(periods)
    assert error is not None
    assert "21:45" in error


def test_simulate_stitched_today_forecast(config):
    """Simulate with a stitched actual+forecast array, as evaluate_schedule builds
    for today mode: actuals for slots 0..current_slot-1, solar forecast for
    current_slot..47.  Solar in past slots should not affect future cost.
    """
    from dataclasses import dataclass

    @dataclass
    class StitchedForecast:
        agile_prices: list
        export_prices: list
        solar_forecast: list
        load_forecast: list
        battery_soc_forecast: list

    current_slot = 20  # 10:00
    # Past slots: high solar actuals (should not be simulated)
    # Future slots: zero solar forecast
    solar = ([2.0] * current_slot + [0.0] * (SLOTS - current_slot))
    load = [0.3] * SLOTS
    soc_48 = [0.0] * SLOTS
    soc_48[current_slot] = 8.0

    forecast = StitchedForecast(
        agile_prices=_flat(20.0),
        export_prices=_flat(5.0),
        solar_forecast=solar,
        load_forecast=load,
        battery_soc_forecast=soc_48,
    )
    periods = [UserPeriod("10:00", "24:00", "Self Use", min_soc_pct=10)]
    result = simulate(periods, forecast, config.battery, start_slot=current_slot)

    # Past slots must be zeroed — actuals are not simulated
    assert all(result.grid_import_forecast[t] == 0.0 for t in range(current_slot))
    # Future slots have no solar so battery must cover load; grid import expected
    assert sum(result.grid_import_forecast[current_slot:]) > 0.0
    # solar_forecast_kwh should only sum future slots (all zero solar there)
    assert result.solar_forecast_kwh == pytest.approx(0.0)


def test_simulate_short_snapshot_arrays_padded(config):
    """Short arrays from a mid-day snapshot (fewer than 48 entries) must be padded
    to 48 before stitching or simulate() will index out of range.  This mirrors the
    normalisation that evaluate_schedule applies before calling simulate().
    """
    from dataclasses import dataclass

    @dataclass
    class PaddedForecast:
        agile_prices: list
        export_prices: list
        solar_forecast: list
        load_forecast: list
        battery_soc_forecast: list

    current_slot = 16  # 08:00 — only 16 actual slots available
    raw_actual_solar = [0.1] * current_slot   # snapshot only has 16 entries
    raw_actual_usage = [0.4] * current_slot   # likewise — deliberately different from predicted
    raw_predicted_usage = [0.3] * current_slot

    # Normalise exactly as evaluate_schedule does
    actual_solar = (raw_actual_solar + [0.0] * SLOTS)[:SLOTS]
    actual_usage = (raw_actual_usage + [0.0] * SLOTS)[:SLOTS]
    predicted_usage = (raw_predicted_usage + [0.3] * SLOTS)[:SLOTS]
    solar_forecast_today = [0.5] * SLOTS

    solar_48 = actual_solar[:current_slot] + solar_forecast_today[current_slot:]
    load_48 = actual_usage[:current_slot] + predicted_usage[current_slot:]  # actuals for past, predicted for future
    soc_48 = [0.0] * SLOTS
    soc_48[current_slot] = 6.0

    assert len(solar_48) == SLOTS
    assert len(load_48) == SLOTS

    forecast = PaddedForecast(
        agile_prices=_flat(15.0),
        export_prices=_flat(4.0),
        solar_forecast=solar_48,
        load_forecast=load_48,
        battery_soc_forecast=soc_48,
    )
    periods = [UserPeriod("08:00", "24:00", "Self Use", min_soc_pct=10)]
    result = simulate(periods, forecast, config.battery, start_slot=current_slot)

    assert len(result.battery_soc_forecast) == SLOTS
    assert len(result.grid_import_forecast) == SLOTS
