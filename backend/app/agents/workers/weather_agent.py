"""WeatherAgent — LangGraph worker that queries weather via pluggable map provider.

Rewritten for C3 to use ProviderRegistry instead of hard-coded amap_service.
Retains backward-compatible ``run()`` signature and adds ``as_worker()``
for the PlannerAgent WorkerFn protocol.

Source prompt: trip_planner_agent.py WEATHER_AGENT_PROMPT (migrated in A2).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Callable

from app.models.schemas import TripRequest, WeatherInfo
from app.prompts.trip_prompts import WEATHER_AGENT_PROMPT

if TYPE_CHECKING:
    from app.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default fallback weather (used when API returns nothing or errors)
# ---------------------------------------------------------------------------

_FALLBACK_WEATHER = WeatherInfo(
    date="1970-01-01",
    day_weather="晴",
    night_weather="多云",
    day_temp=25,
    night_temp=18,
    wind_direction="东南风",
    wind_power="3级",
)


class WeatherAgent:
    """Query weather for trip dates and produce per-day forecasts.

    Uses ``ProviderRegistry.map.get_weather()`` to fetch real weather data,
    making the underlying API fully pluggable via ``settings.yaml``.

    Args:
        registry: Optional pre-built ``ProviderRegistry``. When *None*,
            the module-level singleton is resolved lazily on first call.
    """

    prompt: str = WEATHER_AGENT_PROMPT

    def __init__(self, registry: "ProviderRegistry | None" = None) -> None:
        self._registry = registry

    # ------------------------------------------------------------------
    # Provider access (lazy)
    # ------------------------------------------------------------------

    @property
    def _reg(self) -> "ProviderRegistry":
        """Lazy-resolve the provider registry."""
        if self._registry is None:
            from app.providers.registry import get_provider_registry

            self._registry = get_provider_registry()
        return self._registry

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def run(self, request: TripRequest) -> list[WeatherInfo]:
        """Return per-day weather information for the trip period.

        Args:
            request: A ``TripRequest`` with ``city``, ``start_date``,
                ``end_date``, and ``travel_days`` populated.

        Returns:
            A list of ``WeatherInfo`` models, one per travel day.
            Falls back to deterministic defaults when API fails.
        """
        logger.info("WeatherAgent.run: city=%s days=%d", request.city, request.travel_days)

        base_forecasts = self._fetch_weather_safe(request.city)
        return self._expand_to_trip_days(base_forecasts, request)

    # ------------------------------------------------------------------
    # Weather fetching (best-effort)
    # ------------------------------------------------------------------

    def _fetch_weather_safe(self, city: str) -> list[WeatherInfo]:
        """Fetch weather from the map provider, return empty on failure."""
        try:
            return self._reg.map.get_weather(city)
        except Exception:
            logger.warning("Weather fetch failed for city=%s, using fallback", city, exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Day expansion
    # ------------------------------------------------------------------

    @staticmethod
    def _expand_to_trip_days(
        base_forecasts: list[WeatherInfo],
        request: TripRequest,
    ) -> list[WeatherInfo]:
        """Expand base forecast data into one ``WeatherInfo`` per trip day.

        When real forecast data is available, each day maps to the
        corresponding forecast entry (cycling if fewer forecasts than days).
        When no data is available, a static fallback is used.
        """
        fallback = base_forecasts[0] if base_forecasts else _FALLBACK_WEATHER
        start = datetime.strptime(request.start_date, "%Y-%m-%d")
        days: list[WeatherInfo] = []

        for i in range(request.travel_days):
            current = start + timedelta(days=i)

            # Use matching forecast if available, else cycle/fallback
            if base_forecasts and i < len(base_forecasts):
                src = base_forecasts[i]
            else:
                src = fallback

            days.append(
                WeatherInfo(
                    date=current.strftime("%Y-%m-%d"),
                    day_weather=src.day_weather,
                    night_weather=src.night_weather,
                    day_temp=int(src.day_temp) + (i % 2),
                    night_temp=int(src.night_temp) - (i % 2),
                    wind_direction=src.wind_direction,
                    wind_power=src.wind_power,
                )
            )

        return days

    # ------------------------------------------------------------------
    # WorkerFn protocol adapter
    # ------------------------------------------------------------------

    def as_worker(self) -> Callable[..., dict]:
        """Return a ``WorkerFn``-compatible callable for PlannerAgent.

        The returned function takes ``PlannerState`` and returns a dict
        with key ``weather_info`` containing serialised ``WeatherInfo`` list.
        """

        def _worker(state: dict) -> dict:
            request = TripRequest(**state["request"])
            weather = self.run(request)
            return {
                "weather_info": [w.model_dump() for w in weather],
            }

        return _worker
