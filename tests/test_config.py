import pytest
from solariq.config import load_config


def test_influxdb_config(test_ini_path):
    config = load_config(test_ini_path)
    assert config.influxdb.host == "testhost"
    assert config.influxdb.port == 8086
    assert config.influxdb.database == "energy"
    assert config.influxdb.solar_database == "solar"


def test_octopus_config(test_ini_path):
    config = load_config(test_ini_path)
    assert config.octopus.api_key == "test_octopus_key"
    assert "agile" in config.octopus.agile_rate_url


def test_solcast_config(test_ini_path):
    config = load_config(test_ini_path)
    assert config.solcast.api_key == "test_solcast_key"
    assert config.solcast.resource_id == "test-resource-id"


def test_battery_config(test_ini_path):
    config = load_config(test_ini_path)
    assert config.battery.capacity_kwh == 23.2
    assert config.battery.min_soc_pct == 10
    assert config.battery.max_charge_kw == 7.5


def test_battery_derived_properties(test_ini_path):
    config = load_config(test_ini_path)
    assert config.battery.min_soc_kwh == pytest.approx(2.32)
    assert config.battery.max_charge_kwh_per_slot == pytest.approx(3.75)


def test_app_config(test_ini_path):
    config = load_config(test_ini_path)
    assert config.app.timezone == "Europe/London"
    assert config.app.refresh_time == "16:15"
    assert config.app.cache_dir == "test-cache"
    assert config.app.auth_db_path == "data/auth.sqlite3"
    assert config.app.auth_cookie_secure is True


def test_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/path/solariq.ini")


def test_octopus_export_meter_config(test_ini_path):
    config = load_config(test_ini_path)
    assert config.octopus.export_mpan == "1900092645854"
    assert config.octopus.export_serial_number == "23L3537933"
