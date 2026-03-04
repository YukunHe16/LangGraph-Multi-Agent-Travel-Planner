"""Weather worker migrated from hello-agents and rewritten for LangGraph runtime."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models.schemas import TripRequest, WeatherInfo
from app.prompts.trip_prompts import WEATHER_AGENT_PROMPT
from app.services import get_amap_service


class WeatherAgent:
    """Generate weather timeline for trip dates."""

    prompt: str = WEATHER_AGENT_PROMPT

    def __init__(self) -> None:
        self.amap_service = get_amap_service()

    def run(self, request: TripRequest) -> list[WeatherInfo]:
        """Return per-day weather recommendations."""
        weather_base = self.amap_service.get_weather(request.city)
        fallback = weather_base[0] if weather_base else WeatherInfo(
            date=request.start_date,
            day_weather="晴",
            night_weather="多云",
            day_temp=25,
            night_temp=18,
            wind_direction="东南风",
            wind_power="3级",
        )

        start = datetime.strptime(request.start_date, "%Y-%m-%d")
        days: list[WeatherInfo] = []
        for i in range(request.travel_days):
            current = start + timedelta(days=i)
            days.append(
                WeatherInfo(
                    date=current.strftime("%Y-%m-%d"),
                    day_weather=fallback.day_weather,
                    night_weather=fallback.night_weather,
                    day_temp=int(fallback.day_temp) + (i % 2),
                    night_temp=int(fallback.night_temp) - (i % 2),
                    wind_direction=fallback.wind_direction,
                    wind_power=fallback.wind_power,
                )
            )
        return days
