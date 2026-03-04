"""Abstract base class for photo providers.

Every photo provider (Unsplash, Google Places, …) MUST implement this
interface so that agents and services can be switched via configuration
without code changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.models.schemas import PhotoItem


class IPhotoProvider(ABC):
    """Uniform photo provider interface consumed by agents and routes."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return a short identifier, e.g. ``'unsplash'`` or ``'google'``."""

    # ------------------------------------------------------------------
    # Photo search
    # ------------------------------------------------------------------
    @abstractmethod
    def search_photos(self, query: str, per_page: int = 5) -> list[PhotoItem]:
        """Search photos by keyword.

        Args:
            query: Search keyword, e.g. "故宫".
            per_page: Maximum number of results to return.

        Returns:
            A list of ``PhotoItem`` instances (may be empty on failure).
        """

    @abstractmethod
    def get_photo_url(self, query: str) -> str | None:
        """Return the URL of the first matching photo, or *None*.

        Args:
            query: Search keyword.

        Returns:
            A URL string or ``None`` when no results are found.
        """
