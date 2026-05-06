from dataclasses import dataclass, field
from typing import Literal


@dataclass
class StrategyPeriod:
    period_num: int
    start_time: str                          # "HH:MM"
    end_time: str                            # "HH:MM"
    mode: Literal["Self Use", "Charge", "Battery Standby"]
    min_soc_pct: int = 10                    # Self Use only
    target_soc_pct: int = 0                  # Charge only
    max_charge_w: int = 0                    # Charge only
    avg_price_p: float = 0.0                 # average Agile price over this period
    is_default: bool = False                 # True when this uses inverter default (Self Use 10%)

    def to_dict(self) -> dict:
        return {
            "period_num": self.period_num,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "mode": self.mode,
            "min_soc_pct": self.min_soc_pct,
            "target_soc_pct": self.target_soc_pct,
            "max_charge_w": self.max_charge_w,
            "avg_price_p": round(self.avg_price_p, 2),
            "is_default": self.is_default,
        }


@dataclass
class OptimizationResult:
    periods: list[StrategyPeriod]
    estimated_cost_gbp: float
    solar_forecast_kwh: float
    grid_import_kwh: float
    computed_at: str                         # ISO8601 UTC
    valid_until: str                         # ISO8601 local datetime when window expires
    window_start: str                        # ISO8601 local datetime of slot 0
    agile_prices: list[float]               # 48 values, p/kWh
    export_prices: list[float]              # 48 values, p/kWh
    solar_forecast: list[float]             # 48 values, kWh/slot
    load_forecast: list[float]              # 48 values, kWh/slot
    battery_soc_forecast: list[float]       # 48 values, kWh
    grid_import_forecast: list[float]       # 48 values, kWh
    charge_mode_slots: list[bool]           # 48 values
    standby_mode_slots: list[bool]          # 48 values, True = Battery Standby
    solar_forecast_estimated: bool = False  # True when Solcast unavailable and zeros were used

    def to_dict(self) -> dict:
        return {
            "periods": [p.to_dict() for p in self.periods],
            "estimated_cost_gbp": self.estimated_cost_gbp,
            "solar_forecast_kwh": self.solar_forecast_kwh,
            "grid_import_kwh": self.grid_import_kwh,
            "computed_at": self.computed_at,
            "valid_until": self.valid_until,
            "window_start": self.window_start,
            "agile_prices": self.agile_prices,
            "export_prices": self.export_prices,
            "solar_forecast": self.solar_forecast,
            "load_forecast": self.load_forecast,
            "battery_soc_forecast": self.battery_soc_forecast,
            "grid_import_forecast": self.grid_import_forecast,
            "charge_mode_slots": self.charge_mode_slots,
            "standby_mode_slots": self.standby_mode_slots,
            "solar_forecast_estimated": self.solar_forecast_estimated,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OptimizationResult":
        periods = [
            StrategyPeriod(**{k: v for k, v in p.items()})
            for p in d["periods"]
        ]
        return cls(
            periods=periods,
            estimated_cost_gbp=d["estimated_cost_gbp"],
            solar_forecast_kwh=d["solar_forecast_kwh"],
            grid_import_kwh=d["grid_import_kwh"],
            computed_at=d["computed_at"],
            valid_until=d.get("valid_until", d.get("target_date", "")),
            window_start=d.get("window_start", ""),
            agile_prices=d["agile_prices"],
            export_prices=d["export_prices"],
            solar_forecast=d["solar_forecast"],
            load_forecast=d["load_forecast"],
            battery_soc_forecast=d["battery_soc_forecast"],
            grid_import_forecast=d["grid_import_forecast"],
            charge_mode_slots=d["charge_mode_slots"],
            standby_mode_slots=d.get("standby_mode_slots", [False] * 48),
            solar_forecast_estimated=d.get("solar_forecast_estimated", False),
        )


@dataclass
class TodayLiveData:
    battery_soc_kwh: float
    battery_soc_pct: float
    solar_today_kwh: float
    grid_cost_pence: float
    grid_export_revenue_pence: float
    current_rate_p: float
    current_export_rate_p: float
    last_data_slot: int                      # index of last slot with actual data (0-47)
    timestamps: list[str]                    # 48 "HH:MM" strings
    actual_usage: list[float | None]         # kWh, None for future slots
    actual_solar: list[float | None]
    actual_battery_soc_kwh: list[float | None]
    actual_grid_import: list[float | None]
    actual_grid_export: list[float | None]
    agile_prices: list[float]               # 48 values (may include future)
    export_prices: list[float]              # 48 values (may include future)
    predicted_usage: list[float]            # 48 values (load profile)

    def to_dict(self) -> dict:
        return {
            "battery_soc_kwh": self.battery_soc_kwh,
            "battery_soc_pct": self.battery_soc_pct,
            "solar_today_kwh": self.solar_today_kwh,
            "grid_cost_pence": self.grid_cost_pence,
            "grid_export_revenue_pence": self.grid_export_revenue_pence,
            "current_rate_p": self.current_rate_p,
            "current_export_rate_p": self.current_export_rate_p,
            "last_data_slot": self.last_data_slot,
            "timestamps": self.timestamps,
            "actual_usage": [v if v is not None else 0.0 for v in self.actual_usage],
            "actual_solar": [v if v is not None else 0.0 for v in self.actual_solar],
            "actual_battery_soc_kwh": [v if v is not None else 0.0 for v in self.actual_battery_soc_kwh],
            "actual_grid_import": [v if v is not None else 0.0 for v in self.actual_grid_import],
            "actual_grid_export": [v if v is not None else 0.0 for v in self.actual_grid_export],
            "agile_prices": self.agile_prices,
            "export_prices": self.export_prices,
            "predicted_usage": self.predicted_usage,
        }
