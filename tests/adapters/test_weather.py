from unittest.mock import MagicMock, patch

from tests.conftest import make_full_topic
from tracker.adapters.weather import WeatherAdapter
from tracker.models import SourceConfig

TOPIC = make_full_topic()

SOURCE_NYC = SourceConfig(
    source="weather",
    filters={"lat": 40.7128, "lon": -74.0060, "location_name": "New York City"},
)

OPEN_METEO_RESPONSE = {
    "daily": {
        "time": ["2026-03-23", "2026-03-24", "2026-03-25"],
        "weathercode": [0, 95, 61],        # clear, thunderstorm, rain
        "temperature_2m_max": [15.0, 12.0, 10.0],
        "precipitation_sum": [0.0, 18.5, 8.2],
    },
    "daily_units": {
        "temperature_2m_max": "°C",
        "precipitation_sum": "mm",
    },
}


def _mock_get(json_data, status_code=200):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock(
        side_effect=None if status_code < 400 else Exception(f"HTTP {status_code}")
    )
    return resp


def test_notable_only_filters_clear_days():
    with patch("tracker.adapters.weather.requests.get") as mock_get:
        mock_get.return_value = _mock_get(OPEN_METEO_RESPONSE)
        results = WeatherAdapter().fetch(SOURCE_NYC, TOPIC)
    # Day 0 (clear, code 0) is not notable — only day 1 (thunderstorm 95) returned
    assert len(results) == 1
    assert "thunderstorm" in results[0].title.lower()


def test_notable_false_returns_all_days():
    source = SourceConfig(
        source="weather",
        filters={
            "lat": 40.7128, "lon": -74.0060,
            "location_name": "NYC", "notable_only": False,
        },
    )
    with patch("tracker.adapters.weather.requests.get") as mock_get:
        mock_get.return_value = _mock_get(OPEN_METEO_RESPONSE)
        results = WeatherAdapter().fetch(source, TOPIC)
    # notable_only=False returns all 3 days
    assert len(results) == 3


def test_missing_lat_lon_returns_empty():
    source = SourceConfig(source="weather", filters={"location_name": "Nowhere"})
    results = WeatherAdapter().fetch(source, TOPIC)
    assert results == []


def test_http_error_returns_empty():
    with patch("tracker.adapters.weather.requests.get") as mock_get:
        mock_get.side_effect = Exception("timeout")
        results = WeatherAdapter().fetch(SOURCE_NYC, TOPIC)
    assert results == []


def test_source_type_is_weather():
    with patch("tracker.adapters.weather.requests.get") as mock_get:
        mock_get.return_value = _mock_get(OPEN_METEO_RESPONSE)
        results = WeatherAdapter().fetch(SOURCE_NYC, TOPIC)
    assert all(r.source_type == "weather" for r in results)


def test_location_name_in_title():
    with patch("tracker.adapters.weather.requests.get") as mock_get:
        mock_get.return_value = _mock_get(OPEN_METEO_RESPONSE)
        results = WeatherAdapter().fetch(SOURCE_NYC, TOPIC)
    assert "New York City" in results[0].title
