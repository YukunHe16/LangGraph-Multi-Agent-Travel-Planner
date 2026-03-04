"""Abstract base class for visa source providers.

Every visa provider (Sherpa, …) MUST implement this interface so that
agents and services can be switched via configuration without code changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.schemas import VisaRequirement


class IVisaSourceProvider(ABC):
    """Uniform visa source provider interface consumed by VisaAgent."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return a short identifier, e.g. ``'sherpa'``."""

    # ------------------------------------------------------------------
    # Visa requirements lookup
    # ------------------------------------------------------------------
    @abstractmethod
    def get_requirements(
        self,
        nationality: str,
        destination: str,
        travel_duration_days: int = 7,
    ) -> list[VisaRequirement]:
        """Look up visa requirements for a nationality → destination pair.

        Args:
            nationality: Traveler nationality as ISO 3166-1 alpha-2 (e.g. ``"CN"``).
            destination: Destination country as ISO 3166-1 alpha-2 (e.g. ``"JP"``).
            travel_duration_days: Planned travel duration in days.

        Returns:
            A list of ``VisaRequirement`` instances (may be empty on failure).
            Each item MUST include a ``source_url`` for traceability.
        """
