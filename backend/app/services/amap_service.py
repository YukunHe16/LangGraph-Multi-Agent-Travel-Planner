"""Amap service wrapper — now delegates to the pluggable map provider layer.

This module preserves the original API surface (`search_poi`, `get_weather`,
`plan_route`, `get_poi_detail`) for backward compatibility with existing routes
and agents.  Internally it delegates to ``app.providers.map``.
"""

from __future__ import annotations

from typing import Any, Optional

from app.models.schemas import POIDetail, POIInfo, WeatherInfo
from app.providers.map import get_map_provider


class AmapService:
    """Backward-compatible wrapper that delegates to IMapProvider."""

    def __init__(self) -> None:
        self._provider = get_map_provider()

    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> list[POIInfo]:
        """Search POIs via pluggable map provider."""
        return self._provider.search_poi(keywords=keywords, city=city, citylimit=citylimit)

    def get_weather(self, city: str) -> list[WeatherInfo]:
        """Query weather via pluggable map provider."""
        return self._provider.get_weather(city)

    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking",
    ) -> dict[str, Any]:
        """Plan a route via pluggable map provider."""
        return self._provider.plan_route(
            origin_address=origin_address,
            destination_address=destination_address,
            origin_city=origin_city,
            destination_city=destination_city,
            route_type=route_type,
        )

    def get_poi_detail(self, poi_id: str) -> POIDetail:
        """Get POI detail via pluggable map provider."""
        return self._provider.get_poi_detail(poi_id)


_amap_service: AmapService | None = None


def get_amap_service() -> AmapService:
    """Get singleton Amap service."""
    global _amap_service
    if _amap_service is None:
        _amap_service = AmapService()
    return _amap_service
