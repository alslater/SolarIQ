from datetime import datetime, timedelta, timezone

import pulp

from solariq.config import SolarIQConfig
from solariq.optimizer.model import build_problem, SLOTS
from solariq.optimizer.types import OptimizationResult, StrategyPeriod


def _next_peak_window_slots(window_start: datetime) -> list[int]:
    """Return slot indexes for the next local 16:00-19:00 window within horizon."""
    peak_start = window_start.replace(hour=16, minute=0, second=0, microsecond=0)
    if peak_start < window_start:
        peak_start += timedelta(days=1)
    peak_end = peak_start + timedelta(hours=3)

    slots: list[int] = []
    for t in range(SLOTS):
        slot_dt = window_start + timedelta(minutes=t * 30)
        if peak_start <= slot_dt < peak_end:
            slots.append(t)
    return slots


def solve(
    agile_prices: list[float],
    export_prices: list[float],
    solar: list[float],
    load: list[float],
    initial_soc_kwh: float,
    config: SolarIQConfig,
    window_start: datetime,
) -> OptimizationResult:
    prob, variables = build_problem(
        agile_prices=agile_prices,
        export_prices=export_prices,
        solar=solar,
        load=load,
        initial_soc_kwh=initial_soc_kwh,
        capacity_kwh=config.battery.capacity_kwh,
        min_soc_kwh=config.battery.min_soc_kwh,
        max_charge_kwh_per_slot=config.battery.max_charge_kwh_per_slot,
    )

    # Reserve enough battery before the next 16:00-19:00 peak window to cover
    # expected net demand in that window (load minus solar, floored at zero).
    peak_slots = _next_peak_window_slots(window_start)
    if peak_slots:
        peak_start_slot = peak_slots[0]
        if peak_start_slot > 0:
            expected_peak_demand_kwh = sum(max(load[t] - solar[t], 0.0) for t in peak_slots)
            usable_capacity_kwh = max(0.0, config.battery.capacity_kwh - config.battery.min_soc_kwh)
            reserve_kwh = min(expected_peak_demand_kwh, usable_capacity_kwh)
            required_soc_kwh = config.battery.min_soc_kwh + reserve_kwh

            # Keep the target reachable with available pre-peak charging headroom.
            max_reachable_soc_kwh = min(
                config.battery.capacity_kwh,
                initial_soc_kwh + peak_start_slot * config.battery.max_charge_kwh_per_slot,
            )
            required_soc_kwh = min(required_soc_kwh, max_reachable_soc_kwh)

            prob += variables["battery_soc"][peak_start_slot - 1] >= required_soc_kwh

    solver = pulp.PULP_CBC_CMD(msg=0)
    prob.solve(solver)

    if prob.status != pulp.LpStatusOptimal:
        raise RuntimeError(f"Optimisation failed: {pulp.LpStatus[prob.status]}")

    def val(v) -> float:
        return pulp.value(v) or 0.0

    battery_soc_forecast = [val(variables["battery_soc"][t]) for t in range(SLOTS)]
    grid_import_forecast = [val(variables["grid_import"][t]) for t in range(SLOTS)]
    charge_mode_slots = [bool(round(val(variables["charge_mode"][t]))) for t in range(SLOTS)]

    estimated_cost_pence = sum(
        grid_import_forecast[t] * agile_prices[t]
        - val(variables["grid_export"][t]) * export_prices[t]
        for t in range(SLOTS)
    )

    from solariq.optimizer.strategy import build_strategy_periods

    periods = build_strategy_periods(
        charge_mode_slots=charge_mode_slots,
        battery_soc_forecast=battery_soc_forecast,
        agile_prices=agile_prices,
        config=config,
        window_start=window_start,
    )

    valid_until = window_start + timedelta(hours=24)

    return OptimizationResult(
        periods=periods,
        estimated_cost_gbp=estimated_cost_pence / 100,
        solar_forecast_kwh=sum(solar),
        grid_import_kwh=sum(grid_import_forecast),
        computed_at=datetime.now(timezone.utc).isoformat(),
        valid_until=valid_until.isoformat(),
        window_start=window_start.isoformat(),
        agile_prices=agile_prices,
        export_prices=export_prices,
        solar_forecast=solar,
        load_forecast=load,
        battery_soc_forecast=battery_soc_forecast,
        grid_import_forecast=grid_import_forecast,
        charge_mode_slots=charge_mode_slots,
    )
