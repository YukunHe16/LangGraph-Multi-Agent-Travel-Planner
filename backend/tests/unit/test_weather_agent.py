"""Unit tests for C3 WeatherAgent — pluggable provider integration.

Tests verify:
- Weather fetch via map provider → per-day WeatherInfo list
- Fallback when weather API returns empty
- Fallback when weather API raises exception
- Day expansion matches travel_days count
- as_worker() protocol compliance with PlannerState
- Provider accessed via registry (not hard-coded service)
- Temperature variation across days
- Real forecast data used when available
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.workers.weather_agent import (
    WeatherAgent,
    _FALLBACK_WEATHER,
)
from app.models.schemas import TripRequest, WeatherInfo


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_request(**overrides: Any) -> TripRequest:
    """Build a minimal valid TripRequest with sensible defaults."""
    defaults = {
        "city": "北京",
        "start_date": "2026-06-01",
        "end_date": "2026-06-03",
        "travel_days": 3,
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
        "preferences": [],
    }
    defaults.update(overrides)
    return TripRequest(**defaults)


def _make_weather(date: str = "2026-06-01", **overrides: Any) -> WeatherInfo:
    """Create a stub WeatherInfo."""
    defaults = {
        "date": date,
        "day_weather": "晴",
        "night_weather": "多云",
        "day_temp": 30,
        "night_temp": 20,
        "wind_direction": "南风",
        "wind_power": "2级",
    }
    defaults.update(overrides)
    return WeatherInfo(**defaults)


def _make_registry_mock(
    weather: list[WeatherInfo] | None = None,
    weather_raises: bool = False,
) -> MagicMock:
    """Create a mock ProviderRegistry with map weather stub."""
    registry = MagicMock()

    if weather_raises:
        registry.map.get_weather.side_effect = RuntimeError("Weather API down")
    else:
        registry.map.get_weather.return_value = weather or []

    registry.map.provider_name = "amap"
    return registry


# ---------------------------------------------------------------------------
# Tests: Core run() with real weather data
# ---------------------------------------------------------------------------

class TestWeatherFromAPI:
    """Verify weather generation from successful API calls."""

    def test_returns_weather_per_day(self) -> None:
        weather = [_make_weather(f"2026-06-0{i+1}") for i in range(3)]
        registry = _make_registry_mock(weather=weather)
        agent = WeatherAgent(registry=registry)

        result = agent.run(_make_request())

        assert len(result) == 3
        assert all(isinstance(w, WeatherInfo) for w in result)

    def test_dates_match_trip_days(self) -> None:
        weather = [_make_weather("2026-06-01")]
        registry = _make_registry_mock(weather=weather)
        agent = WeatherAgent(registry=registry)

        result = agent.run(_make_request())

        assert result[0].date == "2026-06-01"
        assert result[1].date == "2026-06-02"
        assert result[2].date == "2026-06-03"

    def test_uses_real_forecast_when_available(self) -> None:
        weather = [
            _make_weather("2026-06-01", day_weather="雨", night_weather="暴雨"),
            _make_weather("2026-06-02", day_weather="阴", night_weather="小雨"),
            _make_weather("2026-06-03", day_weather="晴", night_weather="晴"),
        ]
        registry = _make_registry_mock(weather=weather)
        agent = WeatherAgent(registry=registry)

        result = agent.run(_make_request())

        assert result[0].day_weather == "雨"
        assert result[1].day_weather == "阴"
        assert result[2].day_weather == "晴"

    def test_cycles_fallback_when_fewer_forecasts(self) -> None:
        weather = [_make_weather("2026-06-01", day_weather="雨")]
        registry = _make_registry_mock(weather=weather)
        agent = WeatherAgent(registry=registry)

        result = agent.run(_make_request(travel_days=5, end_date="2026-06-05"))

        # First day uses real forecast; rest cycle the first entry
        assert result[0].day_weather == "雨"
        # Days beyond forecast count use fallback (first entry)
        assert result[3].day_weather == "雨"

    def test_calls_provider_with_city(self) -> None:
        registry = _make_registry_mock(weather=[])
        agent = WeatherAgent(registry=registry)

        agent.run(_make_request(city="上海"))

        registry.map.get_weather.assert_called_once_with("上海")


# ---------------------------------------------------------------------------
# Tests: Temperature variation
# ---------------------------------------------------------------------------

class TestTemperatureVariation:
    """Verify slight temperature variation across days."""

    def test_day_temp_varies(self) -> None:
        weather = [_make_weather(day_temp=30)]
        registry = _make_registry_mock(weather=weather)
        agent = WeatherAgent(registry=registry)

        result = agent.run(_make_request())

        # Day 0: base + 0, Day 1: base + 1, Day 2: base + 0
        assert result[0].day_temp == 30
        assert result[1].day_temp == 31
        assert result[2].day_temp == 30

    def test_night_temp_varies(self) -> None:
        weather = [_make_weather(night_temp=20)]
        registry = _make_registry_mock(weather=weather)
        agent = WeatherAgent(registry=registry)

        result = agent.run(_make_request())

        # Day 0: base - 0, Day 1: base - 1, Day 2: base - 0
        assert result[0].night_temp == 20
        assert result[1].night_temp == 19
        assert result[2].night_temp == 20


# ---------------------------------------------------------------------------
# Tests: Fallback (no weather data)
# ---------------------------------------------------------------------------

class TestFallback:
    """Verify deterministic fallback when weather API returns nothing."""

    def test_empty_weather_uses_fallback(self) -> None:
        registry = _make_registry_mock(weather=[])
        agent = WeatherAgent(registry=registry)

        result = agent.run(_make_request())

        assert len(result) == 3
        assert result[0].day_weather == _FALLBACK_WEATHER.day_weather
        assert result[0].night_weather == _FALLBACK_WEATHER.night_weather

    def test_fallback_dates_correct(self) -> None:
        registry = _make_registry_mock(weather=[])
        agent = WeatherAgent(registry=registry)

        result = agent.run(_make_request())

        assert result[0].date == "2026-06-01"
        assert result[2].date == "2026-06-03"

    def test_exception_triggers_fallback(self) -> None:
        registry = _make_registry_mock(weather_raises=True)
        agent = WeatherAgent(registry=registry)

        result = agent.run(_make_request())

        assert len(result) == 3
        assert result[0].day_weather == _FALLBACK_WEATHER.day_weather

    def test_fallback_wind_info(self) -> None:
        registry = _make_registry_mock(weather=[])
        agent = WeatherAgent(registry=registry)

        result = agent.run(_make_request())

        assert result[0].wind_direction == _FALLBACK_WEATHER.wind_direction
        assert result[0].wind_power == _FALLBACK_WEATHER.wind_power


# ---------------------------------------------------------------------------
# Tests: as_worker() WorkerFn protocol
# ---------------------------------------------------------------------------

class TestAsWorker:
    """Verify as_worker() returns a valid WorkerFn for PlannerAgent."""

    def test_worker_returns_dict_with_weather_info_key(self) -> None:
        weather = [_make_weather()]
        registry = _make_registry_mock(weather=weather)
        agent = WeatherAgent(registry=registry)
        worker = agent.as_worker()

        state = {"request": _make_request().model_dump()}
        result = worker(state)

        assert "weather_info" in result
        assert isinstance(result["weather_info"], list)

    def test_worker_weather_items_are_dicts(self) -> None:
        weather = [_make_weather()]
        registry = _make_registry_mock(weather=weather)
        agent = WeatherAgent(registry=registry)
        worker = agent.as_worker()

        state = {"request": _make_request().model_dump()}
        result = worker(state)

        assert all(isinstance(w, dict) for w in result["weather_info"])

    def test_worker_weather_dict_has_required_fields(self) -> None:
        weather = [_make_weather()]
        registry = _make_registry_mock(weather=weather)
        agent = WeatherAgent(registry=registry)
        worker = agent.as_worker()

        state = {"request": _make_request().model_dump()}
        result = worker(state)

        w = result["weather_info"][0]
        required = ["date", "day_weather", "night_weather", "day_temp", "night_temp"]
        for field in required:
            assert field in w, f"Missing field: {field}"

    def test_worker_count_matches_travel_days(self) -> None:
        registry = _make_registry_mock(weather=[])
        agent = WeatherAgent(registry=registry)
        worker = agent.as_worker()

        state = {"request": _make_request(travel_days=5, end_date="2026-06-05").model_dump()}
        result = worker(state)

        assert len(result["weather_info"]) == 5


# ---------------------------------------------------------------------------
# Tests: Registry lazy resolution
# ---------------------------------------------------------------------------

class TestRegistryLazy:
    """Verify registry is lazily resolved when not injected."""

    def test_lazy_resolution(self) -> None:
        mock_registry = _make_registry_mock(weather=[])
        agent = WeatherAgent()  # No registry injected

        import app.providers.registry as reg_mod
        with patch.object(reg_mod, "get_provider_registry", return_value=mock_registry) as mock_get:
            agent.run(_make_request())
            mock_get.assert_called_once()

    def test_injected_registry_not_lazily_resolved(self) -> None:
        registry = _make_registry_mock(weather=[])
        agent = WeatherAgent(registry=registry)

        import app.providers.registry as reg_mod
        original_get = reg_mod.get_provider_registry
        call_count = 0

        def tracking_get():
            nonlocal call_count
            call_count += 1
            return original_get()

        reg_mod.get_provider_registry = tracking_get
        try:
            agent.run(_make_request())
            assert call_count == 0
        finally:
            reg_mod.get_provider_registry = original_get


# ---------------------------------------------------------------------------
# Tests: Schema compliance
# ---------------------------------------------------------------------------

class TestSchemaCompliance:
    """Verify output matches WeatherInfo schema contract."""

    def test_all_fields_serializable(self) -> None:
        weather = [_make_weather()]
        registry = _make_registry_mock(weather=weather)
        agent = WeatherAgent(registry=registry)

        result = agent.run(_make_request())

        data = result[0].model_dump()
        assert isinstance(data, dict)
        assert "date" in data
        assert "day_weather" in data

    def test_single_day_trip(self) -> None:
        weather = [_make_weather()]
        registry = _make_registry_mock(weather=weather)
        agent = WeatherAgent(registry=registry)

        result = agent.run(_make_request(travel_days=1, end_date="2026-06-01"))

        assert len(result) == 1
        assert result[0].date == "2026-06-01"
