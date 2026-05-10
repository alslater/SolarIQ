# solariq/optimizer/simulator.py
from solariq.optimizer.types import EvaluationResult, UserPeriod

SLOTS = 48

def _time_to_slot(t: str) -> int:
    """Convert "HH:MM" or "24:00" to a slot index (0–48)."""
    if t == "24:00":
        return 48
    h, m = map(int, t.split(":"))
    return h * 2 + m // 30


def _slot_to_time(slot: int) -> str:
    """Convert slot index (0–48) to "HH:MM" or "24:00"."""
    if slot == 48:
        return "24:00"
    h = (slot * 30) // 60
    m = (slot * 30) % 60
    return f"{h:02d}:{m:02d}"


def _is_slot_boundary(t: str) -> bool:
    """Return True if t falls exactly on a 30-minute slot boundary.

    The simulation models 48 half-hour slots. Times between boundaries (e.g. 21:45)
    cannot be represented — _time_to_slot would silently truncate them, producing
    wrong results without any error.
    """
    if t == "24:00":
        return True
    try:
        h, m = map(int, t.split(":"))
    except (ValueError, AttributeError):
        return False
    return 0 <= h <= 23 and m % 30 == 0


def validate_periods(periods: list[UserPeriod], start_slot: int = 0, battery=None) -> str | None:
    """Return an error string if periods are invalid, None if valid.

    Pass `battery` (a BatteryConfig) to enable battery-aware checks:
    - max_charge_kw must be > 0 and <= battery.max_charge_kw
    - target_soc_pct (Charge mode) must be >= battery.min_soc_pct
    """
    if not periods:
        return "At least one period is required."

    if len(periods) > 10:
        # SolaX inverters support at most 10 charge/discharge time slots in their
        # schedule configuration, so plans with more periods can't be applied.
        return "Maximum 10 periods allowed (inverter limit)."

    for p in periods:
        if not _is_slot_boundary(p.start_time):
            return f"Start time {p.start_time!r} must be on a 30-minute boundary (HH:00 or HH:30) — the simulation models 48 half-hour slots."
        if not _is_slot_boundary(p.end_time):
            return f"End time {p.end_time!r} must be on a 30-minute boundary (HH:00 or HH:30) — the simulation models 48 half-hour slots."

    for p in periods:
        start = _time_to_slot(p.start_time)
        end = _time_to_slot(p.end_time)
        if start >= end:
            return f"Period start ({p.start_time}) must be before end ({p.end_time})."

    for p in periods:
        if p.mode == "Charge":
            if not (0 <= p.target_soc_pct <= 100):
                return f"target_soc_pct must be 0–100 (got {p.target_soc_pct})."
            if battery is not None and p.target_soc_pct < battery.min_soc_pct:
                return (
                    f"target_soc_pct ({p.target_soc_pct}%) is below the battery minimum "
                    f"({battery.min_soc_pct}%)."
                )
            if p.max_charge_kw <= 0:
                return f"max_charge_kw must be greater than 0 (got {p.max_charge_kw})."
            if battery is not None and p.max_charge_kw > battery.max_charge_kw:
                return (
                    f"max_charge_kw ({p.max_charge_kw} kW) exceeds the battery maximum "
                    f"({battery.max_charge_kw} kW)."
                )
        if p.mode == "Self Use" and not (0 <= p.min_soc_pct <= 100):
            return f"min_soc_pct must be 0–100 (got {p.min_soc_pct})."

    # Sort by start slot
    sorted_periods = sorted(periods, key=lambda p: _time_to_slot(p.start_time))

    expected_start = _slot_to_time(start_slot)
    if _time_to_slot(sorted_periods[0].start_time) != start_slot:
        return f"Periods must start at {expected_start} to cover the remaining window."

    if _time_to_slot(sorted_periods[-1].end_time) != 48:
        return "Periods must end at 24:00 to cover the full day."

    for i in range(len(sorted_periods) - 1):
        this_end = _time_to_slot(sorted_periods[i].end_time)
        next_start = _time_to_slot(sorted_periods[i + 1].start_time)
        if this_end < next_start:
            return f"Gap between periods ending {sorted_periods[i].end_time} and starting {sorted_periods[i + 1].start_time}."
        if this_end > next_start:
            return f"Periods overlap: {sorted_periods[i].end_time} and {sorted_periods[i + 1].start_time}."

    return None


def simulate(periods: list[UserPeriod], forecast, battery, start_slot: int = 0) -> EvaluationResult:
    """
    Forward-simulate 48 half-hour slots using user-defined periods and forecast data.

    `forecast` must have attributes:
        agile_prices, export_prices, solar_forecast, load_forecast,
        battery_soc_forecast (list[float], 48 items each)
    `battery` must have attributes:
        capacity_kwh, min_soc_kwh, max_charge_kwh_per_slot
    """
    # Build a 48-entry slot → period mapping indexed by absolute slot number.
    # Slots before start_slot are left as None (not simulated).
    sorted_periods = sorted(periods, key=lambda p: _time_to_slot(p.start_time))
    slot_period: list[UserPeriod | None] = [None] * SLOTS
    for p in sorted_periods:
        start = _time_to_slot(p.start_time)
        end = _time_to_slot(p.end_time)
        for s in range(start, end):
            slot_period[s] = p

    simulated_slots = [t for t in range(start_slot, SLOTS) if slot_period[t] is not None]
    if len(simulated_slots) != SLOTS - start_slot:
        raise ValueError(
            f"Periods do not cover all slots from {_slot_to_time(start_slot)} to 24:00 "
            f"({len(simulated_slots)} of {SLOTS - start_slot} slots mapped). "
            "Call validate_periods() before simulate()."
        )

    capacity_kwh = battery.capacity_kwh
    min_soc_kwh = battery.min_soc_kwh

    battery_soc = [0.0] * SLOTS
    grid_import = [0.0] * SLOTS
    grid_export = [0.0] * SLOTS
    charge_mode_slots = [False] * SLOTS

    soc = forecast.battery_soc_forecast[start_slot]  # initial SOC at start_slot

    for t in range(start_slot, SLOTS):
        p = slot_period[t]
        solar = forecast.solar_forecast[t]
        load = forecast.load_forecast[t]
        target_soc_kwh = capacity_kwh * p.target_soc_pct / 100 if p.mode == "Charge" else 0.0
        p_min_soc_kwh = capacity_kwh * p.min_soc_pct / 100 if p.mode == "Self Use" else min_soc_kwh
        max_charge_slot = (p.max_charge_kw / 2) if p.mode == "Charge" else battery.max_charge_kwh_per_slot

        if p.mode == "Charge":
            charge_mode_slots[t] = True
            # Charge battery toward target — no discharge
            charge_headroom = max(0.0, min(target_soc_kwh, capacity_kwh) - soc)
            charge = min(charge_headroom, max_charge_slot)
            # Solar covers load first; remainder offsets grid import for charging
            solar_for_load = min(solar, load)
            solar_surplus = solar - solar_for_load
            load_after_solar = load - solar_for_load
            charge_from_solar = min(solar_surplus, charge)
            charge_from_grid = max(0.0, charge - charge_from_solar)
            solar_exported = max(0.0, solar_surplus - charge_from_solar)
            gi = load_after_solar + charge_from_grid
            ge = solar_exported
            soc = min(soc + charge, capacity_kwh)
        else:
            # Self Use — solar covers load, surplus charges battery or exports
            effective_min_soc = max(min_soc_kwh, p_min_soc_kwh)
            solar_for_load = min(solar, load)
            solar_surplus = solar - solar_for_load
            load_deficit = load - solar_for_load

            # Charge battery from surplus solar
            charge_headroom = max(0.0, capacity_kwh - soc)
            charge = min(solar_surplus, charge_headroom, battery.max_charge_kwh_per_slot)
            solar_after_charge = solar_surplus - charge

            # Export any remaining solar surplus
            ge = max(0.0, solar_after_charge)

            # Discharge battery to cover load deficit
            discharge_available = max(0.0, soc - effective_min_soc)
            discharge = min(load_deficit, discharge_available)
            remaining_deficit = load_deficit - discharge

            # Grid import covers whatever battery can't
            gi = max(0.0, remaining_deficit)

            soc = soc + charge - discharge
            soc = max(effective_min_soc, min(soc, capacity_kwh))

        grid_import[t] = gi
        grid_export[t] = ge
        battery_soc[t] = soc

    estimated_cost_pence = sum(
        grid_import[t] * forecast.agile_prices[t] - grid_export[t] * forecast.export_prices[t]
        for t in range(start_slot, SLOTS)
    )

    return EvaluationResult(
        estimated_cost_gbp=estimated_cost_pence / 100,
        solar_forecast_kwh=sum(forecast.solar_forecast[start_slot:]),
        grid_import_kwh=sum(grid_import[start_slot:]),
        grid_export_kwh=sum(grid_export[start_slot:]),
        battery_soc_forecast=battery_soc,
        grid_import_forecast=grid_import,
        grid_export_forecast=grid_export,
        charge_mode_slots=charge_mode_slots,
        agile_prices=list(forecast.agile_prices),
        export_prices=list(forecast.export_prices),
        solar_forecast=list(forecast.solar_forecast),
    )
