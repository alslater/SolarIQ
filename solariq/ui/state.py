import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import reflex as rx

from solariq.app_settings import (
    OPTIMIZATION_SOURCE_FORECAST_SOLAR,
    OPTIMIZATION_SOURCE_SOLCAST,
    get_forecast_settings,
    init_app_settings_db,
    set_collect_forecast_solar,
    set_collect_solcast,
    set_optimization_source,
)
from solariq.cache import (
    get_cache_paths,
    load_calibration,
    load_solar_forecast_today,
    load_strategy,
    load_today_snapshot,
    save_calibration,
    save_solar_forecast_today,
    save_strategy,
)
from solariq.config import SolarIQConfig
from solariq.data.influx import get_today_live_data, get_historical_range_data, get_latest_inverter_stats, load_solar_forecast_influx
from solariq.data.forecast_solar import fetch_forecast_solar
from solariq.data.load_profile import build_load_profile
from solariq.data.octopus import UNPUBLISHED_RATE_CAP_P, fetch_agile_prices, fetch_export_prices, fetch_standing_charge_p_per_day, fetch_total_standing_charge_gbp, fill_unpublished_slots
from solariq.data.solcast import fetch_solar_forecast
from solariq.data.weather import fetch_today_weather
from solariq.optimizer.simulator import simulate, validate_periods
from solariq.optimizer.solver import solve
from solariq.optimizer.strategy import build_rolling_window, current_window_start
from solariq.optimizer.types import UserPeriod
from solariq.ui.auth_state import AuthState
from solariq.ui.state_common import get_config as _get_config

def _tomorrow(config: SolarIQConfig) -> date:
    tz = ZoneInfo(config.app.timezone)
    return (datetime.now(tz) + timedelta(days=1)).date()


def _prices_published(agile_tomorrow: list[float]) -> bool:
    """Return True if tomorrow's Agile prices are published (not all at cap)."""
    from solariq.data.octopus import UNPUBLISHED_RATE_CAP_P
    return not all(p >= UNPUBLISHED_RATE_CAP_P for p in agile_tomorrow)


def _select_forecast_slots(
    preferred_source: str,
    solcast_slots: list[float] | None,
    forecast_solar_slots: list[float] | None,
) -> tuple[list[float], bool]:
    """Return selected forecast slots and whether data was estimated/missing."""
    if preferred_source == OPTIMIZATION_SOURCE_FORECAST_SOLAR:
        if forecast_solar_slots is not None:
            return forecast_solar_slots, False
        if solcast_slots is not None:
            return solcast_slots, False
        return [0.0] * 48, True

    if solcast_slots is not None:
        return solcast_slots, False
    if forecast_solar_slots is not None:
        return forecast_solar_slots, False
    return [0.0] * 48, True


@dataclass
class _TodayDirectResult:
    battery_soc_pct: float
    battery_soc_kwh: float
    solar_today_kwh: float
    grid_import_today_kwh: float
    grid_export_today_kwh: float
    grid_cost_gbp: float
    grid_export_revenue_gbp: float
    net_daily_cost_gbp: float
    standing_charge_p_per_day: float
    current_rate_p: float
    current_export_rate_p: float
    chart_data: list
    price_data: list


@dataclass
class _TodayForecast:
    agile_prices: list
    export_prices: list
    solar_forecast: list
    load_forecast: list
    battery_soc_forecast: list


async def _fetch_today_direct(
    config: SolarIQConfig,
    today_local: date,
    log_context: str = "",
) -> _TodayDirectResult:
    """Fetch and compute all today-view data directly (bypassing worker snapshot).

    Used by both the polling fallback path and the manual refresh path.
    """
    try:
        sc = await asyncio.to_thread(fetch_standing_charge_p_per_day, config)
    except Exception:
        sc = config.octopus.standing_charge_p_per_day

    today_data = await asyncio.to_thread(get_today_live_data, config)
    load_profile = await asyncio.to_thread(build_load_profile, config, today_local)
    settings = get_forecast_settings(config.app.auth_db_path)

    solcast_forecast = None
    if settings.collect_solcast:
        solcast_forecast = load_solar_forecast_today(config, today_local.isoformat(), source="solcast")
    if settings.collect_solcast and solcast_forecast is None:
        try:
            slots = await asyncio.to_thread(fetch_solar_forecast, config, today_local)
            await asyncio.to_thread(
                save_solar_forecast_today,
                config,
                slots,
                today_local.isoformat(),
                "solcast",
            )
            solcast_forecast = slots
        except Exception as exc:
            logging.getLogger(__name__).warning("Solcast fetch failed%s: %s", log_context, exc)

    forecast_solar_forecast = None
    if settings.collect_forecast_solar:
        forecast_solar_forecast = load_solar_forecast_today(
            config,
            today_local.isoformat(),
            source="forecast_solar",
        )
    if settings.collect_forecast_solar and forecast_solar_forecast is None:
        try:
            slots = await asyncio.to_thread(fetch_forecast_solar, config, today_local)
            await asyncio.to_thread(
                save_solar_forecast_today,
                config,
                slots,
                today_local.isoformat(),
                "forecast_solar",
            )
            forecast_solar_forecast = slots
        except Exception as exc:
            logging.getLogger(__name__).warning("forecast.solar fetch failed%s: %s", log_context, exc)

    selected_forecast, _ = _select_forecast_slots(
        settings.optimization_source,
        solcast_forecast,
        forecast_solar_forecast,
    )

    solcast_for_chart = solcast_forecast or [0.0] * 48
    forecast_solar_for_chart = forecast_solar_forecast or [0.0] * 48
    timestamps = today_data.timestamps
    chart_rows = []
    for i in range(48):
        chart_rows.append({
            "time": timestamps[i],
            "grid_import": round(today_data.actual_grid_import[i] or 0.0, 3),
            "grid_export": round(today_data.actual_grid_export[i] or 0.0, 3),
            "solar": round(today_data.actual_solar[i] or 0.0, 3),
            "predicted_solar": round(selected_forecast[i], 3),
            "predicted_solar_solcast": round(solcast_for_chart[i], 3),
            "predicted_solar_forecast_solar": round(forecast_solar_for_chart[i], 3),
            "soc_pct": (
                (today_data.actual_battery_soc_kwh[i] or 0.0) / config.battery.capacity_kwh * 100
                if today_data.actual_battery_soc_kwh[i] is not None else None
            ),
            "predicted_usage": load_profile[i],
            "is_actual": i <= today_data.last_data_slot,
        })
    price_rows = [
        {
            "time": timestamps[i],
            "import": 0.0 if today_data.agile_prices[i] >= UNPUBLISHED_RATE_CAP_P else today_data.agile_prices[i],
            "export": 0.0 if today_data.export_prices[i] >= UNPUBLISHED_RATE_CAP_P else today_data.export_prices[i],
        }
        for i in range(48)
    ]

    return _TodayDirectResult(
        battery_soc_pct=round(today_data.battery_soc_pct, 1),
        battery_soc_kwh=round(today_data.battery_soc_kwh, 1),
        solar_today_kwh=round(today_data.solar_today_kwh, 2),
        grid_import_today_kwh=round(sum(v for v in today_data.actual_grid_import if v is not None), 2),
        grid_export_today_kwh=round(sum(v for v in today_data.actual_grid_export if v is not None), 2),
        grid_cost_gbp=round(today_data.grid_cost_pence / 100, 2),
        grid_export_revenue_gbp=round(today_data.grid_export_revenue_pence / 100, 2),
        net_daily_cost_gbp=round((today_data.grid_cost_pence - today_data.grid_export_revenue_pence + sc) / 100, 2),
        standing_charge_p_per_day=sc,
        current_rate_p=round(today_data.current_rate_p, 1),
        current_export_rate_p=round(today_data.current_export_rate_p, 1),
        chart_data=chart_rows,
        price_data=price_rows,
    )


def _parse_localstorage_bool(raw: str) -> bool:
    return str(raw).lower() in {"1", "true", "yes", "on"}


class AppState(AuthState):
    # Navigation
    current_page: str = "today"
    sidebar_collapsed_raw: str = rx.LocalStorage(
        "0",
        name="solariq_sidebar_collapsed",
    )

    # Tomorrow strategy
    strategy_periods: list[dict] = []
    estimated_cost_gbp: float = 0.0
    solar_forecast_kwh: float = 0.0
    grid_import_kwh: float = 0.0
    strategy_computed_at: str = ""
    strategy_valid_until: str = ""
    strategy_loading: bool = False
    strategy_error: str = ""
    strategy_solar_estimated: bool = False
    show_self_use_implicit: bool = True
    show_self_use_explicit: bool = True
    show_charge: bool = True
    sort_strategy_by_time: bool = False

    # Evaluation page
    evaluation_periods: list[dict] = []
    evaluation_loading: bool = False
    evaluation_error: str = ""
    evaluation_has_result: bool = False
    evaluation_result_cost: float = 0.0
    evaluation_solar_kwh: float = 0.0
    evaluation_grid_import_kwh: float = 0.0
    evaluation_price_data: list[dict] = []
    evaluation_solar_data: list[dict] = []
    evaluation_today_mode: bool = False
    evaluation_current_slot: int = 0
    evaluation_current_slot_time: str = ""

    # Tomorrow charts
    tomorrow_price_data: list[dict] = []
    tomorrow_solar_data: list[dict] = []

    # Forecast source settings
    collect_solcast_enabled: bool = True
    collect_forecast_solar_enabled: bool = False
    optimization_forecast_source: str = OPTIMIZATION_SOURCE_SOLCAST
    today_show_solcast_forecast_raw: str = rx.LocalStorage(
        "1",
        name="solariq_today_show_solcast_forecast",
    )
    today_show_forecast_solar_forecast_raw: str = rx.LocalStorage(
        "0",
        name="solariq_today_show_forecast_solar_forecast",
    )
    history_show_solcast_forecast_raw: str = rx.LocalStorage(
        "1",
        name="solariq_history_show_solcast_forecast",
    )
    history_show_forecast_solar_forecast_raw: str = rx.LocalStorage(
        "0",
        name="solariq_history_show_forecast_solar_forecast",
    )

    # Today data
    battery_soc_pct: float = 0.0
    battery_soc_kwh: float = 0.0
    solar_today_kwh: float = 0.0
    grid_import_today_kwh: float = 0.0
    grid_export_today_kwh: float = 0.0
    grid_cost_gbp: float = 0.0
    grid_export_revenue_gbp: float = 0.0
    net_daily_cost_gbp: float = 0.0
    standing_charge_p_per_day: float = 0.0
    current_rate_p: float = 0.0
    current_export_rate_p: float = 0.0
    today_loading: bool = False
    today_poll_running: bool = False
    today_poll_generation: int = 0
    today_error: str = ""
    today_weather_code: int = -1
    today_weather_max_temp_c: float = 0.0

    # Today charts
    today_chart_data: list[dict] = []
    today_price_data: list[dict] = []

    # History page
    history_start_date: str = ""
    history_end_date: str = ""
    history_loading: bool = False
    history_error: str = ""
    history_solar_kwh: float = 0.0
    history_grid_import_kwh: float = 0.0
    history_grid_export_kwh: float = 0.0
    history_grid_cost_gbp: float = 0.0
    history_grid_export_revenue_gbp: float = 0.0
    history_solar_saving_gbp: float = 0.0
    history_battery_peak_saving_gbp: float = 0.0
    history_net_period_cost_gbp: float = 0.0
    history_chart_data: list[dict] = []
    history_has_data: bool = False

    # Inverter stats
    inverter_pvpower_kw: float = 0.0
    inverter_feedin_kw: float = 0.0
    inverter_power_in_kw: float = 0.0
    inverter_power_out_kw: float = 0.0
    inverter_battery_power_kw: float = 0.0
    inverter_usage_kw: float = 0.0
    inverter_soc_pct: float = 0.0
    inverter_battery_temp_c: float = 0.0
    inverter_temp_c: float = 0.0
    inverter_grid_voltage_v: float = 0.0
    inverter_recorded_at: str = ""
    inverter_loading: bool = False
    inverter_error: str = ""
    inverter_refresh_interval: int = 30
    inverter_countdown: int = 30
    inverter_poll_generation: int = 0

    # Calibration
    export_factor: float = 1.0
    calibration_computed_at: str = ""
    calibration_octopus_kwh: float = 0.0
    calibration_influx_kwh: float = 0.0

    def _post_auth_success_events(self) -> list:
        return [
            AppState.load_forecast_settings,
            AppState.load_cached_strategy,
            AppState.load_cached_calibration,
        ]

    @rx.var
    def sidebar_collapsed(self) -> bool:
        return _parse_localstorage_bool(self.sidebar_collapsed_raw)

    @rx.var
    def optimize_with_solcast(self) -> bool:
        return self.optimization_forecast_source == OPTIMIZATION_SOURCE_SOLCAST

    @rx.var
    def optimize_with_forecast_solar(self) -> bool:
        return self.optimization_forecast_source == OPTIMIZATION_SOURCE_FORECAST_SOLAR

    @rx.var
    def optimization_forecast_source_label(self) -> str:
        if self.optimization_forecast_source == OPTIMIZATION_SOURCE_FORECAST_SOLAR:
            return "Source: forecast.solar"
        return "Source: Solcast"

    @rx.var
    def today_show_solcast_forecast(self) -> bool:
        return _parse_localstorage_bool(self.today_show_solcast_forecast_raw)

    @rx.var
    def today_show_forecast_solar_forecast(self) -> bool:
        return _parse_localstorage_bool(self.today_show_forecast_solar_forecast_raw)

    @rx.var
    def history_show_solcast_forecast(self) -> bool:
        return _parse_localstorage_bool(self.history_show_solcast_forecast_raw)

    @rx.var
    def history_show_forecast_solar_forecast(self) -> bool:
        return _parse_localstorage_bool(self.history_show_forecast_solar_forecast_raw)

    @rx.event
    def load_forecast_settings(self):
        """Load forecast settings from SQLite into state fields."""
        settings = self._read_forecast_settings_from_db()
        self._apply_forecast_settings(settings)

    def _read_forecast_settings_from_db(self):
        db_path = _get_config().app.auth_db_path
        init_app_settings_db(db_path)
        return get_forecast_settings(db_path)

    def _apply_forecast_settings(self, settings) -> None:
        self.collect_solcast_enabled = settings.collect_solcast
        self.collect_forecast_solar_enabled = settings.collect_forecast_solar
        self.optimization_forecast_source = settings.optimization_source

    def _sync_forecast_settings_from_db(self) -> None:
        """Refresh forecast settings from SQLite if another instance changed them."""
        settings = self._read_forecast_settings_from_db()
        self._apply_forecast_settings(settings)

    @rx.event
    def set_collect_solcast_enabled(self, enabled: bool):
        if not self.current_user_is_admin:
            return rx.toast.warning("Only administrators can change forecast collection settings.")
        db_path = _get_config().app.auth_db_path
        init_app_settings_db(db_path)
        set_collect_solcast(db_path, bool(enabled))
        self.collect_solcast_enabled = bool(enabled)

    @rx.event
    def set_collect_forecast_solar_enabled(self, enabled: bool):
        if not self.current_user_is_admin:
            return rx.toast.warning("Only administrators can change forecast collection settings.")
        db_path = _get_config().app.auth_db_path
        init_app_settings_db(db_path)
        set_collect_forecast_solar(db_path, bool(enabled))
        self.collect_forecast_solar_enabled = bool(enabled)

    @rx.event
    def set_optimization_forecast_source(self, source: str):
        if not self.current_user_is_admin:
            return rx.toast.warning("Only administrators can change optimization forecast source.")
        if source not in {OPTIMIZATION_SOURCE_SOLCAST, OPTIMIZATION_SOURCE_FORECAST_SOLAR}:
            return
        db_path = _get_config().app.auth_db_path
        init_app_settings_db(db_path)
        set_optimization_source(db_path, source)
        self.optimization_forecast_source = source

    @rx.event
    def set_today_show_solcast_forecast(self, enabled: bool):
        self.today_show_solcast_forecast_raw = "1" if bool(enabled) else "0"

    @rx.event
    def set_today_show_forecast_solar_forecast(self, enabled: bool):
        self.today_show_forecast_solar_forecast_raw = "1" if bool(enabled) else "0"

    @rx.event
    def set_history_show_solcast_forecast(self, enabled: bool):
        self.history_show_solcast_forecast_raw = "1" if bool(enabled) else "0"

    @rx.event
    def set_history_show_forecast_solar_forecast(self, enabled: bool):
        self.history_show_forecast_solar_forecast_raw = "1" if bool(enabled) else "0"

    @rx.event
    def login(self):
        return self._login_impl()

    @rx.event
    def create_initial_user(self):
        return self._create_initial_user_impl()

    @rx.event
    def on_load(self):
        return self._on_load_impl()

    calibration_loading: bool = False
    calibration_error: str = ""

    # Cache management
    cache_clear_message: str = ""

    @rx.var
    def corrected_export_today_kwh(self) -> float:
        return round(self.grid_export_today_kwh * self.export_factor, 2)

    @rx.var
    def corrected_export_revenue_gbp(self) -> float:
        return round(self.grid_export_revenue_gbp * self.export_factor, 2)

    @rx.var
    def corrected_net_daily_cost_gbp(self) -> float:
        # Adjust pre-computed net by (1 - factor) × raw revenue to correct for factor
        return round(
            self.net_daily_cost_gbp + self.grid_export_revenue_gbp * (1.0 - self.export_factor),
            2,
        )

    @rx.var
    def corrected_history_export_kwh(self) -> float:
        return round(self.history_grid_export_kwh * self.export_factor, 2)

    @rx.var
    def corrected_history_export_revenue_gbp(self) -> float:
        return round(self.history_grid_export_revenue_gbp * self.export_factor, 2)

    @rx.var
    def corrected_history_net_period_cost_gbp(self) -> float:
        return round(
            self.history_net_period_cost_gbp + self.history_grid_export_revenue_gbp * (1.0 - self.export_factor),
            2,
        )

    # ── Formatted price strings ────────────────────────────────────────────────

    @rx.var
    def grid_cost_str(self) -> str:
        return f"£{self.grid_cost_gbp:.2f}"

    @rx.var
    def corrected_export_revenue_str(self) -> str:
        return f"£{round(self.grid_export_revenue_gbp * self.export_factor, 2):.2f}"

    @rx.var
    def corrected_net_daily_cost_str(self) -> str:
        return f"£{round(self.net_daily_cost_gbp + self.grid_export_revenue_gbp * (1.0 - self.export_factor), 2):.2f}"

    @rx.var
    def current_rate_str(self) -> str:
        return f"{self.current_rate_p:.2f}p"

    @rx.var
    def current_export_rate_str(self) -> str:
        return f"Export: {self.current_export_rate_p:.2f}p"

    @rx.var
    def avg_import_rate_str(self) -> str:
        rates = [row["import"] for row in self.today_price_data if row.get("import", 100) < 90]
        if not rates:
            return "—"
        return f"{sum(rates) / len(rates):.2f}p"

    @rx.var
    def avg_export_rate_str(self) -> str:
        rates = [row["export"] for row in self.today_price_data if row.get("export", 100) < 90]
        if not rates:
            return "Export: —"
        return f"Export: {sum(rates) / len(rates):.2f}p"

    @rx.var
    def avg_paid_rate_str(self) -> str:
        total_kwh = 0.0
        total_cost_p = 0.0
        for chart, price in zip(self.today_chart_data, self.today_price_data):
            kwh = chart.get("grid_import") or 0.0
            rate = price.get("import") or 0.0
            if kwh > 0 and rate < 90:
                total_kwh += kwh
                total_cost_p += kwh * rate
        if total_kwh <= 0:
            return "—"
        return f"{total_cost_p / total_kwh:.2f}p"

    @rx.var
    def today_weather_icon(self) -> str:
        c = self.today_weather_code
        if c < 0:
            return "help-circle"
        if c == 0 or c == 1:
            return "sun"
        if c == 2:
            return "cloud-sun"
        if c == 3:
            return "cloud"
        if c in (45, 48):
            return "cloud-fog"
        if c in (51, 53, 55, 56, 57):
            return "cloud-drizzle"
        if c in (61, 63, 65, 66, 67, 80, 81, 82):
            return "cloud-rain"
        if c in (71, 73, 75, 77, 85, 86):
            return "cloud-snow"
        if c in (95, 96, 99):
            return "cloud-lightning"
        return "cloud"

    @rx.var
    def today_weather_label(self) -> str:
        c = self.today_weather_code
        if c < 0:
            return "—"
        if c == 0:
            return "Clear sky"
        if c == 1:
            return "Mainly clear"
        if c == 2:
            return "Partly cloudy"
        if c == 3:
            return "Overcast"
        if c in (45, 48):
            return "Foggy"
        if c in (51, 53, 55):
            return "Drizzle"
        if c in (56, 57):
            return "Freezing drizzle"
        if c in (61, 63, 65):
            return "Rain"
        if c in (66, 67):
            return "Freezing rain"
        if c in (71, 73, 75, 77):
            return "Snow"
        if c in (80, 81, 82):
            return "Showers"
        if c in (85, 86):
            return "Snow showers"
        if c in (95, 96, 99):
            return "Thunderstorm"
        return "—"

    @rx.var
    def today_weather_temp_str(self) -> str:
        if self.today_weather_code < 0:
            return ""
        return f"Max {self.today_weather_max_temp_c:.0f}°C"

    @rx.var
    def history_grid_cost_str(self) -> str:
        return f"£{self.history_grid_cost_gbp:.2f}"

    @rx.var
    def history_grid_export_revenue_str(self) -> str:
        return f"£{self.history_grid_export_revenue_gbp:.2f}"

    @rx.var
    def history_solar_saving_str(self) -> str:
        return f"£{self.history_solar_saving_gbp:.2f}"

    @rx.var
    def history_battery_peak_saving_str(self) -> str:
        return f"£{self.history_battery_peak_saving_gbp:.2f}"

    @rx.var
    def history_net_period_cost_str(self) -> str:
        return f"£{self.history_net_period_cost_gbp:.2f}"

    @rx.var
    def history_avg_rate_str(self) -> str:
        rates = [r["avg_import_rate_p"] for r in self.history_chart_data if r.get("avg_import_rate_p") is not None]
        if not rates:
            return "—"
        return f"{sum(rates) / len(rates):.2f}p"

    @rx.var
    def history_avg_export_rate_str(self) -> str:
        rates = [r["avg_export_rate_p"] for r in self.history_chart_data if r.get("avg_export_rate_p") is not None]
        if not rates:
            return "Export: —"
        return f"Export: {sum(rates) / len(rates):.2f}p"

    @rx.var
    def history_avg_paid_rate_str(self) -> str:
        total_kwh = sum(r.get("grid_import_kwh") or 0.0 for r in self.history_chart_data)
        total_cost_gbp = sum(r.get("grid_cost_gbp") or 0.0 for r in self.history_chart_data)
        if total_kwh <= 0:
            return "—"
        return f"{total_cost_gbp * 100 / total_kwh:.2f}p"

    @rx.var
    def calibration_label(self) -> str:
        """Subtitle for export stat cards: '×1.092 calibrated' or 'uncalibrated'."""
        if not self.calibration_computed_at:
            return "uncalibrated"
        return f"×{self.export_factor:.3f} calibrated"

    @rx.var
    def calibration_age_str(self) -> str:
        """Human-readable age of the calibration data, e.g. '3d ago'."""
        if not self.calibration_computed_at:
            return "never"
        try:
            dt = datetime.fromisoformat(self.calibration_computed_at)
            diff = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
            days = diff.days
            if days == 0:
                hours = diff.seconds // 3600
                return f"{hours}h ago" if hours > 0 else "just now"
            return f"{days}d ago"
        except Exception:
            return "unknown"

    @rx.var
    def calibration_computed_at_local(self) -> str:
        """calibration_computed_at formatted in the configured local timezone."""
        if not self.calibration_computed_at:
            return ""
        try:
            tz = ZoneInfo(_get_config().app.timezone)
            dt = datetime.fromisoformat(self.calibration_computed_at).astimezone(tz)
            return dt.strftime("%d %b %Y %H:%M")
        except Exception:
            return self.calibration_computed_at

    @rx.event
    def set_page(self, page: str):
        self.current_page = page
        if page == "settings":
            self.account_form_error = ""
            self.admin_form_error = ""
            return AppState.load_forecast_settings
        if page == "today":
            return AppState.refresh_today_data

    @rx.event
    def toggle_sidebar(self):
        self.sidebar_collapsed_raw = "0" if self.sidebar_collapsed else "1"

    @rx.event
    def set_history_start(self, value: str):
        self.history_start_date = value

    @rx.event
    def set_history_end(self, value: str):
        self.history_end_date = value

    @rx.event
    def select_yesterday(self):
        config = _get_config()
        tz = ZoneInfo(config.app.timezone)
        yesterday = (datetime.now(tz) - timedelta(days=1)).date().isoformat()
        self.history_start_date = yesterday
        self.history_end_date = yesterday
        return AppState.load_history

    @rx.event
    def select_day_before_yesterday(self):
        config = _get_config()
        tz = ZoneInfo(config.app.timezone)
        day_before = (datetime.now(tz) - timedelta(days=2)).date().isoformat()
        self.history_start_date = day_before
        self.history_end_date = day_before
        return AppState.load_history

    @rx.event
    def select_this_week(self):
        config = _get_config()
        tz = ZoneInfo(config.app.timezone)
        today = datetime.now(tz).date()
        monday = today - timedelta(days=today.weekday())
        self.history_start_date = monday.isoformat()
        self.history_end_date = today.isoformat()
        return AppState.load_history

    @rx.event
    def select_last_week(self):
        config = _get_config()
        tz = ZoneInfo(config.app.timezone)
        today = datetime.now(tz).date()
        last_monday = today - timedelta(days=today.weekday() + 7)
        last_sunday = last_monday + timedelta(days=6)
        self.history_start_date = last_monday.isoformat()
        self.history_end_date = last_sunday.isoformat()
        return AppState.load_history

    @rx.event
    def select_this_month(self):
        config = _get_config()
        tz = ZoneInfo(config.app.timezone)
        today = datetime.now(tz).date()
        self.history_start_date = today.replace(day=1).isoformat()
        self.history_end_date = today.isoformat()
        return AppState.load_history

    @rx.event
    def select_last_month(self):
        config = _get_config()
        tz = ZoneInfo(config.app.timezone)
        today = datetime.now(tz).date()
        first_of_this_month = today.replace(day=1)
        last_day_of_last_month = first_of_this_month - timedelta(days=1)
        self.history_start_date = last_day_of_last_month.replace(day=1).isoformat()
        self.history_end_date = last_day_of_last_month.isoformat()
        return AppState.load_history

    @rx.event(background=True)
    async def load_history(self):
        async with self:
            if not self.history_start_date or not self.history_end_date:
                self.history_error = "Please select both a start and end date."
                return
            self.history_loading = True
            self.history_error = ""
            self.history_has_data = False

        config = _get_config()
        try:
            start = date.fromisoformat(self.history_start_date)
            end = date.fromisoformat(self.history_end_date)
            if end < start:
                async with self:
                    self.history_error = "End date must be on or after start date."
                    self.history_loading = False
                return

            rows = await asyncio.to_thread(get_historical_range_data, config, start, end)

            try:
                standing_total_gbp = await asyncio.to_thread(fetch_total_standing_charge_gbp, config, start, end)
            except Exception as exc:
                delta_days = (end - start).days + 1
                standing_total_gbp = config.octopus.standing_charge_p_per_day * delta_days / 100
                import logging
                logging.getLogger(__name__).warning("standing charge range fetch failed: %s", exc)

            async with self:
                self.history_chart_data = rows
                self.history_solar_kwh = round(sum(r["solar_kwh"] for r in rows), 2)
                self.history_grid_import_kwh = round(sum(r["grid_import_kwh"] for r in rows), 2)
                self.history_grid_export_kwh = round(sum(r["grid_export_kwh"] for r in rows), 2)
                self.history_grid_cost_gbp = round(sum(r["grid_cost_gbp"] for r in rows), 2)
                self.history_grid_export_revenue_gbp = round(sum(r["grid_export_revenue_gbp"] for r in rows), 2)
                self.history_solar_saving_gbp = round(sum(r["solar_saving_gbp"] for r in rows), 2)
                self.history_battery_peak_saving_gbp = round(sum(r["battery_peak_saving_gbp"] for r in rows), 2)
                self.history_net_period_cost_gbp = round(
                    sum(r["grid_cost_gbp"] for r in rows)
                    - sum(r["grid_export_revenue_gbp"] for r in rows)
                    + standing_total_gbp,
                    2,
                )
                self.history_has_data = True
                self.history_loading = False
        except Exception as exc:
            async with self:
                self.history_error = str(exc)
                self.history_loading = False

    @rx.event
    def load_cached_strategy(self):
        result = load_strategy()
        if result:
            self._apply_strategy(result)

    @rx.event
    def load_cached_calibration(self):
        data = load_calibration()
        if data:
            self.export_factor = data.get("factor", 1.0)
            self.calibration_computed_at = data.get("computed_at", "")
            self.calibration_octopus_kwh = data.get("octopus_kwh", 0.0)
            self.calibration_influx_kwh = data.get("influx_kwh", 0.0)

    @rx.event(background=True)
    async def recalibrate(self):
        async with self:
            self.calibration_loading = True
            self.calibration_error = ""

        config = _get_config()
        try:
            from solariq.calibration import compute_export_factor
            result = await asyncio.to_thread(compute_export_factor, config)
            await asyncio.to_thread(save_calibration, result)
            async with self:
                self.export_factor = result["factor"]
                self.calibration_computed_at = result["computed_at"]
                self.calibration_octopus_kwh = result["octopus_kwh"]
                self.calibration_influx_kwh = result["influx_kwh"]
                self.calibration_loading = False
        except Exception as exc:
            async with self:
                self.calibration_error = str(exc)
                self.calibration_loading = False

    @rx.var
    def inverter_refresh_progress(self) -> int:
        if self.inverter_refresh_interval == 0:
            return 0
        return int(self.inverter_countdown / self.inverter_refresh_interval * 100)

    @rx.var
    def inverter_recorded_at_local(self) -> str:
        """inverter_recorded_at formatted in the configured local timezone."""
        if not self.inverter_recorded_at:
            return ""
        try:
            tz = ZoneInfo(_get_config().app.timezone)
            dt = datetime.fromisoformat(self.inverter_recorded_at.replace("Z", "+00:00")).astimezone(tz)
            return dt.strftime("%d %b %Y %H:%M")
        except Exception:
            return self.inverter_recorded_at

    def _write_inverter_stats(self, stats: dict | None) -> None:
        if stats:
            self.inverter_pvpower_kw = stats["pvpower_kw"]
            self.inverter_feedin_kw = stats["feedin_kw"]
            self.inverter_power_in_kw = stats["power_in_kw"]
            self.inverter_power_out_kw = stats["power_out_kw"]
            self.inverter_battery_power_kw = stats["battery_power_kw"]
            self.inverter_usage_kw = stats["usage_kw"]
            self.inverter_soc_pct = stats["soc_pct"]
            self.inverter_battery_temp_c = stats["battery_temp_c"]
            self.inverter_temp_c = stats["inverter_temp_c"]
            self.inverter_grid_voltage_v = stats["grid_voltage_v"]
            recorded_at_raw = str(stats.get("recorded_at") or "")
            if recorded_at_raw:
                try:
                    dt = datetime.fromisoformat(recorded_at_raw.replace("Z", "+00:00"))
                    # Influx LAST() can return epoch-zero timestamps when no real points exist.
                    if dt.year >= 2000:
                        self.inverter_recorded_at = dt.isoformat().replace("+00:00", "Z")
                    else:
                        self.inverter_recorded_at = ""
                except ValueError:
                    self.inverter_recorded_at = ""
            else:
                self.inverter_recorded_at = ""
        else:
            self.inverter_error = "No data returned from inverter"
            self.inverter_recorded_at = ""

    @rx.event(background=True)
    async def load_inverter_stats(self):
        """Manual refresh — fetches immediately and resets the auto-refresh countdown."""
        config = _get_config()
        async with self:
            self.inverter_loading = True
            self.inverter_error = ""
        try:
            stats = await asyncio.to_thread(get_latest_inverter_stats, config)
            async with self:
                self._write_inverter_stats(stats)
                self.inverter_loading = False
                self.inverter_countdown = self.inverter_refresh_interval
        except Exception as exc:
            async with self:
                self.inverter_error = str(exc)
                self.inverter_loading = False
                self.inverter_countdown = self.inverter_refresh_interval

    @rx.event
    def set_inverter_refresh_interval(self, interval: int):
        self.inverter_refresh_interval = interval
        self.inverter_countdown = interval
        return AppState.start_inverter_polling

    @rx.event(background=True)
    async def start_inverter_polling(self):
        """Load stats immediately then tick every second, refreshing when countdown hits zero."""
        config = _get_config()
        async with self:
            self.inverter_poll_generation += 1
            my_gen = self.inverter_poll_generation
            self.inverter_loading = True
            self.inverter_error = ""

        try:
            stats = await asyncio.to_thread(get_latest_inverter_stats, config)
            async with self:
                if self.inverter_poll_generation != my_gen:
                    return
                self._write_inverter_stats(stats)
                self.inverter_loading = False
                self.inverter_countdown = self.inverter_refresh_interval
        except Exception as exc:
            async with self:
                self.inverter_error = str(exc)
                self.inverter_loading = False
                self.inverter_countdown = self.inverter_refresh_interval

        while True:
            await asyncio.sleep(1)
            async with self:
                if self.inverter_poll_generation != my_gen:
                    return
                self.inverter_countdown = max(0, self.inverter_countdown - 1)
                do_refresh = self.inverter_countdown == 0

            if do_refresh:
                async with self:
                    self.inverter_loading = True
                    self.inverter_error = ""
                try:
                    stats = await asyncio.to_thread(get_latest_inverter_stats, config)
                    async with self:
                        if self.inverter_poll_generation != my_gen:
                            return
                        self._write_inverter_stats(stats)
                        self.inverter_loading = False
                        self.inverter_countdown = self.inverter_refresh_interval
                except Exception as exc:
                    async with self:
                        self.inverter_error = str(exc)
                        self.inverter_loading = False
                        self.inverter_countdown = self.inverter_refresh_interval

    @rx.event
    def clear_cache(self):
        if not self.current_user_is_admin:
            return rx.toast.warning(
                "Only administrators can clear cache.",
                duration=4000,
                close_button=True,
            )

        from pathlib import Path
        cleared = []
        for path in get_cache_paths():
            p = Path(path)
            if p.exists():
                p.unlink()
                cleared.append(p.name)
        self.cache_clear_message = ""
        if cleared:
            return rx.toast.success(
                f"Cleared: {', '.join(cleared)}",
                duration=5000,
                close_button=True,
            )
        return rx.toast.warning(
            "Cache already empty",
            duration=4000,
            close_button=True,
        )

    def _apply_strategy(self, result, capacity_kwh: float = 0.0) -> None:
        if not capacity_kwh:
            capacity_kwh = _get_config().battery.capacity_kwh
        self.strategy_periods = [p.to_dict() for p in result.periods]
        self.estimated_cost_gbp = round(result.estimated_cost_gbp, 2)
        self.solar_forecast_kwh = round(result.solar_forecast_kwh, 1)
        self.grid_import_kwh = round(result.grid_import_kwh, 1)
        self.strategy_computed_at = result.computed_at
        self.strategy_valid_until = result.valid_until
        self.strategy_solar_estimated = result.solar_forecast_estimated

        if result.window_start:
            ws = datetime.fromisoformat(result.window_start)
            timestamps = [
                (ws + timedelta(minutes=t * 30)).strftime("%H:%M")
                for t in range(48)
            ]
        else:
            timestamps = [
                f"{(t * 30) // 60:02d}:{(t * 30) % 60:02d}" for t in range(48)
            ]

        # Build a per-slot mode label from periods so chart bars can be annotated by mode.
        slot_modes = ["Self Use (Implicit)"] * 48
        start_slots: list[int] = []
        for period in result.periods:
            try:
                start_slots.append(timestamps.index(period.start_time))
            except ValueError:
                start_slots.append(0)
        for i, period in enumerate(result.periods):
            start = start_slots[i]
            end = start_slots[i + 1] if i + 1 < len(start_slots) else 48
            if period.mode == "Charge":
                mode_label = "Charge"
            elif period.is_default:
                mode_label = "Self Use (Implicit)"
            else:
                mode_label = "Self Use (Explicit)"
            for t in range(start, end):
                slot_modes[t] = mode_label

        self.tomorrow_price_data = []
        for t in range(48):
            mode_label = slot_modes[t]
            price = result.agile_prices[t]
            self.tomorrow_price_data.append(
                {
                    "time": timestamps[t],
                    "price": price,
                    "export": result.export_prices[t],
                    "mode": mode_label,
                    "price_charge": price if mode_label == "Charge" else 0.0,
                    "price_self_use_explicit": price if mode_label == "Self Use (Explicit)" else 0.0,
                    "price_self_use_implicit": price if mode_label == "Self Use (Implicit)" else 0.0,
                }
            )
        self.tomorrow_solar_data = [
            {
                "time": timestamps[t],
                "solar": result.solar_forecast[t],
                "soc_pct": round(result.battery_soc_forecast[t] / capacity_kwh * 100, 1) if capacity_kwh else 0.0,
            }
            for t in range(48)
        ]

    @rx.var
    def strategy_valid_until_str(self) -> str:
        if not self.strategy_valid_until:
            return ""
        try:
            dt = datetime.fromisoformat(self.strategy_valid_until)
            return dt.strftime("%H:%M %d %b")
        except ValueError:
            return self.strategy_valid_until

    @rx.var
    def test_strategy_mode(self) -> bool:
        return _get_config().app.test_strategy_mode

    @rx.var
    def evaluation_agile_chart_data(self) -> list[dict]:
        """Agile import and export prices for the reference chart above the schedule editor."""
        if self.evaluation_today_mode:
            return [
                {"time": row["time"], "import": row.get("import", 0.0), "export": row.get("export", 0.0)}
                for row in self.today_price_data
            ]
        return [
            {"time": row["time"], "import": row.get("price", 0.0), "export": row.get("export", 0.0)}
            for row in self.tomorrow_price_data
        ]

    @rx.var
    def filtered_strategy_periods(self) -> list[dict]:
        filtered: list[dict] = []
        for period in self.strategy_periods:
            mode = period.get("mode")
            if mode == "Charge":
                if self.show_charge:
                    filtered.append(period)
                continue

            if mode == "Self Use":
                is_default = period.get("is_default", period.get("min_soc_pct", 10) <= 10)
                if is_default and self.show_self_use_implicit:
                    filtered.append(period)
                if (not is_default) and self.show_self_use_explicit:
                    filtered.append(period)
        if self.sort_strategy_by_time:
            filtered = sorted(filtered, key=lambda p: p.get("start_time", ""))
        return filtered

    @rx.event
    def toggle_show_self_use_implicit(self):
        self.show_self_use_implicit = not self.show_self_use_implicit

    @rx.event
    def toggle_show_self_use_explicit(self):
        self.show_self_use_explicit = not self.show_self_use_explicit

    @rx.event
    def toggle_show_charge(self):
        self.show_charge = not self.show_charge

    @rx.event
    def toggle_sort_strategy_by_time(self):
        self.sort_strategy_by_time = not self.sort_strategy_by_time

    @rx.event
    def add_evaluation_period(self):
        default_start = self.evaluation_current_slot_time if self.evaluation_today_mode else "00:00"
        if not self.evaluation_periods:
            self.evaluation_periods = [{
                "start_time": default_start,
                "end_time": "24:00",
                "mode": "Self Use",
                "target_soc_pct": 100,
                "max_charge_kw": 3.6,
                "min_soc_pct": 10,
            }]
        else:
            last = self.evaluation_periods[-1]
            self.evaluation_periods = self.evaluation_periods + [{
                "start_time": last["end_time"],
                "end_time": "24:00",
                "mode": "Self Use",
                "target_soc_pct": 100,
                "max_charge_kw": 3.6,
                "min_soc_pct": 10,
            }]

    @rx.event
    def update_evaluation_period(self, index: int, field: str, value):
        updated = list(self.evaluation_periods)
        updated[index] = {**updated[index], field: value}
        self.evaluation_periods = updated

    @rx.event
    def remove_evaluation_period(self, index: int):
        self.evaluation_periods = [
            p for i, p in enumerate(self.evaluation_periods) if i != index
        ]

    @rx.event
    def toggle_evaluation_today_mode(self):
        config = _get_config()
        self.evaluation_today_mode = not self.evaluation_today_mode
        self.evaluation_has_result = False
        self.evaluation_error = ""
        if self.evaluation_today_mode:
            slot, _ = current_window_start(config.app.timezone)
            self.evaluation_current_slot = slot
            h = (slot * 30) // 60
            m = (slot * 30) % 60
            self.evaluation_current_slot_time = f"{h:02d}:{m:02d}"
            self.evaluation_periods = [{
                "start_time": self.evaluation_current_slot_time,
                "end_time": "24:00",
                "mode": "Self Use",
                "target_soc_pct": 100,
                "max_charge_kw": 3.6,
                "min_soc_pct": 10,
            }]
        else:
            self.evaluation_periods = []
            self.evaluation_current_slot = 0
            self.evaluation_current_slot_time = ""

    @rx.event(background=True)
    async def evaluate_schedule(self):
        async with self:
            self.evaluation_loading = True
            self.evaluation_error = ""
            self.evaluation_has_result = False

        config = _get_config()
        today_mode = self.evaluation_today_mode
        current_slot = self.evaluation_current_slot

        try:
            periods = [
                UserPeriod(
                    start_time=p["start_time"],
                    end_time=p["end_time"],
                    mode=p["mode"],
                    target_soc_pct=int(p.get("target_soc_pct", 100)),
                    max_charge_kw=float(p.get("max_charge_kw", config.battery.max_charge_kw)),
                    min_soc_pct=int(p.get("min_soc_pct", 10)),
                )
                for p in self.evaluation_periods
            ]
            error = validate_periods(periods, start_slot=current_slot if today_mode else 0)
        except Exception as exc:
            async with self:
                self.evaluation_error = f"Invalid period input: {exc}"
                self.evaluation_loading = False
            return

        if error:
            async with self:
                self.evaluation_error = error
                self.evaluation_loading = False
            return

        if today_mode:
            # Build forecast from today's actuals + today's solar forecast
            snapshot = await asyncio.to_thread(load_today_snapshot)
            if snapshot is None or snapshot.get("error"):
                # Worker not running — fetch live data directly as fallback
                try:
                    tz = ZoneInfo(config.app.timezone)
                    today_local = datetime.now(tz).date()
                    direct = await _fetch_today_direct(config, today_local)
                    chart_data = direct.chart_data
                    price_data_snap = direct.price_data
                    battery_soc_kwh = direct.battery_soc_kwh
                except Exception as exc:
                    async with self:
                        self.evaluation_error = f"Could not load today data: {exc}"
                        self.evaluation_loading = False
                    return
            else:
                chart_data = snapshot.get("chart_data", [])
                price_data_snap = snapshot.get("price_data", [])
                battery_soc_kwh = snapshot.get("battery_soc_kwh", 0.0)

            # Extract per-slot arrays from chart_data (always exactly 48 entries)
            actual_solar_raw = [row.get("solar", 0.0) or 0.0 for row in chart_data]
            # actual_usage = grid_import + solar - grid_export (energy balance)
            actual_usage_raw = [
                (row.get("grid_import", 0.0) or 0.0)
                + (row.get("solar", 0.0) or 0.0)
                - (row.get("grid_export", 0.0) or 0.0)
                for row in chart_data
            ]
            predicted_usage_raw = [row.get("predicted_usage", 0.0) or 0.0 for row in chart_data]
            agile_prices_raw = [row.get("import", 0.0) or 0.0 for row in price_data_snap]
            export_prices_raw = [row.get("export", 0.0) or 0.0 for row in price_data_snap]
            timestamps_raw = [row.get("time", f"{(i * 30) // 60:02d}:{(i * 30) % 60:02d}") for i, row in enumerate(chart_data)]

            # Load today's solar forecast from InfluxDB
            tz = ZoneInfo(config.app.timezone)
            today_date = datetime.now(tz).date()
            settings = get_forecast_settings(config.app.auth_db_path)

            solar_forecast_today = None
            if settings.collect_solcast:
                solar_forecast_today = await asyncio.to_thread(
                    load_solar_forecast_influx, config, today_date, source="solcast"
                )
            if solar_forecast_today is None and settings.collect_forecast_solar:
                solar_forecast_today = await asyncio.to_thread(
                    load_solar_forecast_influx, config, today_date, source="forecast_solar"
                )
            if solar_forecast_today is None:
                solar_forecast_today = []

            # Normalise all source lists to exactly 48 entries before stitching
            actual_solar = (actual_solar_raw + [0.0] * 48)[:48]
            actual_usage = (actual_usage_raw + [0.0] * 48)[:48]
            predicted_usage = (predicted_usage_raw + [0.0] * 48)[:48]
            solar_forecast_today = (solar_forecast_today + [0.0] * 48)[:48]
            agile_prices = (agile_prices_raw + [0.0] * 48)[:48]
            export_prices = (export_prices_raw + [0.0] * 48)[:48]
            timestamps = (timestamps_raw + [f"{(i * 30) // 60:02d}:{(i * 30) % 60:02d}" for i in range(48)])[:48]

            # Stitch: actuals for past slots, forecast for future
            solar_48 = actual_solar[:current_slot] + solar_forecast_today[current_slot:]
            load_48 = actual_usage[:current_slot] + predicted_usage[current_slot:]

            # Battery SOC array: only index `current_slot` matters (used as initial SOC by simulate)
            soc_48 = [0.0] * 48
            soc_48[current_slot] = battery_soc_kwh

            forecast = _TodayForecast(
                agile_prices=agile_prices,
                export_prices=export_prices,
                solar_forecast=solar_48,
                load_forecast=load_48,
                battery_soc_forecast=soc_48,
            )
        else:
            forecast = await asyncio.to_thread(load_strategy)
            if forecast is None:
                async with self:
                    self.evaluation_error = "No forecast available — run the optimizer first."
                    self.evaluation_loading = False
                return
            if forecast.window_start:
                ws = datetime.fromisoformat(forecast.window_start)
                timestamps = [
                    (ws + timedelta(minutes=t * 30)).strftime("%H:%M")
                    for t in range(48)
                ]
            else:
                timestamps = [
                    f"{(t * 30) // 60:02d}:{(t * 30) % 60:02d}" for t in range(48)
                ]

        try:
            result = await asyncio.to_thread(
                simulate, periods, forecast, config.battery,
                current_slot if today_mode else 0
            )
        except Exception as exc:
            async with self:
                self.evaluation_error = str(exc)
                self.evaluation_loading = False
            return

        capacity_kwh = config.battery.capacity_kwh

        price_data = []
        for t in range(48):
            mode_label = "Charge" if result.charge_mode_slots[t] else "Self Use"
            price = result.agile_prices[t]
            price_data.append({
                "time": timestamps[t],
                "price": price,
                "mode": mode_label,
                "price_charge": price if mode_label == "Charge" else 0.0,
                "price_self_use_explicit": price if mode_label == "Self Use" else 0.0,
                "price_self_use_implicit": 0.0,
            })

        solar_data = [
            {
                "time": timestamps[t],
                "solar": result.solar_forecast[t],
                "soc_pct": round(result.battery_soc_forecast[t] / capacity_kwh * 100, 1) if capacity_kwh else 0.0,
            }
            for t in range(48)
        ]

        async with self:
            self.evaluation_result_cost = round(result.estimated_cost_gbp, 2)
            self.evaluation_solar_kwh = round(result.solar_forecast_kwh, 1)
            self.evaluation_grid_import_kwh = round(result.grid_import_kwh, 1)
            self.evaluation_price_data = price_data
            self.evaluation_solar_data = solar_data
            self.evaluation_has_result = True
            self.evaluation_loading = False

    @rx.event(background=True)
    async def refresh_strategy(self):
        async with self:
            self.strategy_loading = True
            self.strategy_error = ""

        config = _get_config()
        tz = ZoneInfo(config.app.timezone)
        tomorrow = _tomorrow(config)
        today = datetime.now(tz).date()

        try:
            agile_tomorrow = await asyncio.to_thread(fetch_agile_prices, config, tomorrow)
        except Exception as exc:
            async with self:
                self.strategy_error = f"Could not fetch tomorrow's prices: {exc}"
                self.strategy_loading = False
            return

        if not config.app.test_strategy_mode and not _prices_published(agile_tomorrow):
            async with self:
                self.strategy_loading = False
            yield rx.toast.warning(
                "Tomorrow's Agile prices aren't available yet — try after 16:00.",
                duration=6000,
                close_button=True,
            )
            return

        try:
            from solariq.data.influx import save_solar_forecast_influx

            current_slot, window_start = current_window_start(config.app.timezone)
            settings = get_forecast_settings(config.app.auth_db_path)

            agile_today = await asyncio.to_thread(fetch_agile_prices, config, today)
            export_today = await asyncio.to_thread(fetch_export_prices, config, today)
            export_tomorrow = export_today if config.app.test_strategy_mode else await asyncio.to_thread(fetch_export_prices, config, tomorrow)

            solcast_today = None
            solcast_tomorrow = None
            if settings.collect_solcast:
                solcast_today = await asyncio.to_thread(load_solar_forecast_influx, config, today, source="solcast")
                solcast_tomorrow = await asyncio.to_thread(load_solar_forecast_influx, config, tomorrow, source="solcast")
            if settings.collect_solcast and solcast_tomorrow is None:
                try:
                    solcast_tomorrow = await asyncio.to_thread(fetch_solar_forecast, config, tomorrow)
                    try:
                        await asyncio.to_thread(save_solar_forecast_influx, config, solcast_tomorrow, tomorrow, source="solcast")
                    except Exception as exc:
                        logging.getLogger(__name__).warning("failed to cache tomorrow's Solcast forecast: %s", exc)
                except Exception:
                    solcast_tomorrow = None

            forecast_solar_today = None
            forecast_solar_tomorrow = None
            if settings.collect_forecast_solar:
                forecast_solar_today = await asyncio.to_thread(load_solar_forecast_influx, config, today, source="forecast_solar")
                forecast_solar_tomorrow = await asyncio.to_thread(load_solar_forecast_influx, config, tomorrow, source="forecast_solar")
            if settings.collect_forecast_solar and forecast_solar_tomorrow is None:
                try:
                    forecast_solar_tomorrow = await asyncio.to_thread(fetch_forecast_solar, config, tomorrow)
                    try:
                        await asyncio.to_thread(
                            save_solar_forecast_influx,
                            config,
                            forecast_solar_tomorrow,
                            tomorrow,
                            "forecast_solar",
                        )
                    except Exception as exc:
                        logging.getLogger(__name__).warning("failed to cache tomorrow's forecast.solar forecast: %s", exc)
                except Exception:
                    forecast_solar_tomorrow = None

            solar_today, _ = _select_forecast_slots(
                settings.optimization_source,
                solcast_today,
                forecast_solar_today,
            )
            solar_tomorrow, solar_estimated = _select_forecast_slots(
                settings.optimization_source,
                solcast_tomorrow,
                forecast_solar_tomorrow,
            )

            load_today = await asyncio.to_thread(build_load_profile, config, today)
            load_tomorrow = await asyncio.to_thread(build_load_profile, config, tomorrow)

            agile_for_today = fill_unpublished_slots(agile_today) if config.app.test_strategy_mode else agile_today
            agile_for_tomorrow = fill_unpublished_slots(agile_today) if config.app.test_strategy_mode else agile_tomorrow
            export_today_eff = fill_unpublished_slots(export_today) if config.app.test_strategy_mode else export_today
            export_tomorrow_eff = fill_unpublished_slots(export_tomorrow) if config.app.test_strategy_mode else export_tomorrow
            agile = build_rolling_window(agile_for_today, agile_for_tomorrow, current_slot)
            export = build_rolling_window(export_today_eff, export_tomorrow_eff, current_slot)
            solar = build_rolling_window(solar_today, solar_tomorrow, current_slot)
            load = build_rolling_window(load_today, load_tomorrow, current_slot)

            today_data = await asyncio.to_thread(get_today_live_data, config)
            initial_soc = today_data.battery_soc_kwh or (config.battery.capacity_kwh * 0.5)

            result = await asyncio.to_thread(
                solve, agile, export, solar, load, initial_soc, config, window_start
            )
            result.solar_forecast_estimated = solar_estimated
            await asyncio.to_thread(save_strategy, result)

            async with self:
                self._apply_strategy(result, config.battery.capacity_kwh)
                self.strategy_loading = False

            valid_dt = datetime.fromisoformat(result.valid_until)
            valid_str = valid_dt.strftime("%H:%M %d %b")
            yield rx.toast.success(
                f"Strategy calculated — valid until {valid_str}, estimated cost £{result.estimated_cost_gbp:.2f}",
                duration=0,
                close_button=True,
            )
        except Exception as exc:
            async with self:
                self.strategy_error = str(exc)
                self.strategy_loading = False

    @rx.event(background=True)
    async def refresh_today_data(self):
        """Poll the worker-produced today snapshot every 30 s.

        Primary path: reads cache/today.json written by the worker process.
        Fallback: if no snapshot exists yet (worker not running or first startup),
        fetches directly so the app works standalone in development.
        Also picks up strategy updates written by the worker without any
        separate polling loop.
        """
        async with self:
            if self.today_poll_running:
                return
            self.today_poll_running = True
            self.today_loading = True
            self.today_poll_generation += 1
            my_gen = self.today_poll_generation

        last_strategy_valid_until: str = self.strategy_valid_until
        last_known_date: date | None = None
        last_weather_fetch_at: datetime | None = None

        try:
            while True:
                async with self:
                    if self.today_poll_generation != my_gen:
                        return
                    if not self.current_user:
                        self.today_loading = False
                        return

                # Keep per-instance settings state aligned with shared SQLite state.
                latest_settings = await asyncio.to_thread(self._read_forecast_settings_from_db)
                async with self:
                    self._apply_forecast_settings(latest_settings)

                poll_interval = 30
                try:
                    config = _get_config()
                    tz = ZoneInfo(config.app.timezone)
                    now_local = datetime.now(tz)
                    today_local = now_local.date()

                    # Detect date rollover — reset today's data so stale figures don't linger
                    if last_known_date is not None and today_local != last_known_date:
                        async with self:
                            self.battery_soc_pct = 0.0
                            self.battery_soc_kwh = 0.0
                            self.solar_today_kwh = 0.0
                            self.grid_import_today_kwh = 0.0
                            self.grid_export_today_kwh = 0.0
                            self.grid_cost_gbp = 0.0
                            self.grid_export_revenue_gbp = 0.0
                            self.net_daily_cost_gbp = 0.0
                            self.current_rate_p = 0.0
                            self.current_export_rate_p = 0.0
                            self.today_chart_data = []
                            self.today_price_data = []
                            self.today_error = ""
                            self.today_weather_code = -1
                            self.today_weather_max_temp_c = 0.0
                        last_weather_fetch_at = None
                    last_known_date = today_local

                    snapshot = await asyncio.to_thread(load_today_snapshot)

                    if snapshot:
                        # Ignore snapshots written before today (worker hasn't ticked yet)
                        fetched_at_str = snapshot.get("fetched_at", "")
                        if fetched_at_str:
                            fetched_date = datetime.fromisoformat(fetched_at_str).astimezone(tz).date()
                            if fetched_date < today_local:
                                snapshot = None

                    if snapshot:
                        if snapshot.get("error"):
                            async with self:
                                self.today_error = snapshot["error"]
                                self.today_loading = False
                        else:
                            async with self:
                                self.battery_soc_pct = snapshot.get("battery_soc_pct", 0.0)
                                self.battery_soc_kwh = snapshot.get("battery_soc_kwh", 0.0)
                                self.solar_today_kwh = snapshot.get("solar_today_kwh", 0.0)
                                self.grid_import_today_kwh = snapshot.get("grid_import_today_kwh", 0.0)
                                self.grid_export_today_kwh = snapshot.get("grid_export_today_kwh", 0.0)
                                self.grid_cost_gbp = snapshot.get("grid_cost_gbp", 0.0)
                                self.grid_export_revenue_gbp = snapshot.get("grid_export_revenue_gbp", 0.0)
                                self.net_daily_cost_gbp = snapshot.get("net_daily_cost_gbp", 0.0)
                                self.standing_charge_p_per_day = snapshot.get("standing_charge_p_per_day", 0.0)
                                self.current_rate_p = snapshot.get("current_rate_p", 0.0)
                                self.current_export_rate_p = snapshot.get("current_export_rate_p", 0.0)
                                self.today_chart_data = snapshot.get("chart_data", [])
                                self.today_price_data = snapshot.get("price_data", [])
                                self.today_error = ""
                                self.today_loading = False

                    else:
                    # Worker not running — fall back to a direct fetch so dev / standalone
                    # mode still works.
                        poll_interval = 300
                        try:
                            r = await _fetch_today_direct(config, today_local, log_context=" in fallback")
                            async with self:
                                self.battery_soc_pct = r.battery_soc_pct
                                self.battery_soc_kwh = r.battery_soc_kwh
                                self.solar_today_kwh = r.solar_today_kwh
                                self.grid_import_today_kwh = r.grid_import_today_kwh
                                self.grid_export_today_kwh = r.grid_export_today_kwh
                                self.grid_cost_gbp = r.grid_cost_gbp
                                self.grid_export_revenue_gbp = r.grid_export_revenue_gbp
                                self.net_daily_cost_gbp = r.net_daily_cost_gbp
                                self.standing_charge_p_per_day = r.standing_charge_p_per_day
                                self.current_rate_p = r.current_rate_p
                                self.current_export_rate_p = r.current_export_rate_p
                                self.today_chart_data = r.chart_data
                                self.today_price_data = r.price_data
                                self.today_error = ""
                                self.today_loading = False
                        except Exception as exc:
                            async with self:
                                self.today_error = str(exc)
                                self.today_loading = False

                    # Refresh weather at most every 15 minutes, or immediately if unknown.
                    async with self:
                        need_weather = self.today_weather_code < 0
                    if not need_weather and last_weather_fetch_at is not None:
                        need_weather = (now_local - last_weather_fetch_at) >= timedelta(minutes=15)
                    if need_weather:
                        try:
                            code, max_temp = await asyncio.to_thread(fetch_today_weather, config)
                            async with self:
                                self.today_weather_code = code
                                self.today_weather_max_temp_c = max_temp
                            last_weather_fetch_at = now_local
                        except Exception as exc:
                            logging.getLogger(__name__).warning("weather fetch failed: %s", exc)

                    # Pick up strategy updates written by the worker without a separate loop
                    cached = await asyncio.to_thread(load_strategy)
                    if cached and cached.valid_until != last_strategy_valid_until:
                        last_strategy_valid_until = cached.valid_until
                        async with self:
                            self._apply_strategy(cached, config.battery.capacity_kwh)
                        valid_str = datetime.fromisoformat(cached.valid_until).strftime("%H:%M %d %b")
                        yield rx.toast.success(
                            f"Strategy updated — valid until {valid_str}, estimated cost £{cached.estimated_cost_gbp:.2f}",
                            duration=0,
                            close_button=True,
                        )

                except Exception as exc:
                    # Catch-all so the polling loop never dies silently
                    logging.getLogger(__name__).error("refresh_today_data loop error: %s", exc, exc_info=True)

                await asyncio.sleep(poll_interval)
        finally:
            async with self:
                if self.today_poll_generation == my_gen:
                    self.today_poll_running = False

    @rx.event(background=True)
    async def refresh_today_now(self):
        """Immediately refresh today data and populate any missing forecast caches.

        Unlike the normal polling path, this bypasses the worker snapshot and fetches
        live data directly so the Refresh button can warm missing Solcast and
        forecast.solar caches on demand.
        """
        config = _get_config()
        tz = ZoneInfo(config.app.timezone)
        today_local = datetime.now(tz).date()

        async with self:
            self.today_loading = True
            self.today_error = ""

        try:
            r = await _fetch_today_direct(config, today_local, log_context=" on manual refresh")
            async with self:
                self.battery_soc_pct = r.battery_soc_pct
                self.battery_soc_kwh = r.battery_soc_kwh
                self.solar_today_kwh = r.solar_today_kwh
                self.grid_import_today_kwh = r.grid_import_today_kwh
                self.grid_export_today_kwh = r.grid_export_today_kwh
                self.grid_cost_gbp = r.grid_cost_gbp
                self.grid_export_revenue_gbp = r.grid_export_revenue_gbp
                self.net_daily_cost_gbp = r.net_daily_cost_gbp
                self.standing_charge_p_per_day = r.standing_charge_p_per_day
                self.current_rate_p = r.current_rate_p
                self.current_export_rate_p = r.current_export_rate_p
                self.today_chart_data = r.chart_data
                self.today_price_data = r.price_data
                self.today_error = ""
                self.today_loading = False

            # Manual refresh should also update weather immediately.
            try:
                code, max_temp = await asyncio.to_thread(fetch_today_weather, config)
                async with self:
                    self.today_weather_code = code
                    self.today_weather_max_temp_c = max_temp
            except Exception as exc:
                logging.getLogger(__name__).warning("weather fetch failed on manual refresh: %s", exc)

            yield rx.toast.success(
                "Today data refreshed.",
                duration=3000,
                close_button=True,
            )
        except Exception as exc:
            async with self:
                self.today_error = str(exc)
                self.today_loading = False

    @rx.event
    def restart_today_polling(self):
        self.today_poll_generation += 1
        self.today_poll_running = False
        self.today_loading = False
        yield AppState.refresh_today_data
