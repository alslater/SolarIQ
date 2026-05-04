from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path


@dataclass
class InfluxConfig:
    host: str
    port: int
    database: str
    solar_database: str
    solax_database: str
    solcast_forecast_database: str


@dataclass
class OctopusConfig:
    api_key: str
    agile_rate_url: str
    agile_export_url: str
    standing_charge_p_per_day: float = 50.0  # pence/day — update in solariq.ini
    export_mpan: str = ""
    export_serial_number: str = ""


@dataclass
class SolcastConfig:
    api_key: str
    resource_id: str


@dataclass
class BatteryConfig:
    capacity_kwh: float
    min_soc_pct: int
    max_charge_kw: float

    @property
    def min_soc_kwh(self) -> float:
        return self.capacity_kwh * self.min_soc_pct / 100

    @property
    def max_charge_kwh_per_slot(self) -> float:
        return self.max_charge_kw / 2  # 30-min slots


@dataclass
class AppConfig:
    timezone: str
    refresh_time: str  # "HH:MM"
    cache_dir: str = "cache"
    auth_db_path: str = "data/auth.sqlite3"
    auth_cookie_secure: bool = False
    log_file: str = ""  # empty = stdout
    log_level: str = "INFO"
    test_strategy_mode: bool = False  # substitute today's rates for tomorrow's when True


@dataclass
class LocationConfig:
    latitude: float
    longitude: float


@dataclass
class SolarIQConfig:
    influxdb: InfluxConfig
    octopus: OctopusConfig
    solcast: SolcastConfig
    battery: BatteryConfig
    app: AppConfig
    location: LocationConfig


def load_config(path: str = "solariq.ini") -> SolarIQConfig:
    if not Path(path).exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    parser = ConfigParser()
    parser.read(path)
    return SolarIQConfig(
        influxdb=InfluxConfig(
            host=parser.get("influxdb", "host", fallback="localhost"),
            port=parser.getint("influxdb", "port", fallback=8086),
            database=parser.get("influxdb", "database", fallback="energy"),
            solar_database=parser.get("influxdb", "solar_database", fallback="solar"),
            solax_database=parser.get("influxdb", "solax_database", fallback="solax"),
            solcast_forecast_database=parser.get("influxdb", "solcast_forecast_database", fallback="solcast"),
        ),
        octopus=OctopusConfig(
            api_key=parser.get("octopus", "api_key"),
            agile_rate_url=parser.get("octopus", "agile_rate_url"),
            agile_export_url=parser.get("octopus", "agile_export_url"),
            standing_charge_p_per_day=parser.getfloat("octopus", "standing_charge_p_per_day", fallback=50.0),
            export_mpan=parser.get("octopus", "export_mpan", fallback=""),
            export_serial_number=parser.get("octopus", "export_serial_number", fallback=""),
        ),
        solcast=SolcastConfig(
            api_key=parser.get("solcast", "api_key"),
            resource_id=parser.get("solcast", "resource_id"),
        ),
        battery=BatteryConfig(
            capacity_kwh=parser.getfloat("battery", "capacity_kwh", fallback=23.2),
            min_soc_pct=parser.getint("battery", "min_soc_pct", fallback=10),
            max_charge_kw=parser.getfloat("battery", "max_charge_kw", fallback=7.5),
        ),
        app=AppConfig(
            timezone=parser.get("app", "timezone", fallback="Europe/London"),
            refresh_time=parser.get("app", "refresh_time", fallback="16:15"),
            cache_dir=parser.get("app", "cache_dir", fallback="cache"),
            auth_db_path=parser.get("app", "auth_db_path", fallback="data/auth.sqlite3"),
            auth_cookie_secure=parser.getboolean("app", "auth_cookie_secure", fallback=False),
            log_file=parser.get("app", "log_file", fallback=""),
            log_level=parser.get("app", "log_level", fallback="INFO"),
            test_strategy_mode=parser.getboolean("app", "test_strategy_mode", fallback=False),
        ),
        location=LocationConfig(
            latitude=parser.getfloat("location", "latitude", fallback=50.89),
            longitude=parser.getfloat("location", "longitude", fallback=0.32),
        ),
    )
