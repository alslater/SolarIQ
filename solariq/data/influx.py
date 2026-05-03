import logging
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from influxdb import InfluxDBClient

from solariq.config import SolarIQConfig
from solariq.data.octopus import fetch_agile_prices
from solariq.optimizer.types import TodayLiveData

logger = logging.getLogger(__name__)

SLOTS = 48
SLOT_MINUTES = 30


def _slot_timestamps() -> list[str]:
    result = []
    for slot in range(SLOTS):
        h = (slot * SLOT_MINUTES) // 60
        m = (slot * SLOT_MINUTES) % 60
        result.append(f"{h:02d}:{m:02d}")
    return result


def _local_day_utc_bounds(day: date, tz_name: str) -> tuple[str, str]:
    tz = ZoneInfo(tz_name)
    start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=tz)
    end = datetime(day.year, day.month, day.day, 23, 30, tzinfo=tz)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (
        start.astimezone(timezone.utc).strftime(fmt),
        end.astimezone(timezone.utc).strftime(fmt),
    )


def query_solar_electricity_range(
    config: SolarIQConfig, from_utc: str, to_utc: str
) -> list[dict]:
    """Query octograph solar_electricity measurement — used for load profile history."""
    logger.debug(
        "query solar_electricity %s → %s (db=%s)", from_utc, to_utc, config.influxdb.solar_database
    )
    client = InfluxDBClient(
        host=config.influxdb.host,
        port=config.influxdb.port,
        database=config.influxdb.solar_database,
    )
    result = client.query(
        f"SELECT time, actual_usage, solar_generation, battery_charge, "
        f"consumption, agile_rate, agile_cost "
        f"FROM solar_electricity "
        f"WHERE time >= '{from_utc}' AND time <= '{to_utc}' "
        f"ORDER BY time ASC"
    )
    points = list(result.get_points())
    logger.debug("solar_electricity returned %d points", len(points))
    return points


def query_solax_usage_day(
    config: SolarIQConfig, target_date: date
) -> list[float]:
    """Return 48-slot usage profile (kWh/slot) for target_date from solaxdata.

    Uses MEAN(usage) per 30-min bucket (usage is in kW, × 0.5 h = kWh).
    Returns a list of 48 zeros if the date has no data.
    """
    from_utc, to_utc = _local_day_utc_bounds(target_date, config.app.timezone)
    tz = ZoneInfo(config.app.timezone)
    logger.debug("query solaxdata usage for %s (%s → %s)", target_date, from_utc, to_utc)
    client = InfluxDBClient(
        host=config.influxdb.host,
        port=config.influxdb.port,
        database=config.influxdb.solax_database,
    )
    result = client.query(
        f"SELECT MEAN(usage) AS usage "
        f"FROM solaxdata "
        f"WHERE time >= '{from_utc}' AND time <= '{to_utc}' "
        f"GROUP BY time(30m) fill(0)"
    )
    slots = [0.0] * SLOTS
    for point in result.get_points():
        t_utc = datetime.fromisoformat(point["time"].replace("Z", "+00:00"))
        t_local = t_utc.astimezone(tz)
        if t_local.date() != target_date:
            continue
        slot = (t_local.hour * 60 + t_local.minute) // 30
        if 0 <= slot < SLOTS:
            slots[slot] = float(point.get("usage") or 0.0) * 0.5  # kW × 0.5 h = kWh
    return slots


def _query_solax_slots(
    config: SolarIQConfig, from_utc: str, to_utc: str
) -> list[dict]:
    """Query solaxdata aggregated to 30-min slots."""
    logger.info(
        "query solaxdata %s → %s (db=%s)", from_utc, to_utc, config.influxdb.solax_database
    )
    client = InfluxDBClient(
        host=config.influxdb.host,
        port=config.influxdb.port,
        database=config.influxdb.solax_database,
    )
    result = client.query(
        f"SELECT MEAN(pvpower) AS pvpower, MEAN(power_in) AS power_in, "
        f"MEAN(power_out) AS power_out, LAST(soc) AS soc "
        f"FROM solaxdata "
        f"WHERE time >= '{from_utc}' AND time <= '{to_utc}' "
        f"GROUP BY time(30m) fill(none)"
    )
    points = list(result.get_points())
    logger.info("solaxdata returned %d aggregated slots", len(points))
    return points


def get_today_live_data(
    config: SolarIQConfig,
    today: date | None = None,
) -> TodayLiveData:
    if today is None:
        tz = ZoneInfo(config.app.timezone)
        today = datetime.now(tz).date()

    logger.info("fetching today live data for %s", today)
    from_utc, to_utc = _local_day_utc_bounds(today, config.app.timezone)
    tz = ZoneInfo(config.app.timezone)

    solax_points = _query_solax_slots(config, from_utc, to_utc)

    from solariq.cache import load_today_rates, save_today_rates
    from solariq.data.octopus import fetch_export_prices
    today_str = today.isoformat()
    cached = load_today_rates(today_str)
    if cached:
        agile_prices, export_prices = cached
        logger.debug("using cached agile rates for %s", today_str)
    else:
        agile_prices = fetch_agile_prices(config, today)
        export_prices = fetch_export_prices(config, today)
        try:
            save_today_rates(agile_prices, export_prices, today_str)
        except Exception as exc:
            logger.warning("failed to cache today's rates: %s", exc)

    timestamps = _slot_timestamps()
    actual_solar: list[float | None] = [None] * SLOTS
    actual_grid_import: list[float | None] = [None] * SLOTS
    actual_grid_export: list[float | None] = [None] * SLOTS
    actual_battery_soc_kwh: list[float | None] = [None] * SLOTS

    last_data_slot = -1
    battery_soc_pct = 0.0

    for point in solax_points:
        t_str = point["time"]
        t_utc = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
        t_local = t_utc.astimezone(tz)
        if t_local.date() != today:
            continue
        slot = (t_local.hour * 60 + t_local.minute) // 30
        if not 0 <= slot < SLOTS:
            continue

        pvpower = float(point.get("pvpower") or 0.0)
        power_in = float(point.get("power_in") or 0.0)
        power_out = float(point.get("power_out") or 0.0)
        soc = point.get("soc")

        actual_solar[slot] = pvpower * 0.5       # mean kW × 0.5 h = kWh
        actual_grid_import[slot] = power_in * 0.5
        actual_grid_export[slot] = power_out * 0.5
        if soc is not None:
            actual_battery_soc_kwh[slot] = float(soc) / 100 * config.battery.capacity_kwh
            battery_soc_pct = float(soc)
        last_data_slot = max(last_data_slot, slot)

    solar_today_kwh = sum(v for v in actual_solar if v is not None)
    battery_soc_kwh = battery_soc_pct / 100 * config.battery.capacity_kwh

    # Cost = grid import × agile price for each completed slot
    grid_cost_pence = sum(
        (actual_grid_import[i] or 0.0) * agile_prices[i]
        for i in range(last_data_slot + 1)
    ) if last_data_slot >= 0 else 0.0

    # Revenue = grid export × export price for each completed slot
    grid_export_revenue_pence = sum(
        (actual_grid_export[i] or 0.0) * export_prices[i]
        for i in range(last_data_slot + 1)
    ) if last_data_slot >= 0 else 0.0

    current_rate_p = agile_prices[last_data_slot] if last_data_slot >= 0 else 0.0
    current_export_rate_p = export_prices[last_data_slot] if last_data_slot >= 0 else 0.0

    grid_export_today_kwh = sum(v for v in actual_grid_export if v is not None)
    logger.info(
        "today result: last_slot=%d, battery=%.1f%%, solar=%.2f kWh, export=%.2f kWh, grid_cost=%.1fp, export_revenue=%.1fp",
        last_data_slot, battery_soc_pct, solar_today_kwh, grid_export_today_kwh,
        grid_cost_pence, grid_export_revenue_pence,
    )

    return TodayLiveData(
        battery_soc_kwh=battery_soc_kwh,
        battery_soc_pct=battery_soc_pct,
        solar_today_kwh=solar_today_kwh,
        grid_cost_pence=grid_cost_pence,
        grid_export_revenue_pence=grid_export_revenue_pence,
        current_rate_p=current_rate_p,
        current_export_rate_p=current_export_rate_p,
        last_data_slot=last_data_slot,
        timestamps=timestamps,
        actual_usage=[None] * SLOTS,
        actual_solar=actual_solar,
        actual_battery_soc_kwh=actual_battery_soc_kwh,
        actual_grid_import=actual_grid_import,
        actual_grid_export=actual_grid_export,
        agile_prices=agile_prices,
        export_prices=export_prices,
        predicted_usage=[0.0] * SLOTS,
    )


def get_historical_range_data(
    config: SolarIQConfig, start_date: date, end_date: date
) -> list[dict]:
    """Return per-bucket energy data for start_date..end_date inclusive.

    Buckets are hourly for ranges ≤7 days, daily otherwise.
    Each row: {date, solar_kwh, grid_import_kwh, grid_export_kwh, grid_cost_gbp, grid_export_revenue_gbp}
    """
    from datetime import timedelta

    tz = ZoneInfo(config.app.timezone)
    from_utc, _ = _local_day_utc_bounds(start_date, config.app.timezone)
    _, to_utc = _local_day_utc_bounds(end_date, config.app.timezone)

    delta_days = (end_date - start_date).days + 1
    use_hourly = delta_days <= 7

    logger.info(
        "historical range query: %s → %s (%s → %s), bucket=%s",
        start_date, end_date, from_utc, to_utc, "hourly" if use_hourly else "daily",
    )

    client = InfluxDBClient(
        host=config.influxdb.host,
        port=config.influxdb.port,
        database=config.influxdb.solax_database,
    )
    result = client.query(
        f"SELECT MEAN(pvpower) AS pvpower, MEAN(power_in) AS power_in, MEAN(power_out) AS power_out "
        f"FROM solaxdata "
        f"WHERE time >= '{from_utc}' AND time <= '{to_utc}' "
        f"GROUP BY time(30m) fill(none)"
    )

    # Aggregate 30-min slots into buckets; also accumulate raw slot data for cost calculation
    # Bucket key: (date, hour) for hourly, (date,) for daily
    energy_buckets: dict[tuple, dict] = {}
    # slot_entries: list of (date, slot_index, import_kwh, export_kwh) for cost join
    slot_entries: list[tuple] = []

    for point in result.get_points():
        t_utc = datetime.fromisoformat(point["time"].replace("Z", "+00:00"))
        t_local = t_utc.astimezone(tz)
        d = t_local.date()
        if d < start_date or d > end_date:
            continue

        solar_kwh = float(point.get("pvpower") or 0.0) * 0.5
        import_kwh = float(point.get("power_in") or 0.0) * 0.5
        export_kwh = float(point.get("power_out") or 0.0) * 0.5
        slot = (t_local.hour * 60 + t_local.minute) // 30

        key = (d, t_local.hour) if use_hourly else (d,)
        if key not in energy_buckets:
            energy_buckets[key] = {"solar_kwh": 0.0, "grid_import_kwh": 0.0, "grid_export_kwh": 0.0}
        energy_buckets[key]["solar_kwh"] += solar_kwh
        energy_buckets[key]["grid_import_kwh"] += import_kwh
        energy_buckets[key]["grid_export_kwh"] += export_kwh
        slot_entries.append((d, slot, import_kwh, export_kwh))

    # Fetch agile import and export rates from energy.electricity
    import_rate_map: dict[tuple[date, int], float] = {}
    export_rate_map: dict[tuple[date, int], float] = {}
    agile_client = InfluxDBClient(
        host=config.influxdb.host,
        port=config.influxdb.port,
        database=config.influxdb.database,
    )
    try:
        rate_result = agile_client.query(
            f"SELECT agile_rate, export_rate "
            f"FROM electricity "
            f"WHERE time >= '{from_utc}' AND time <= '{to_utc}' "
            f"ORDER BY time ASC"
        )
        for point in rate_result.get_points():
            t_utc = datetime.fromisoformat(point["time"].replace("Z", "+00:00"))
            t_local = t_utc.astimezone(tz)
            d = t_local.date()
            slot = (t_local.hour * 60 + t_local.minute) // 30
            import_rate_map[(d, slot)] = float(point.get("agile_rate") or 0.0)
            export_rate_map[(d, slot)] = float(point.get("export_rate") or 0.0)
        logger.debug("rate map: %d import slots, %d export slots", len(import_rate_map), len(export_rate_map))
    except Exception as exc:
        logger.warning("agile rate query failed for history: %s", exc)

    # Compute import cost and export revenue per bucket
    cost_buckets: dict[tuple, float] = {}
    revenue_buckets: dict[tuple, float] = {}
    for d, slot, import_kwh, export_kwh in slot_entries:
        key = (d, slot // 2) if use_hourly else (d,)
        cost_buckets[key] = cost_buckets.get(key, 0.0) + import_kwh * import_rate_map.get((d, slot), 0.0)
        revenue_buckets[key] = revenue_buckets.get(key, 0.0) + export_kwh * export_rate_map.get((d, slot), 0.0)

    # Build output rows covering every bucket in the range
    prec = 3 if use_hourly else 2
    rows = []
    cursor = start_date
    while cursor <= end_date:
        if use_hourly:
            for h in range(24):
                key = (cursor, h)
                label = f"{h:02d}:00" if delta_days == 1 else f"{cursor.strftime('%d %b')} {h:02d}:00"
                bucket = energy_buckets.get(key, {"solar_kwh": 0.0, "grid_import_kwh": 0.0, "grid_export_kwh": 0.0})
                rows.append({
                    "date": label,
                    "solar_kwh": round(bucket["solar_kwh"], prec),
                    "grid_import_kwh": round(bucket["grid_import_kwh"], prec),
                    "grid_export_kwh": round(bucket["grid_export_kwh"], prec),
                    "grid_cost_gbp": round(cost_buckets.get(key, 0.0) / 100, prec),
                    "grid_export_revenue_gbp": round(revenue_buckets.get(key, 0.0) / 100, prec),
                })
        else:
            key = (cursor,)
            bucket = energy_buckets.get(key, {"solar_kwh": 0.0, "grid_import_kwh": 0.0, "grid_export_kwh": 0.0})
            rows.append({
                "date": cursor.strftime("%d %b"),
                "solar_kwh": round(bucket["solar_kwh"], prec),
                "grid_import_kwh": round(bucket["grid_import_kwh"], prec),
                "grid_export_kwh": round(bucket["grid_export_kwh"], prec),
                "grid_cost_gbp": round(cost_buckets.get(key, 0.0) / 100, prec),
                "grid_export_revenue_gbp": round(revenue_buckets.get(key, 0.0) / 100, prec),
            })
        cursor += timedelta(days=1)

    logger.info(
        "historical range: %d %s buckets, %d with solar data",
        len(rows), "hourly" if use_hourly else "daily",
        sum(1 for r in rows if r["solar_kwh"] > 0),
    )
    return rows


def get_latest_inverter_stats(config: SolarIQConfig) -> dict | None:
    """Return the most recent solaxdata record as a flat dict of current inverter values.

    Returns None if the measurement is empty or the query fails.
    Fields (all floats unless noted):
      pvpower_kw, feedin_kw, power_in_kw, power_out_kw, battery_power_kw,
      usage_kw, soc_pct, battery_temp_c, inverter_temp_c, grid_voltage_v,
      recorded_at (ISO string)
    """
    client = InfluxDBClient(
        host=config.influxdb.host,
        port=config.influxdb.port,
        database=config.influxdb.solax_database,
    )
    try:
        result = client.query(
            "SELECT LAST(pvpower) AS pvpower, LAST(feedin) AS feedin, "
            "LAST(power_in) AS power_in, LAST(power_out) AS power_out, "
            "LAST(battery_power) AS battery_power, LAST(usage) AS usage, "
            "LAST(soc) AS soc, LAST(battery_temp) AS battery_temp, "
            "LAST(inverter_temp) AS inverter_temp, LAST(grid_voltage) AS grid_voltage "
            "FROM solaxdata"
        )
        points = list(result.get_points())
        if not points:
            return None
        p = points[0]
        return {
            "pvpower_kw": round(float(p.get("pvpower") or 0.0), 3),
            "feedin_kw": round(float(p.get("feedin") or 0.0), 3),
            "power_in_kw": round(float(p.get("power_in") or 0.0), 3),
            "power_out_kw": round(float(p.get("power_out") or 0.0), 3),
            "battery_power_kw": round(float(p.get("battery_power") or 0.0), 3),
            "usage_kw": round(float(p.get("usage") or 0.0), 3),
            "soc_pct": round(float(p.get("soc") or 0.0), 1),
            "battery_temp_c": round(float(p.get("battery_temp") or 0.0), 1),
            "inverter_temp_c": round(float(p.get("inverter_temp") or 0.0), 1),
            "grid_voltage_v": round(float(p.get("grid_voltage") or 0.0), 1),
            "recorded_at": p.get("time", ""),
        }
    except Exception as exc:
        logger.warning("get_latest_inverter_stats failed: %s", exc)
        return None
