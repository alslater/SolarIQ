from datetime import datetime, timezone

import pulp

from solariq.config import SolarIQConfig
from solariq.optimizer.model import build_problem, SLOTS
from solariq.optimizer.types import OptimizationResult, StrategyPeriod


def solve(
    agile_prices: list[float],
    export_prices: list[float],
    solar: list[float],
    load: list[float],
    initial_soc_kwh: float,
    config: SolarIQConfig,
    target_date: str = "",
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
    )

    return OptimizationResult(
        periods=periods,
        estimated_cost_gbp=estimated_cost_pence / 100,
        solar_forecast_kwh=sum(solar),
        grid_import_kwh=sum(grid_import_forecast),
        computed_at=datetime.now(timezone.utc).isoformat(),
        target_date=target_date,
        agile_prices=agile_prices,
        export_prices=export_prices,
        solar_forecast=solar,
        load_forecast=load,
        battery_soc_forecast=battery_soc_forecast,
        grid_import_forecast=grid_import_forecast,
        charge_mode_slots=charge_mode_slots,
    )
