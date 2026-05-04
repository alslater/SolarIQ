from solariq.config import SolarIQConfig, load_config
from solariq.logging_config import setup_logging

_config: SolarIQConfig | None = None


def get_config() -> SolarIQConfig:
    global _config
    if _config is None:
        _config = load_config()
        setup_logging(_config.app.log_file, _config.app.log_level)
    return _config
