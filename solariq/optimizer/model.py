"""PuLP MILP problem builder for battery charge optimisation."""
from typing import Any

import pulp

SLOTS = 48


def build_problem(
    agile_prices: list[float],
    export_prices: list[float],
    solar: list[float],
    load: list[float],
    initial_soc_kwh: float,
    capacity_kwh: float,
    min_soc_kwh: float,
    max_charge_kwh_per_slot: float,
) -> tuple[pulp.LpProblem, dict[str, Any]]:
    """
    Build the MILP problem. Returns (problem, variables_dict).

    Variables dict keys: grid_import, grid_export, grid_to_battery,
    battery_charge, battery_discharge, battery_soc, charge_mode, grid_direction.
    Each maps to a dict keyed by slot index 0-47.

    Standby mode is NOT a MILP variable; it is inferred post-solve in solver.py.

    Energy balance per slot:
      grid_import[t] + solar[t] + battery_discharge[t]
        = load[t] + battery_charge[t] + grid_export[t]

    battery_charge[t] <= grid_to_battery[t] + solar[t]  (no grid charging in Self Use)
    grid_to_battery[t] <= charge_mode[t] * max_charge_kwh_per_slot
    battery_discharge[t] <= (1 - charge_mode[t]) * max_charge_kwh_per_slot

    grid_direction[t] is a binary that prevents simultaneous import and export.
    This is physically correct (the meter can't do both) and is critical for
    correctness when import prices go negative: without it, the objective is
    unbounded because the solver can inflate both import and export together
    while keeping their difference (fixed by the energy balance) unchanged.
    """
    prob = pulp.LpProblem("battery_charge_optimisation", pulp.LpMinimize)

    M = max_charge_kwh_per_slot

    # Tight big-M for grid flow: the most that can ever flow in one direction in
    # a single 30-min slot is battery charge rate + peak load (import) or
    # battery discharge rate + peak solar (export).
    M_grid = max_charge_kwh_per_slot + max(load) + max(solar) + 0.1

    grid_import = {t: pulp.LpVariable(f"gi_{t}", lowBound=0) for t in range(SLOTS)}
    grid_export = {t: pulp.LpVariable(f"ge_{t}", lowBound=0) for t in range(SLOTS)}
    grid_to_battery = {t: pulp.LpVariable(f"g2b_{t}", lowBound=0) for t in range(SLOTS)}
    battery_charge = {t: pulp.LpVariable(f"bc_{t}", lowBound=0) for t in range(SLOTS)}
    battery_discharge = {t: pulp.LpVariable(f"bd_{t}", lowBound=0) for t in range(SLOTS)}
    battery_soc = {
        t: pulp.LpVariable(f"soc_{t}", lowBound=min_soc_kwh, upBound=capacity_kwh)
        for t in range(SLOTS)
    }
    charge_mode = {t: pulp.LpVariable(f"cm_{t}", cat="Binary") for t in range(SLOTS)}
    # 1 = net importing from grid this slot, 0 = net exporting to grid
    grid_direction = {t: pulp.LpVariable(f"gd_{t}", cat="Binary") for t in range(SLOTS)}

    # Objective: minimise grid import cost minus export revenue.
    # When agile_prices[t] < 0 the import term is negative (a credit), so the
    # solver will maximise import — but only up to what can physically be used
    # or stored, because grid_direction prevents the round-trip arbitrage.
    prob += pulp.lpSum(
        grid_import[t] * agile_prices[t] - grid_export[t] * export_prices[t]
        for t in range(SLOTS)
    )

    for t in range(SLOTS):
        # Energy balance
        prob += (
            grid_import[t] + solar[t] + battery_discharge[t]
            == load[t] + battery_charge[t] + grid_export[t]
        )

        # Battery continuity
        prev_soc = initial_soc_kwh if t == 0 else battery_soc[t - 1]
        prob += battery_soc[t] == prev_soc + battery_charge[t] - battery_discharge[t]

        # Inverter rate limits
        prob += battery_charge[t] <= M
        prob += battery_discharge[t] <= M

        # No discharge during charge periods
        prob += battery_discharge[t] <= (1 - charge_mode[t]) * M

        # Grid-to-battery only in charge periods
        prob += grid_to_battery[t] <= charge_mode[t] * M

        # Battery charge can't exceed what grid+solar provides
        prob += battery_charge[t] <= grid_to_battery[t] + solar[t]

        # grid_to_battery is a subset of battery_charge and grid_import
        prob += grid_to_battery[t] <= battery_charge[t]
        prob += grid_to_battery[t] <= grid_import[t]

        # Prevent simultaneous import and export (physical meter constraint).
        # Without this, when import_price < 0 the model can inflate both
        # grid_import and grid_export together indefinitely (unbounded).
        prob += grid_import[t] <= grid_direction[t] * M_grid
        prob += grid_export[t] <= (1 - grid_direction[t]) * M_grid

    # End-of-day SOC >= start SOC
    prob += battery_soc[SLOTS - 1] >= initial_soc_kwh

    variables = {
        "grid_import": grid_import,
        "grid_export": grid_export,
        "grid_to_battery": grid_to_battery,
        "battery_charge": battery_charge,
        "battery_discharge": battery_discharge,
        "battery_soc": battery_soc,
        "charge_mode": charge_mode,
        "grid_direction": grid_direction,
    }
    return prob, variables
