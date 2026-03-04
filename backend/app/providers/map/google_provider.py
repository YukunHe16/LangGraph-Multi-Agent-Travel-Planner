"""Google Maps implementation of IMapProvider.

This is a stub / baseline implementation.  It provides deterministic fallback
data so that the system stays functional when no Google Maps API key is
configured, while still satisfying the ``IMapProvider`` contract.

When a valid API key is provided the real Google Maps REST endpoints will be
called (Places API for POI, Geocoding for routes, etc.).
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


class GoogleMapProvider(IMapProvider):
    """Google Maps provider with deterministic fallback when no key."""

    def __init__(self, api_key: str = "", base_url: str = "https://maps.googleapis.com") -> None:
        self._api_key = api_key
        self._base_url = base_url

    @property
    def provider_name(self) -> str:  # noqa: D401
        return "google"

    # ------------------------------------------------------------------
    # POI
    # ------------------------------------------------------------------
    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> list[POIInfo]:
        """Search POIs via Google Places Text Search API."""
        contract = MapPOISearchInput(keywords=keywords, city=city, citylimit=citylimit)

        if not self._api_key:
            fallback_items = [
                POIInfo(
                    id=f"google-mock-{contract.city}-{contract.keywords}",
                    name=f"{contract.city}{contract.keywords}推荐点(Google)",
                    type="景点",
                    address=f"{contract.city}市中心",
                    location=Location(longitude=116.397128, latitude=39.916527),
                )
            ]
            return MapPOISearchOutput(provider=self.provider_name, items=fallback_items).items

        url = f"{self._base_url}/maps/api/place/textsearch/json"
        params = {
            "query": f"{contract.keywords} in {contract.city}",
            "key": self._api_key,
            "language": "zh-CN",
        }
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
            data = response.json()
            results: list[POIInfo] = []
            for place in data.get("results", [])[:8]:
                loc = place.get("geometry", {}).get("location", {})
                results.append(
                    POIInfo(
                        id=place.get("place_id", ""),
                        name=place.get("name", ""),
                        type=",".join(place.get("types", [])),
                        address=place.get("formatted_address", ""),
                        location=Location(
                            longitude=loc.get("lng", 0.0),
                            latitude=loc.get("lat", 0.0),
                        ),
                    )
                )
            return MapPOISearchOutput(provider=self.provider_name, items=results).items
        except Exception:
            return []

    def get_poi_detail(self, poi_id: str) -> POIDetail:
        """Return a minimal POI detail payload."""
        return POIDetail(id=poi_id, name="示例景点(Google)", address="示例地址", source=self.provider_name)

    # ------------------------------------------------------------------
    # Weather (Google Maps has no weather API — fallback only)
    # ------------------------------------------------------------------
    def get_weather(self, city: str) -> list[WeatherInfo]:
        """Google Maps has no weather endpoint; returns deterministic fallback."""
        contract = MapWeatherInput(city=city)
        _ = contract  # validate input
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
        """Plan route via Google Directions API; fallback when no key."""
        if not self._api_key:
            return {
                "distance": 3200.0,
                "duration": 1800,
                "route_type": route_type,
                "description": f"{origin_address} 到 {destination_address} 的{route_type}路线(Google)",
            }

        mode_map = {"walking": "walking", "driving": "driving", "transit": "transit"}
        url = f"{self._base_url}/maps/api/directions/json"
        params = {
            "origin": f"{origin_address},{origin_city or ''}",
            "destination": f"{destination_address},{destination_city or ''}",
            "mode": mode_map.get(route_type, "walking"),
            "key": self._api_key,
            "language": "zh-CN",
        }
        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
            data = response.json()
            routes = data.get("routes", [])
            if not routes:
                return {
                    "distance": 0.0,
                    "duration": 0,
                    "route_type": route_type,
                    "description": "未找到路线",
                }
            leg = routes[0].get("legs", [{}])[0]
            return {
                "distance": float(leg.get("distance", {}).get("value", 0)),
                "duration": int(leg.get("duration", {}).get("value", 0)),
                "route_type": route_type,
                "description": leg.get("start_address", origin_address)
                + " → "
                + leg.get("end_address", destination_address),
            }
        except Exception:
            return {
                "distance": 0.0,
                "duration": 0,
                "route_type": route_type,
                "description": "路线规划失败",
            }
