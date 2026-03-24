from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from tracker.adapters.base import BaseAdapter
from tracker.models import Result, SourceConfig, TopicConfig

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO Weather Interpretation Codes → human description
_WMO_CODES: dict[int, str] = {
    0: "clear sky",
    1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "icy fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "heavy showers", 82: "violent showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail", 99: "severe thunderstorm with hail",
}

# Codes considered "notable" — worth surfacing as a result
_NOTABLE_CODES = {45, 48, 65, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99}


def _describe(code: int) -> str:
    return _WMO_CODES.get(code, f"weather code {code}")


class WeatherAdapter(BaseAdapter):
    """
    Fetches a 3-day forecast from Open-Meteo (free, global, no credentials).

    Configure in source_config.filters:
        lat:           latitude (float)
        lon:           longitude (float)
        location_name: human-readable name shown in results (string)
        notable_only:  if true (default), only return results for severe/notable
                       weather; if false, always return the daily forecast

    Example topics.yaml entry:
        - source: weather
          filters:
            lat: 40.7128
            lon: -74.0060
            location_name: "New York City"
            notable_only: true
    """

    source_type = "weather"

    def fetch(self, source_config: SourceConfig, topic: TopicConfig) -> list[Result]:
        lat = source_config.filters.get("lat")
        lon = source_config.filters.get("lon")
        if lat is None or lon is None:
            logger.warning(
                "WeatherAdapter: 'lat' and 'lon' required in filters, skipping"
            )
            return []

        location = source_config.filters.get("location_name", f"{lat},{lon}")
        notable_only = source_config.filters.get("notable_only", True)

        try:
            resp = requests.get(
                OPEN_METEO_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "daily": "weathercode,temperature_2m_max,precipitation_sum",
                    "timezone": "auto",
                    "forecast_days": 3,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning("WeatherAdapter error for %s: %s", location, exc)
            return []

        daily = data.get("daily", {})
        times = daily.get("time", [])
        codes = daily.get("weathercode", [])
        temps = daily.get("temperature_2m_max", [])
        precip = daily.get("precipitation_sum", [])
        units = data.get("daily_units", {})
        temp_unit = units.get("temperature_2m_max", "°C")

        results = []
        for date, code, temp, rain in zip(times, codes, temps, precip):
            if notable_only and code not in _NOTABLE_CODES:
                continue
            description = _describe(code)
            title = f"Weather {location}: {description} on {date}"
            snippet = (
                f"{description.capitalize()}, high {temp}{temp_unit}, "
                f"precipitation {rain} {units.get('precipitation_sum', 'mm')}"
            )
            results.append(
                Result(
                    url="https://open-meteo.com",
                    title=title,
                    snippet=snippet,
                    source="open_meteo",
                    source_type=self.source_type,
                    topic_name=topic.name,
                    fetched_at=datetime.now(timezone.utc),
                    raw={"date": date, "code": code, "temp": temp, "precip": rain},
                )
            )
        return results
