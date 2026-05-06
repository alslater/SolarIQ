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


def _midnight_slot(window_start: datetime) -> int | None:
    """Return the slot index where the next calendar midnight falls within the window.

    Returns None if midnight does not fall within slots [1, SLOTS-1] (e.g. window
    starts exactly at midnight, or midnight is beyond the 48-slot horizon).
    """
    ws_date = window_start.date()
    midnight = datetime(
        ws_date.year, ws_date.month, ws_date.day,
        tzinfo=window_start.tzinfo,
    ) + timedelta(days=1)
    delta_seconds = (midnight - window_start).total_seconds()
    # window_start is always snapped to a 30-minute boundary, so delta_seconds
    # should be an exact multiple of 1800.  Guard against DST transitions that
    # could shift the wall-clock offset by a non-slot-aligned amount: if the
    # remainder is non-zero, midnight doesn't fall on a slot boundary and we
    # cannot safely split there.
    remainder = delta_seconds % 1800
    if remainder != 0:
        return None
    slot = int(delta_seconds // 1800)
    if 1 <= slot <= SLOTS - 1:
        return slot
    return None


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
    standby_mode_slots: list[bool],
    battery_soc_forecast: list[float],
    agile_prices: list[float],
    export_prices: list[float],
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

    # Build raw blocks: list of [start_slot, end_slot_exclusive, mode_str]
    def _slot_mode(t: int) -> str:
        if charge_mode_slots[t]:
            return "charge"
        if standby_mode_slots[t]:
            return "standby"
        return "self_use"

    blocks: list[list] = []
    current_mode = _slot_mode(0)
    block_start = 0
    for t in range(1, SLOTS):
        m = _slot_mode(t)
        if m != current_mode:
            blocks.append([block_start, t, current_mode])
            current_mode = m
            block_start = t
    blocks.append([block_start, SLOTS, current_mode])

    # Split any block that spans midnight so no period crosses 23:xx → 00:xx.
    # Inverters cannot represent a single period that straddles the day boundary.
    if window_start is not None:
        mid_slot = _midnight_slot(window_start)
        if mid_slot is not None:
            split: list[list] = []
            for block in blocks:
                bstart, bend, bmode = block
                if bstart < mid_slot < bend:
                    split.append([bstart, mid_slot, bmode])
                    split.append([mid_slot, bend, bmode])
                else:
                    split.append(block)
            blocks = split

    def _self_use_min_soc_pct(start: int, end: int) -> int:
        min_soc_kwh = min(battery_soc_forecast[t] for t in range(start, end))
        min_soc_pct = _round_to_nearest_5(min_soc_kwh / config.battery.capacity_kwh * 100)
        return max(DEFAULT_SELF_USE_MIN_SOC_PCT, min(100, min_soc_pct))

    def _build_periods_from_blocks(blocks_in: list[list]) -> list[StrategyPeriod]:
        periods_local: list[StrategyPeriod] = []
        for num, (start, end, mode_str) in enumerate(blocks_in, start=1):
            start_time = _slot_time(start)
            end_time = _end_sentinel() if end == SLOTS else _slot_time(end)

            if mode_str == "charge":
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
            elif mode_str == "standby":
                avg_export = sum(export_prices[t] for t in range(start, end)) / (end - start)
                periods_local.append(
                    StrategyPeriod(
                        period_num=num,
                        start_time=start_time,
                        end_time=end_time,
                        mode="Battery Standby",
                        avg_price_p=avg_export,
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
        return sum(
            1 for p in periods_in
            if p.mode in ("Charge", "Battery Standby") or (p.mode == "Self Use" and not p.is_default)
        )

    # Keep only explicit periods within inverter limits by dropping smallest standby then charge blocks.
    while True:
        periods = _build_periods_from_blocks(blocks)
        if _explicit_count(periods) <= MAX_PERIODS:
            return periods

        # Collapse smallest standby blocks first, then smallest charge blocks.
        standby_blocks = [(i, b) for i, b in enumerate(blocks) if b[2] == "standby"]
        charge_blocks = [(i, b) for i, b in enumerate(blocks) if b[2] == "charge"]

        candidates = standby_blocks if standby_blocks else charge_blocks
        if not candidates:
            return periods

        smallest_idx, _ = min(candidates, key=lambda x: x[1][1] - x[1][0])
        blocks.pop(smallest_idx)

        # Merge adjacent self-use blocks after removing a block.
        merged: list[list] = []
        for block in blocks:
            if merged and merged[-1][2] == "self_use" and block[2] == "self_use":
                merged[-1][1] = block[1]
            else:
                merged.append(block)
        blocks = merged
