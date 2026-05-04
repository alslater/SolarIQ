# Charging Strategy Algorithm

SolarIQ calculates an optimised battery charging schedule for the following day. The goal is to minimise the net electricity cost across all 48 half-hour slots by deciding when to charge the battery from the grid, when to let solar charge it, and when to discharge it to meet house load.

---

## Inputs

| Input | Source |
|-------|--------|
| 48 half-hourly Agile import prices (p/kWh) | Octopus Energy API, published ~16:00 each day |
| 48 half-hourly Agile export prices (p/kWh) | Octopus Energy API |
| 48 half-hourly solar generation forecast (kWh) | Solcast API |
| 48 half-hourly predicted house load (kWh) | Historical inverter data (see Load Profile below) |
| Battery starting SOC | Current reading from InfluxDB |

---

## Load Profile

The load profile predicts house consumption in each 30-minute slot. It is built by averaging historical inverter data from days with similar conditions.

### Day selection

1. The last **8 same-weekday dates** are gathered as candidates (e.g. for a Friday, the last 8 Fridays).
2. The daily mean temperature for each candidate and for tomorrow is fetched from Open-Meteo (free, no API key required).
3. The **4 candidates with the closest daily mean temperature** to tomorrow's forecast are selected.
4. Their per-slot `usage` values are averaged to form the 48-slot profile.

### Why temperature matters

The house is heated entirely by electric panel heaters. Consumption scales with how far the outside temperature falls below the comfort setpoint — a cold day draws significantly more than a mild one. Temperature-ranked selection produces a more accurate profile than simply taking the most recent same-weekday days.

If the Open-Meteo fetch fails, the 4 most recent same-weekday days are used as a fallback.

---

## Optimisation Model

The core of SolarIQ is a **Mixed Integer Linear Program (MILP)** solved by the CBC solver (via PuLP). It takes roughly 0.2 seconds to solve.

### Decision variables (per slot *t* = 0…47)

| Variable | Description |
|----------|-------------|
| `grid_import[t]` | kWh imported from the grid |
| `grid_export[t]` | kWh exported to the grid (solar overflow only) |
| `battery_charge[t]` | kWh charged into the battery |
| `battery_discharge[t]` | kWh discharged from the battery |
| `battery_soc[t]` | kWh stored in the battery at end of slot |
| `charge_mode[t]` | 1 = Charge period, 0 = Self Use period (binary) |

### Objective

Minimise net electricity cost across all 48 slots:

```
minimise  Σ_t [ grid_import[t] × import_price[t]  −  grid_export[t] × export_price[t] ]
```

The standing charge is fixed and excluded from the optimisation.

When `import_price[t] < 0` (Octopus Agile prices occasionally go negative), the import term becomes a credit, so the optimiser naturally maximises grid import during those slots — charging the battery as fast as possible and meeting house load from the grid rather than the battery.

### Constraints

1. **Energy balance** — every kWh must be accounted for in every slot:
   `grid_import + solar + battery_discharge = load + battery_charge + grid_export`

2. **Battery continuity** — SOC tracks charge and discharge across slots.

3. **Battery bounds** — SOC stays between 2.32 kWh (10 % minimum) and 23.2 kWh (full).

4. **Inverter rate limit** — charge and discharge each capped at 3.75 kWh/slot (7.5 kW × 0.5 h).

5. **No discharge during Charge periods** — when `charge_mode[t] = 1`, the battery holds its charge (SolaX behaviour in Charge mode).

6. **Grid-forced charging only in Charge periods** — grid energy can only flow into the battery during a Charge slot; solar can still charge the battery at any time.

7. **End-of-day SOC ≥ start-of-day SOC** — the battery is not depleted overnight at the expense of tomorrow.

8. **No simultaneous import and export** — `grid_direction[t]` is a binary variable that enforces physical meter reality: a slot is either importing or exporting, never both. Without this constraint the objective is unbounded when import prices are negative, because the solver can inflate both `grid_import` and `grid_export` together by an arbitrary amount while satisfying the energy balance (their *difference* is fixed by the balance, but their individual magnitudes are not). The big-M is `max_charge_rate + peak_load + peak_solar`, a tight physical upper bound on single-slot grid flow.

9. **Peak-window battery reserve (16:00-19:00)** — before the next local 16:00 peak window, the optimiser enforces a battery SOC floor that covers forecast net demand in that window:
   `reserve = Σ_t max(load[t] - solar[t], 0)` for slots in 16:00-19:00,
   then `SOC_before_peak >= min_soc + reserve` (capped by reachable/capacity limits).

---

## Strategy Output

After solving, the per-slot decisions are converted into a displayed plan of contiguous periods. Only **explicit periods** consume one of the inverter's 10 Time-of-Use slots.

Each plan period is one of:

- **Self Use (Default)** — implicit inverter default: Self Use with **Min SOC 10%**. These blocks are shown in the plan but do **not** consume one of the 10 explicit slots.
- **Self Use (Explicit)** — explicitly configured Self Use block with **Min SOC > 10%** when preserving charge is economically beneficial.
- **Charge** — the inverter charges the battery from the grid at up to 7,500 W, targeting a specific SOC percentage by the end of the period.

### Period consolidation

1. Contiguous slots are merged into plan periods.
2. **Midnight split** — any block that would cross the calendar day boundary (23:xx → 00:xx) is split into two periods at `00:00`. This is a hard inverter constraint: a single TOU period cannot span midnight, so a charge window such as 23:00→01:00 must be entered as two separate periods: 23:00→00:00 and 00:00→01:00.
3. Self Use periods at 10% Min SOC are treated as **default/implicit** blocks.
4. Self Use periods above 10% Min SOC are treated as **explicit** blocks.
5. If explicit blocks exceed 10 (the SolaX maximum), the smallest Charge blocks are merged with neighbours until the explicit count fits.
6. Each Charge period specifies a **target SOC %** (rounded to the nearest 5 %) calculated from the battery SOC forecast at the end of that period.

The resulting schedule is displayed in the Charging Strategy page and must be keyed into the SolaX web app manually each evening. Use the **By Start Time** sort toggle to reorder rows chronologically — the natural order to enter them into the inverter.
