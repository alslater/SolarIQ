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
    from datetime import timedelta
    tz = ZoneInfo(tz_name)
    start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=tz)
    end = start + timedelta(days=1)
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
        f"MEAN(power_out) AS power_out, MEAN(usage) AS usage, LAST(soc) AS soc "
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
    actual_usage: list[float | None] = [None] * SLOTS
    actual_solar: list[float | None] = [None] * SLOTS
    actual_grid_import: list[float | None] = [None] * SLOTS
    actual_grid_export: list[float | None] = [None] * SLOTS
    actual_battery_soc_kwh: list[float | None] = [None] * SLOTS

    last_data_slot = -1
    battery_soc_pct = 0.0

    now_local = datetime.now(tz)
    current_slot = (now_local.hour * 60 + now_local.minute) // 30
    # Minutes elapsed so far within the current in-progress slot (1..30)
    elapsed_minutes = (now_local.hour * 60 + now_local.minute) % 30 or 30

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
        usage = point.get("usage")
        soc = point.get("soc")

        # For the current in-progress slot use elapsed time so the bar shows
        # actual energy accumulated so far rather than a full-slot extrapolation.
        hours = elapsed_minutes / 60 if slot == current_slot else 0.5

        actual_solar[slot] = pvpower * hours
        actual_grid_import[slot] = power_in * hours
        actual_grid_export[slot] = power_out * hours
        if usage is not None:
            actual_usage[slot] = float(usage) * hours
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
        actual_usage=actual_usage,
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
    Each row: {date, solar_kwh, predicted_solar_kwh, grid_import_kwh, grid_export_kwh, grid_cost_gbp, grid_export_revenue_gbp}
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
        f"SELECT MEAN(pvpower) AS pvpower, MEAN(power_in) AS power_in, "
        f"MEAN(power_out) AS power_out, MEAN(battery_power) AS battery_power "
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
        battery_power_kw = float(point.get("battery_power") or 0.0)
        slot = (t_local.hour * 60 + t_local.minute) // 30

        key = (d, t_local.hour) if use_hourly else (d,)
        if key not in energy_buckets:
            energy_buckets[key] = {"solar_kwh": 0.0, "grid_import_kwh": 0.0, "grid_export_kwh": 0.0}
        energy_buckets[key]["solar_kwh"] += solar_kwh
        energy_buckets[key]["grid_import_kwh"] += import_kwh
        energy_buckets[key]["grid_export_kwh"] += export_kwh
        slot_entries.append((d, slot, import_kwh, export_kwh, solar_kwh, battery_power_kw))

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

    # Compute import cost, export revenue, solar saving, and battery peak saving per bucket
    cost_buckets: dict[tuple, float] = {}
    revenue_buckets: dict[tuple, float] = {}
    solar_saving_buckets: dict[tuple, float] = {}
    battery_peak_saving_buckets: dict[tuple, float] = {}
    import_rate_sum_buckets: dict[tuple, float] = {}
    import_rate_count_buckets: dict[tuple, int] = {}
    export_rate_sum_buckets: dict[tuple, float] = {}
    export_rate_count_buckets: dict[tuple, int] = {}
    for d, slot, import_kwh, export_kwh, solar_kwh, battery_power_kw in slot_entries:
        key = (d, slot // 2) if use_hourly else (d,)
        cost_buckets[key] = cost_buckets.get(key, 0.0) + import_kwh * import_rate_map.get((d, slot), 0.0)
        revenue_buckets[key] = revenue_buckets.get(key, 0.0) + export_kwh * export_rate_map.get((d, slot), 0.0)
        if (d, slot) in import_rate_map:
            import_rate_sum_buckets[key] = import_rate_sum_buckets.get(key, 0.0) + import_rate_map[(d, slot)]
            import_rate_count_buckets[key] = import_rate_count_buckets.get(key, 0) + 1
        if (d, slot) in export_rate_map:
            export_rate_sum_buckets[key] = export_rate_sum_buckets.get(key, 0.0) + export_rate_map[(d, slot)]
            export_rate_count_buckets[key] = export_rate_count_buckets.get(key, 0) + 1
        solar_saving_buckets[key] = solar_saving_buckets.get(key, 0.0) + solar_kwh * import_rate_map.get((d, slot), 0.0)
        local_hour = slot // 2
        if 16 <= local_hour <= 18:
            battery_discharge_kwh = max(0.0, -battery_power_kw) * 0.5
            battery_to_load_kwh = max(0.0, battery_discharge_kwh - export_kwh)
            battery_peak_saving_buckets[key] = (
                battery_peak_saving_buckets.get(key, 0.0)
                + battery_to_load_kwh * import_rate_map.get((d, slot), 0.0)
            )

    # Fetch forecast data from both providers and aggregate to the same buckets.
    predicted_solcast_buckets: dict[tuple, float] = {}
    predicted_forecast_solar_buckets: dict[tuple, float] = {}
    forecast_sources = [
        ("solcast", config.influxdb.solcast_forecast_database, predicted_solcast_buckets),
        ("forecast_solar", config.influxdb.forecast_solar_forecast_database, predicted_forecast_solar_buckets),
    ]
    for source_name, database_name, bucket_map in forecast_sources:
        source_client = InfluxDBClient(
            host=config.influxdb.host,
            port=config.influxdb.port,
            database=database_name,
        )
        try:
            forecast_result = source_client.query(
                f"SELECT pv_estimate_kwh "
                f"FROM solar_forecast "
                f"WHERE time >= '{from_utc}' AND time <= '{to_utc}' "
                f"ORDER BY time ASC"
            )
            for point in forecast_result.get_points():
                t_utc = datetime.fromisoformat(point["time"].replace("Z", "+00:00"))
                t_local = t_utc.astimezone(tz)
                d = t_local.date()
                if d < start_date or d > end_date:
                    continue
                key = (d, t_local.hour) if use_hourly else (d,)
                bucket_map[key] = bucket_map.get(key, 0.0) + float(point.get("pv_estimate_kwh") or 0.0)
        except Exception as exc:
            logger.warning("%s forecast query failed for history: %s", source_name, exc)

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
                predicted_solcast = predicted_solcast_buckets.get(key, 0.0)
                predicted_forecast_solar = predicted_forecast_solar_buckets.get(key, 0.0)
                predicted_default = (
                    predicted_solcast
                    if key in predicted_solcast_buckets
                    else predicted_forecast_solar
                )
                rows.append({
                    "date": label,
                    "solar_kwh": round(bucket["solar_kwh"], prec),
                    "predicted_solar_kwh": round(predicted_default, prec),
                    "predicted_solar_solcast_kwh": round(predicted_solcast, prec),
                    "predicted_solar_forecast_solar_kwh": round(predicted_forecast_solar, prec),
                    "grid_import_kwh": round(bucket["grid_import_kwh"], prec),
                    "grid_export_kwh": round(bucket["grid_export_kwh"], prec),
                    "grid_cost_gbp": round(cost_buckets.get(key, 0.0) / 100, prec),
                    "grid_export_revenue_gbp": round(revenue_buckets.get(key, 0.0) / 100, prec),
                    "solar_saving_gbp": round(solar_saving_buckets.get(key, 0.0) / 100, prec),
                    "battery_peak_saving_gbp": round(battery_peak_saving_buckets.get(key, 0.0) / 100, prec),
                    "avg_import_rate_p": round(
                        import_rate_sum_buckets[key] / import_rate_count_buckets[key], prec
                    ) if import_rate_count_buckets.get(key, 0) > 0 else None,
                    "avg_export_rate_p": round(
                        export_rate_sum_buckets[key] / export_rate_count_buckets[key], prec
                    ) if export_rate_count_buckets.get(key, 0) > 0 else None,
                })
        else:
            key = (cursor,)
            bucket = energy_buckets.get(key, {"solar_kwh": 0.0, "grid_import_kwh": 0.0, "grid_export_kwh": 0.0})
            predicted_solcast = predicted_solcast_buckets.get(key, 0.0)
            predicted_forecast_solar = predicted_forecast_solar_buckets.get(key, 0.0)
            predicted_default = (
                predicted_solcast
                if key in predicted_solcast_buckets
                else predicted_forecast_solar
            )
            rows.append({
                "date": cursor.strftime("%d %b"),
                "solar_kwh": round(bucket["solar_kwh"], prec),
                "predicted_solar_kwh": round(predicted_default, prec),
                "predicted_solar_solcast_kwh": round(predicted_solcast, prec),
                "predicted_solar_forecast_solar_kwh": round(predicted_forecast_solar, prec),
                "grid_import_kwh": round(bucket["grid_import_kwh"], prec),
                "grid_export_kwh": round(bucket["grid_export_kwh"], prec),
                "grid_cost_gbp": round(cost_buckets.get(key, 0.0) / 100, prec),
                "grid_export_revenue_gbp": round(revenue_buckets.get(key, 0.0) / 100, prec),
                "solar_saving_gbp": round(solar_saving_buckets.get(key, 0.0) / 100, prec),
                "battery_peak_saving_gbp": round(battery_peak_saving_buckets.get(key, 0.0) / 100, prec),
                "avg_import_rate_p": round(
                    import_rate_sum_buckets[key] / import_rate_count_buckets[key], prec
                ) if import_rate_count_buckets.get(key, 0) > 0 else None,
                "avg_export_rate_p": round(
                    export_rate_sum_buckets[key] / export_rate_count_buckets[key], prec
                ) if export_rate_count_buckets.get(key, 0) > 0 else None,
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
            "SELECT pvpower, feedin, power_in, power_out, "
            "battery_power, usage, soc, battery_temp, inverter_temp, grid_voltage "
            "FROM solaxdata "
            "ORDER BY time DESC LIMIT 1"
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


def _forecast_database_for_source(config: SolarIQConfig, source: str) -> str:
    if source == "solcast":
        return config.influxdb.solcast_forecast_database
    if source == "forecast_solar":
        return config.influxdb.forecast_solar_forecast_database
    raise ValueError(f"unsupported forecast source: {source}")


def save_solar_forecast_influx(
    config: SolarIQConfig,
    slots: list[float],
    for_date: date,
    source: str = "solcast",
) -> None:
    """Write 48-slot forecast to InfluxDB. Each slot is one point.

    source must be "solcast" or "forecast_solar".
    Raises on InfluxDB failure — caller should catch and log.
    """
    from datetime import timedelta
    tz = ZoneInfo(config.app.timezone)
    base_local = datetime(for_date.year, for_date.month, for_date.day, 0, 0, tzinfo=tz)
    points = []
    for i, kwh in enumerate(slots):
        t_local = base_local + timedelta(minutes=i * 30)
        t_utc = t_local.astimezone(timezone.utc)
        points.append({
            "measurement": "solar_forecast",
            "time": t_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tags": {"source": source},
            "fields": {"pv_estimate_kwh": float(kwh)},
        })
    client = InfluxDBClient(
        host=config.influxdb.host,
        port=config.influxdb.port,
        database=_forecast_database_for_source(config, source),
    )
    client.create_database(_forecast_database_for_source(config, source))
    client.write_points(points)
    logger.info(
        "saved %d %s forecast points for %s to InfluxDB", len(points), source, for_date
    )


def load_solar_forecast_influx(
    config: SolarIQConfig,
    for_date: date,
    source: str = "solcast",
) -> list[float] | None:
    """Read 48-slot forecast from InfluxDB. Returns None if data absent or partial."""
    from_utc, to_utc = _local_day_utc_bounds(for_date, config.app.timezone)
    tz = ZoneInfo(config.app.timezone)
    client = InfluxDBClient(
        host=config.influxdb.host,
        port=config.influxdb.port,
        database=_forecast_database_for_source(config, source),
    )
    try:
        result = client.query(
            f"SELECT pv_estimate_kwh FROM solar_forecast "
            f"WHERE time >= '{from_utc}' AND time < '{to_utc}'"
        )
        raw_points = list(result.get_points())
    except Exception as exc:
        # First run for a source may hit an Influx "database not found" error
        # before the worker has created the forecast database. Treat that as a
        # normal cache miss rather than a warning.
        if "database not found" in str(exc).lower():
            logger.debug(
                "load_solar_forecast_influx(%s): database missing for %s, returning None",
                source,
                for_date,
            )
            return None
        logger.warning("load_solar_forecast_influx(%s) query failed: %s", source, exc)
        return None

    if len(raw_points) < 48:
        logger.debug(
            "load_solar_forecast_influx(%s): only %d points for %s, returning None",
            source, len(raw_points), for_date,
        )
        return None

    slots = [0.0] * 48
    for point in raw_points:
        t_utc = datetime.fromisoformat(point["time"].replace("Z", "+00:00"))
        t_local = t_utc.astimezone(tz)
        if t_local.date() != for_date:
            continue
        slot = (t_local.hour * 60 + t_local.minute) // 30
        if 0 <= slot < 48:
            slots[slot] = float(point.get("pv_estimate_kwh") or 0.0)
    return slots
