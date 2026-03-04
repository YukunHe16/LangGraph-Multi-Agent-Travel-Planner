"""Unified provider registry — settings-driven assembly of all provider singletons.

Usage::

    from app.providers.registry import get_provider_registry

    registry = get_provider_registry()
    pois = registry.map.search_poi("故宫", "北京")
    photos = registry.photo.search_photos("故宫")
    flights = registry.flight.search_flights("PEK", "NRT", "2026-06-01")
    reqs = registry.visa.get_requirements("CN", "JP")

The registry delegates to the existing per-domain singleton factories. Each
domain factory already reads ``settings.yaml`` and handles fallback wrapping,
so the registry itself contains **zero** business logic — it is a pure
aggregation facade.
"""

from __future__ import annotations

import logging

from app.providers.flight.base import IFlightProvider
from app.providers.flight.factory import get_flight_provider, reset_flight_provider
from app.providers.map.base import IMapProvider
from app.providers.map.factory import get_map_provider, reset_map_provider
from app.providers.photo.base import IPhotoProvider
from app.providers.photo.factory import get_photo_provider, reset_photo_provider
from app.providers.visa.base import IVisaSourceProvider
from app.providers.visa.factory import get_visa_provider, reset_visa_provider

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Unified access point for all configured provider singletons.

    Each property lazily resolves the domain provider through its factory,
    ensuring that the first access triggers settings-driven construction
    while subsequent accesses return the cached singleton.

    Attributes are typed to the abstract interface, making downstream code
    depend only on contracts, not implementations.
    """

    # ── Typed provider accessors ──────────────────────────────────────

    @property
    def map(self) -> IMapProvider:
        """Return the configured map provider (with optional fallback)."""
        return get_map_provider()

    @property
    def photo(self) -> IPhotoProvider:
        """Return the configured photo provider (with optional fallback)."""
        return get_photo_provider()

    @property
    def flight(self) -> IFlightProvider:
        """Return the configured flight provider (with optional fallback)."""
        return get_flight_provider()

    @property
    def visa(self) -> IVisaSourceProvider:
        """Return the configured visa provider (with optional fallback)."""
        return get_visa_provider()

    # ── Introspection ─────────────────────────────────────────────────

    def provider_names(self) -> dict[str, str]:
        """Return a mapping of domain → active provider name.

        Useful for health-check endpoints and debugging.
        """
        return {
            "map": self.map.provider_name,
            "photo": self.photo.provider_name,
            "flight": self.flight.provider_name,
            "visa": self.visa.provider_name,
        }

    # ── Lifecycle ─────────────────────────────────────────────────────

    @staticmethod
    def reset_all() -> None:
        """Reset every domain singleton — intended for tests only."""
        reset_map_provider()
        reset_photo_provider()
        reset_flight_provider()
        reset_visa_provider()
        logger.debug("ProviderRegistry: all domain singletons reset")


# ── Module-level singleton ────────────────────────────────────────────

_registry: ProviderRegistry | None = None


def get_provider_registry() -> ProviderRegistry:
    """Return (or create) the module-level ``ProviderRegistry`` singleton."""
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
        logger.info(
            "ProviderRegistry initialised — providers will be resolved lazily "
            "from settings.yaml on first access"
        )
    return _registry


def reset_provider_registry() -> None:
    """Reset the registry singleton **and** all domain singletons (test helper)."""
    global _registry
    if _registry is not None:
        _registry.reset_all()
    _registry = None
    logger.debug("ProviderRegistry singleton reset")
