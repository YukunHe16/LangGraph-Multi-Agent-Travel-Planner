"""Abstract base class for map providers.

Every map provider (Amap, Google Maps, …) MUST implement this interface so that
agents and services can be switched via configuration without code changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from app.models.schemas import POIDetail, POIInfo, WeatherInfo


class IMapProvider(ABC):
    """Uniform map provider interface consumed by agents and routes."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return a short identifier, e.g. ``'amap'`` or ``'google'``."""

    # ------------------------------------------------------------------
    # POI
    # ------------------------------------------------------------------
    @abstractmethod
    def search_poi(
        self,
        keywords: str,
        city: str,
        citylimit: bool = True,
    ) -> list[POIInfo]:
        """Search Points-of-Interest by keyword in a city.

        Args:
            keywords: Search keyword, e.g. "故宫".
            city: Target city name.
            citylimit: Whether to restrict results to the given city.

        Returns:
            A list of ``POIInfo`` items (may be empty on failure).
        """

    @abstractmethod
    def get_poi_detail(self, poi_id: str) -> POIDetail:
        """Return detailed info for a single POI.

        Args:
            poi_id: Provider-specific POI identifier.

        Returns:
            A ``POIDetail`` instance.
        """

    # ------------------------------------------------------------------
    # Weather
    # ------------------------------------------------------------------
    @abstractmethod
    def get_weather(self, city: str) -> list[WeatherInfo]:
        """Query current / forecast weather for a city.

        Args:
            city: City name.

        Returns:
            A list of ``WeatherInfo`` entries.
        """

    # ------------------------------------------------------------------
    # Route
    # ------------------------------------------------------------------
    @abstractmethod
    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking",
    ) -> dict[str, Any]:
        """Plan a route between two addresses.

        Args:
            origin_address: Start address text.
            destination_address: End address text.
            origin_city: Optional city hint for origin.
            destination_city: Optional city hint for destination.
            route_type: One of ``walking``, ``driving``, ``transit``.

        Returns:
            A dict with keys ``distance``, ``duration``, ``route_type``, ``description``.
        """
