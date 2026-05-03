import logging
from datetime import date

import requests

from solariq.config import SolarIQConfig

logger = logging.getLogger(__name__)

_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_daily_temperatures(config: SolarIQConfig, dates: list[date]) -> dict[date, float]:
    """Return {date: mean_temp_celsius} for each requested date via Open-Meteo.

    Uses the forecast endpoint with past_days to cover historical dates — no API key required.
    Dates not covered by the response are absent from the result.
    """
    if not dates:
        return {}

    today = date.today()
    past_days = max(0, (today - min(dates)).days + 1)
    forecast_days = max(2, (max(dates) - today).days + 2)

    logger.info(
        "fetching temperatures for %d dates (%.1f°N %.1f°E, past_days=%d, forecast_days=%d)",
        len(dates), config.location.latitude, config.location.longitude,
        past_days, forecast_days,
    )

    response = requests.get(
        _FORECAST_URL,
        params={
            "latitude": config.location.latitude,
            "longitude": config.location.longitude,
            "daily": "temperature_2m_mean",
            "past_days": past_days,
            "forecast_days": forecast_days,
            "timezone": config.app.timezone,
        },
        timeout=10,
    )
    response.raise_for_status()
    daily = response.json().get("daily", {})

    result = {
        date.fromisoformat(t): float(v)
        for t, v in zip(daily.get("time", []), daily.get("temperature_2m_mean", []))
        if v is not None
    }
    logger.info("received temperatures for %d dates", len(result))
    return result


def fetch_today_weather(config: SolarIQConfig) -> tuple[int, float]:
    """Return (wmo_weather_code, max_temp_celsius) for today via Open-Meteo. No API key required."""
    today = date.today()
    response = requests.get(
        _FORECAST_URL,
        params={
            "latitude": config.location.latitude,
            "longitude": config.location.longitude,
            "daily": ["weather_code", "temperature_2m_max"],
            "forecast_days": 1,
            "timezone": config.app.timezone,
        },
        timeout=10,
    )
    response.raise_for_status()
    daily = response.json().get("daily", {})
    times = daily.get("time", [])
    codes = daily.get("weather_code", [])
    temps = daily.get("temperature_2m_max", [])
    for t, code, temp in zip(times, codes, temps):
        if date.fromisoformat(t) == today and code is not None:
            logger.info("today weather: code=%d max_temp=%.1f°C", code, temp or 0.0)
            return int(code), float(temp or 0.0)
    logger.warning("no weather data for today from Open-Meteo")
    return -1, 0.0
