from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from solariq.config import SolarIQConfig
from solariq.optimizer.types import StrategyPeriod

SLOTS = 48
MAX_PERIODS = 10
DEFAULT_SELF_USE_MIN_SOC_PCT = 10


def _slot_to_time(slot: int) -> str:
    total_minutes = slot * 30
    h, m = divmod(total_minutes, 60)
    return f"{h:02d}:{m:02d}"


def _round_to_nearest_5(value: float) -> int:
    return round(value / 5) * 5


def build_rolling_window(
    today: list[float],
    tomorrow: list[float],
    current_slot: int,
) -> list[float]:
    """Return a 48-slot window: today[current_slot:] + tomorrow[:current_slot]."""
    return today[current_slot:] + tomorrow[:current_slot]


def current_window_start(tz_name: str) -> tuple[int, datetime]:
    """Return (current_slot_index, window_start_datetime) in local time.

    current_slot is the 30-min slot index for now (0–47).
    window_start is the datetime at which that slot began (seconds/microseconds zeroed).
    """
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    slot = (now.hour * 60 + now.minute) // 30
    slot_hour = (slot * 30) // 60
    slot_minute = (slot * 30) % 60
    window_start = now.replace(hour=slot_hour, minute=slot_minute, second=0, microsecond=0)
    return slot, window_start


def build_strategy_periods(
    charge_mode_slots: list[bool],
    battery_soc_forecast: list[float],
    agile_prices: list[float],
    config: SolarIQConfig,
    window_start: datetime | None = None,
) -> list[StrategyPeriod]:
    """Convert slot decisions into a displayed plan.

    Explicit periods are limited to MAX_PERIODS and include:
    - Charge periods
    - Self Use periods with min SOC > default (10%)

    Self Use periods at default min SOC (10%) are implicit inverter defaults and
    do not consume one of the 10 explicit period slots, but are still included in
    the returned plan for visibility.
    """

    def _slot_time(slot: int) -> str:
        if window_start is not None:
            return (window_start + timedelta(minutes=slot * 30)).strftime("%H:%M")
        return _slot_to_time(slot)

    def _end_sentinel() -> str:
        if window_start is not None:
            return (window_start + timedelta(minutes=SLOTS * 30)).strftime("%H:%M")
        return "23:59"

    # Build raw blocks: list of [start_slot, end_slot_exclusive, is_charge]
    blocks: list[list] = []
    current_mode = charge_mode_slots[0]
    block_start = 0
    for t in range(1, SLOTS):
        if charge_mode_slots[t] != current_mode:
            blocks.append([block_start, t, current_mode])
            current_mode = charge_mode_slots[t]
            block_start = t
    blocks.append([block_start, SLOTS, current_mode])

    def _self_use_min_soc_pct(start: int, end: int) -> int:
        min_soc_kwh = min(battery_soc_forecast[t] for t in range(start, end))
        min_soc_pct = _round_to_nearest_5(min_soc_kwh / config.battery.capacity_kwh * 100)
        return max(DEFAULT_SELF_USE_MIN_SOC_PCT, min(100, min_soc_pct))

    def _build_periods_from_blocks(blocks_in: list[list]) -> list[StrategyPeriod]:
        periods_local: list[StrategyPeriod] = []
        for num, (start, end, is_charge) in enumerate(blocks_in, start=1):
            start_time = _slot_time(start)
            end_time = _end_sentinel() if end == SLOTS else _slot_time(end)

            if is_charge:
                end_soc_kwh = battery_soc_forecast[min(end - 1, SLOTS - 1)]
                target_pct = _round_to_nearest_5(end_soc_kwh / config.battery.capacity_kwh * 100)
                target_pct = max(DEFAULT_SELF_USE_MIN_SOC_PCT, min(100, target_pct))
                avg_price = sum(agile_prices[t] for t in range(start, end)) / (end - start)
                periods_local.append(
                    StrategyPeriod(
                        period_num=num,
                        start_time=start_time,
                        end_time=end_time,
                        mode="Charge",
                        target_soc_pct=target_pct,
                        max_charge_w=int(config.battery.max_charge_kw * 1000),
                        avg_price_p=avg_price,
                        is_default=False,
                    )
                )
            else:
                min_soc_pct = _self_use_min_soc_pct(start, end)
                is_default = min_soc_pct <= DEFAULT_SELF_USE_MIN_SOC_PCT
                periods_local.append(
                    StrategyPeriod(
                        period_num=num,
                        start_time=start_time,
                        end_time=end_time,
                        mode="Self Use",
                        min_soc_pct=DEFAULT_SELF_USE_MIN_SOC_PCT if is_default else min_soc_pct,
                        is_default=is_default,
                    )
                )
        return periods_local

    def _explicit_count(periods_in: list[StrategyPeriod]) -> int:
        return sum(1 for p in periods_in if p.mode == "Charge" or (p.mode == "Self Use" and not p.is_default))

    # Keep only explicit periods within inverter limits by dropping smallest charge blocks first.
    while True:
        periods = _build_periods_from_blocks(blocks)
        if _explicit_count(periods) <= MAX_PERIODS:
            return periods

        charge_blocks = [(i, b) for i, b in enumerate(blocks) if b[2]]
        if not charge_blocks:
            # No charge blocks left to collapse; return best effort plan.
            return periods

        smallest_idx, _ = min(charge_blocks, key=lambda x: x[1][1] - x[1][0])
        blocks.pop(smallest_idx)

        # Merge adjacent self-use blocks after removing a charge block.
        merged: list[list] = []
        for block in blocks:
            if merged and not merged[-1][2] and not block[2]:
                merged[-1][1] = block[1]
            else:
                merged.append(block)
        blocks = merged
