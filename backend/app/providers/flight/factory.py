"""Flight provider factory with automatic fallback wrapper.

Usage::

    provider = get_flight_provider()           # reads settings.yaml
    offers = provider.search_flights("PEK", "NRT", "2026-06-01")

When ``settings.providers.flight_provider`` is ``"amadeus"`` (default), an
``AmadeusFlightProvider`` is returned.

The ``FallbackFlightProvider`` wraps a *primary* and *secondary* provider:
if the primary call raises or returns empty, the secondary is tried.
"""

from __future__ import annotations

import logging

from app.config.settings import get_settings
from app.models.schemas import FlightOffer
from app.providers.flight.amadeus_provider import AmadeusFlightProvider
from app.providers.flight.base import IFlightProvider

logger = logging.getLogger(__name__)

# ── Registry ─────────────────────────────────────────────────────────
_PROVIDER_MAP: dict[str, type[IFlightProvider]] = {
    "amadeus": AmadeusFlightProvider,
}


# ── Fallback wrapper ─────────────────────────────────────────────────
class FallbackFlightProvider(IFlightProvider):
    """Transparent fallback: try *primary*, on failure try *secondary*."""

    def __init__(self, primary: IFlightProvider, secondary: IFlightProvider) -> None:
        self._primary = primary
        self._secondary = secondary

    @property
    def provider_name(self) -> str:  # noqa: D401
        return f"{self._primary.provider_name}+{self._secondary.provider_name}"

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None = None,
        adults: int = 1,
        max_results: int = 5,
    ) -> list[FlightOffer]:
        """Try primary; fall back to secondary on exception or empty result."""
        try:
            result = self._primary.search_flights(
                origin, destination, departure_date, return_date, adults, max_results
            )
            if result:
                return result
        except Exception:
            logger.warning(
                "Flight provider '%s' search_flights failed, falling back to '%s'",
                self._primary.provider_name,
                self._secondary.provider_name,
            )
        return self._secondary.search_flights(
            origin, destination, departure_date, return_date, adults, max_results
        )


# ── Factory ──────────────────────────────────────────────────────────
def _build_provider(name: str) -> IFlightProvider:
    """Instantiate a flight provider by name using current settings."""
    settings = get_settings()
    if name == "amadeus":
        return AmadeusFlightProvider(
            client_id=settings.providers.amadeus_client_id,
            client_secret=settings.providers.amadeus_client_secret,
            base_url=settings.providers.amadeus_base_url,
        )
    raise ValueError(f"Unknown flight provider: {name!r}. Available: {list(_PROVIDER_MAP)}")


_flight_provider: IFlightProvider | None = None


def get_flight_provider() -> IFlightProvider:
    """Return a singleton ``IFlightProvider`` driven by ``settings.yaml``.

    If ``flight_provider_fallback`` is configured, the returned instance wraps
    primary+secondary in a ``FallbackFlightProvider``.
    """
    global _flight_provider
    if _flight_provider is not None:
        return _flight_provider

    settings = get_settings()
    primary_name = settings.providers.flight_provider
    fallback_name = settings.providers.flight_provider_fallback

    primary = _build_provider(primary_name)

    if fallback_name and fallback_name != primary_name:
        secondary = _build_provider(fallback_name)
        _flight_provider = FallbackFlightProvider(primary, secondary)
    else:
        _flight_provider = primary

    return _flight_provider


def reset_flight_provider() -> None:
    """Reset the singleton (useful in tests)."""
    global _flight_provider
    _flight_provider = None
