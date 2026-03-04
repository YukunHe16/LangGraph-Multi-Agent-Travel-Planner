"""Abstract base class for flight providers.

Every flight provider (Amadeus, …) MUST implement this interface so that
agents and services can be switched via configuration without code changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.schemas import FlightOffer


class IFlightProvider(ABC):
    """Uniform flight provider interface consumed by agents and routes."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return a short identifier, e.g. ``'amadeus'``."""

    # ------------------------------------------------------------------
    # Flight search
    # ------------------------------------------------------------------
    @abstractmethod
    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None = None,
        adults: int = 1,
        max_results: int = 5,
    ) -> list[FlightOffer]:
        """Search flights by origin/destination and dates.

        Args:
            origin: Departure IATA airport code (e.g. ``"PEK"``).
            destination: Arrival IATA airport code (e.g. ``"NRT"``).
            departure_date: Departure date ``YYYY-MM-DD``.
            return_date: Optional return date ``YYYY-MM-DD`` for round-trip.
            adults: Number of adult passengers.
            max_results: Maximum number of offers to return.

        Returns:
            A list of ``FlightOffer`` instances (may be empty on failure).
        """
