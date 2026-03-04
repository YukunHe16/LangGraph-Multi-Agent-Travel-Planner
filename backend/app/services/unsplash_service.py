"""Unsplash service migrated from hello-agents service layer."""

from __future__ import annotations

from typing import Any

import httpx

from app.config.settings import get_settings


class UnsplashService:
    """Simple Unsplash client used by attraction recommendation flow."""

    def __init__(self) -> None:
        settings = get_settings()
        self.access_key = settings.providers.unsplash_access_key
        self.base_url = "https://api.unsplash.com"

    def search_photos(self, query: str, per_page: int = 5) -> list[dict[str, Any]]:
        """Search images by keyword; return empty list when key is missing."""
        if not self.access_key:
            return []

        url = f"{self.base_url}/search/photos"
        params = {"query": query, "per_page": per_page, "client_id": self.access_key}

        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            photos: list[dict[str, Any]] = []
            for photo in results:
                photos.append(
                    {
                        "id": photo.get("id"),
                        "url": photo.get("urls", {}).get("regular"),
                        "thumb": photo.get("urls", {}).get("thumb"),
                        "description": photo.get("description") or photo.get("alt_description"),
                        "photographer": photo.get("user", {}).get("name"),
                    }
                )
            return photos
        except Exception:
            return []

    def get_photo_url(self, query: str) -> str | None:
        """Return first image URL for a query."""
        photos = self.search_photos(query, per_page=1)
        if photos:
            return photos[0].get("url")
        return None


_unsplash_service: UnsplashService | None = None


def get_unsplash_service() -> UnsplashService:
    """Get singleton Unsplash service."""
    global _unsplash_service
    if _unsplash_service is None:
        _unsplash_service = UnsplashService()
    return _unsplash_service
