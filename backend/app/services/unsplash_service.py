"""Unsplash service – backward-compatible wrapper delegating to photo provider layer."""

from __future__ import annotations

from typing import Any

from app.models.schemas import PhotoSearchInput
from app.providers.photo.factory import get_photo_provider, reset_photo_provider


class UnsplashService:
    """Backward-compatible wrapper over ``IPhotoProvider``.

    Existing call-sites (agents, routes) keep working without changes while
    the actual implementation is now pluggable via ``settings.yaml``.
    """

    def __init__(self) -> None:
        self._provider = get_photo_provider()

    def search_photos(self, query: str, per_page: int = 5) -> list[dict[str, Any]]:
        """Search images by keyword; return list of dicts for backward compat."""
        contract = PhotoSearchInput(query=query, per_page=per_page)
        photos = self._provider.search_photos(contract.query, contract.per_page)
        return [item.model_dump() for item in photos]

    def get_photo_url(self, query: str) -> str | None:
        """Return first image URL for a query."""
        return self._provider.get_photo_url(query)


_unsplash_service: UnsplashService | None = None


def get_unsplash_service() -> UnsplashService:
    """Get singleton Unsplash service."""
    global _unsplash_service
    if _unsplash_service is None:
        _unsplash_service = UnsplashService()
    return _unsplash_service
