"""Map provider factory with automatic fallback wrapper.

Usage::

    provider = get_map_provider()          # reads settings.yaml
    pois = provider.search_poi("故宫", "北京")

When ``settings.providers.map_provider`` is ``"amap"`` (default), an
``AmapMapProvider`` is returned.  Set it to ``"google"`` to switch.

The ``FallbackMapProvider`` wraps a *primary* and *secondary* provider:
if the primary call raises or returns empty, the secondary is tried.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.config.settings import get_settings
from app.models.schemas import POIDetail, POIInfo, WeatherInfo
from app.providers.map.amap_provider import AmapMapProvider
from app.providers.map.base import IMapProvider
from app.providers.map.google_provider import GoogleMapProvider

logger = logging.getLogger(__name__)

# ── Registry ─────────────────────────────────────────────────────────
_PROVIDER_MAP: dict[str, type[IMapProvider]] = {
    "amap": AmapMapProvider,
    "google": GoogleMapProvider,
}


# ── Fallback wrapper ─────────────────────────────────────────────────
class FallbackMapProvider(IMapProvider):
    """Transparent fallback: try *primary*, on failure try *secondary*."""

    def __init__(self, primary: IMapProvider, secondary: IMapProvider) -> None:
        self._primary = primary
        self._secondary = secondary

    @property
    def provider_name(self) -> str:  # noqa: D401
        return f"{self._primary.provider_name}+{self._secondary.provider_name}"

    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> list[POIInfo]:
        """Try primary; fall back to secondary on exception or empty result."""
        try:
            result = self._primary.search_poi(keywords, city, citylimit)
            if result:
                return result
        except Exception:
            logger.warning(
                "Map provider '%s' search_poi failed, falling back to '%s'",
                self._primary.provider_name,
                self._secondary.provider_name,
            )
        return self._secondary.search_poi(keywords, city, citylimit)

    def get_poi_detail(self, poi_id: str) -> POIDetail:
        """Try primary; fall back to secondary on exception."""
        try:
            return self._primary.get_poi_detail(poi_id)
        except Exception:
            logger.warning(
                "Map provider '%s' get_poi_detail failed, falling back to '%s'",
                self._primary.provider_name,
                self._secondary.provider_name,
            )
            return self._secondary.get_poi_detail(poi_id)

    def get_weather(self, city: str) -> list[WeatherInfo]:
        """Try primary; fall back to secondary on exception or empty result."""
        try:
            result = self._primary.get_weather(city)
            if result:
                return result
        except Exception:
            logger.warning(
                "Map provider '%s' get_weather failed, falling back to '%s'",
                self._primary.provider_name,
                self._secondary.provider_name,
            )
        return self._secondary.get_weather(city)

    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking",
    ) -> dict[str, Any]:
        """Try primary; fall back to secondary on exception."""
        try:
            return self._primary.plan_route(
                origin_address, destination_address, origin_city, destination_city, route_type
            )
        except Exception:
            logger.warning(
                "Map provider '%s' plan_route failed, falling back to '%s'",
                self._primary.provider_name,
                self._secondary.provider_name,
            )
            return self._secondary.plan_route(
                origin_address, destination_address, origin_city, destination_city, route_type
            )


# ── Factory ──────────────────────────────────────────────────────────
def _build_provider(name: str) -> IMapProvider:
    """Instantiate a map provider by name using current settings."""
    settings = get_settings()
    if name == "amap":
        return AmapMapProvider(api_key=settings.providers.amap_api_key)
    if name == "google":
        return GoogleMapProvider(api_key=settings.providers.google_maps_api_key)
    raise ValueError(f"Unknown map provider: {name!r}. Available: {list(_PROVIDER_MAP)}")


_map_provider: IMapProvider | None = None


def get_map_provider() -> IMapProvider:
    """Return a singleton ``IMapProvider`` driven by ``settings.yaml``.

    If ``map_provider_fallback`` is configured, the returned instance wraps
    primary+secondary in a ``FallbackMapProvider``.
    """
    global _map_provider
    if _map_provider is not None:
        return _map_provider

    settings = get_settings()
    primary_name = settings.providers.map_provider
    fallback_name = settings.providers.map_provider_fallback

    primary = _build_provider(primary_name)

    if fallback_name and fallback_name != primary_name:
        secondary = _build_provider(fallback_name)
        _map_provider = FallbackMapProvider(primary, secondary)
    else:
        _map_provider = primary

    return _map_provider


def reset_map_provider() -> None:
    """Reset the singleton (useful in tests)."""
    global _map_provider
    _map_provider = None
