from solariq.config import SolarIQConfig
from solariq.optimizer.types import StrategyPeriod

SLOTS = 48
MAX_PERIODS = 10


def _slot_to_time(slot: int) -> str:
    total_minutes = slot * 30
    h, m = divmod(total_minutes, 60)
    return f"{h:02d}:{m:02d}"


def _round_to_nearest_5(value: float) -> int:
    return round(value / 5) * 5


def build_strategy_periods(
    charge_mode_slots: list[bool],
    battery_soc_forecast: list[float],
    agile_prices: list[float],
    config: SolarIQConfig,
) -> list[StrategyPeriod]:
    """Convert per-slot charge_mode decisions into ≤10 SolaX time periods."""

    # Build raw blocks: list of [start_slot, end_slot_exclusive, is_charge]
    blocks: list[list] = []
    if not any(charge_mode_slots):
        blocks = [[0, SLOTS, False]]
    else:
        current_mode = charge_mode_slots[0]
        block_start = 0
        for t in range(1, SLOTS):
            if charge_mode_slots[t] != current_mode:
                blocks.append([block_start, t, current_mode])
                current_mode = charge_mode_slots[t]
                block_start = t
        blocks.append([block_start, SLOTS, current_mode])

    # If over MAX_PERIODS, merge smallest charge blocks into adjacent self-use periods
    while len(blocks) > MAX_PERIODS:
        charge_blocks = [(i, b) for i, b in enumerate(blocks) if b[2]]
        if not charge_blocks:
            break
        # Remove the smallest charge block (fewest slots)
        smallest_idx, _ = min(charge_blocks, key=lambda x: x[1][1] - x[1][0])
        blocks.pop(smallest_idx)
        # Merge adjacent self-use blocks
        merged: list[list] = []
        for block in blocks:
            if merged and not merged[-1][2] and not block[2]:
                merged[-1][1] = block[1]  # extend end
            else:
                merged.append(block)
        blocks = merged

    periods: list[StrategyPeriod] = []
    for num, (start, end, is_charge) in enumerate(blocks, start=1):
        start_time = _slot_to_time(start)
        end_time = "23:59" if end == SLOTS else _slot_to_time(end)

        if is_charge:
            end_soc_kwh = battery_soc_forecast[min(end - 1, SLOTS - 1)]
            target_pct = _round_to_nearest_5(end_soc_kwh / config.battery.capacity_kwh * 100)
            target_pct = max(config.battery.min_soc_pct, min(100, target_pct))
            avg_price = sum(agile_prices[t] for t in range(start, end)) / (end - start)
            period = StrategyPeriod(
                period_num=num,
                start_time=start_time,
                end_time=end_time,
                mode="Charge",
                target_soc_pct=target_pct,
                max_charge_w=int(config.battery.max_charge_kw * 1000),
                avg_price_p=avg_price,
            )
        else:
            period = StrategyPeriod(
                period_num=num,
                start_time=start_time,
                end_time=end_time,
                mode="Self Use",
                min_soc_pct=config.battery.min_soc_pct,
            )
        periods.append(period)

    return periods
