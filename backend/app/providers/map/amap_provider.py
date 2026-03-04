"""Amap (高德地图) implementation of IMapProvider.

Extracted from ``app/services/amap_service.py`` and adapted to the pluggable
provider interface.  All public methods match the ``IMapProvider`` contract.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from app.models.schemas import (
    Location,
    MapPOISearchInput,
    MapPOISearchOutput,
    MapWeatherInput,
    MapWeatherOutput,
    POIDetail,
    POIInfo,
    WeatherInfo,
)
from app.providers.map.base import IMapProvider


class AmapMapProvider(IMapProvider):
    """Amap REST API client with deterministic fallback data."""

    def __init__(self, api_key: str = "", base_url: str = "https://restapi.amap.com") -> None:
        self._api_key = api_key
        self._base_url = base_url

    @property
    def provider_name(self) -> str:  # noqa: D401
        return "amap"

    # ------------------------------------------------------------------
    # POI
    # ------------------------------------------------------------------
    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> list[POIInfo]:
        """Search POIs via Amap REST API, fallback to mock entries when no key."""
        contract = MapPOISearchInput(keywords=keywords, city=city, citylimit=citylimit)
        if not self._api_key:
            fallback_items = [
                POIInfo(
                    id=f"mock-{contract.city}-{contract.keywords}",
                    name=f"{contract.city}{contract.keywords}推荐点",
                    type="景点",
                    address=f"{contract.city}市中心",
                    location=Location(longitude=116.397128, latitude=39.916527),
                )
            ]
            return MapPOISearchOutput(provider=self.provider_name, items=fallback_items).items

        url = f"{self._base_url}/v5/place/text"
        params = {
            "key": self._api_key,
            "keywords": contract.keywords,
            "region": contract.city,
            "city_limit": "true" if contract.citylimit else "false",
            "show_fields": "business,photos",
        }
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
            data = response.json()
            pois = data.get("pois", [])
            results: list[POIInfo] = []
            for poi in pois[:8]:
                location = poi.get("location", "0,0").split(",")
                lon = float(location[0]) if len(location) == 2 else 0.0
                lat = float(location[1]) if len(location) == 2 else 0.0
                results.append(
                    POIInfo(
                        id=poi.get("id", ""),
                        name=poi.get("name", ""),
                        type=poi.get("type", ""),
                        address=poi.get("address", ""),
                        location=Location(longitude=lon, latitude=lat),
                        tel=poi.get("tel") or None,
                    )
                )
            return MapPOISearchOutput(provider=self.provider_name, items=results).items
        except Exception:
            return []

    def get_poi_detail(self, poi_id: str) -> POIDetail:
        """Return a minimal POI detail payload."""
        return POIDetail(id=poi_id, name="示例景点", address="示例地址", source=self.provider_name)

    # ------------------------------------------------------------------
    # Weather
    # ------------------------------------------------------------------
    def get_weather(self, city: str) -> list[WeatherInfo]:
        """Query weather via Amap REST API, fallback to one deterministic day."""
        contract = MapWeatherInput(city=city)
        if not self._api_key:
            fallback_items = [
                WeatherInfo(
                    date="today",
                    day_weather="晴",
                    night_weather="多云",
                    day_temp=25,
                    night_temp=18,
                    wind_direction="东南风",
                    wind_power="3级",
                )
            ]
            return MapWeatherOutput(provider=self.provider_name, items=fallback_items).items

        url = f"{self._base_url}/v3/weather/weatherInfo"
        params = {"key": self._api_key, "city": contract.city, "extensions": "base"}
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
            data = response.json()
            lives = data.get("lives", [])
            if not lives:
                return []
            live = lives[0]
            result_items = [
                WeatherInfo(
                    date=live.get("reporttime", "")[:10] or "today",
                    day_weather=live.get("weather", ""),
                    night_weather=live.get("weather", ""),
                    day_temp=live.get("temperature", 0),
                    night_temp=live.get("temperature", 0),
                    wind_direction=live.get("winddirection", ""),
                    wind_power=live.get("windpower", ""),
                )
            ]
            return MapWeatherOutput(provider=self.provider_name, items=result_items).items
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Route
    # ------------------------------------------------------------------
    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking",
    ) -> dict[str, Any]:
        """Return a simple route summary compatible with API response schema."""
        _ = (origin_city, destination_city)
        return {
            "distance": 3200.0,
            "duration": 1800,
            "route_type": route_type,
            "description": f"{origin_address} 到 {destination_address} 的{route_type}路线",
        }
