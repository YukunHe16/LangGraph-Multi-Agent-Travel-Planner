"""Unsplash implementation of IPhotoProvider.

Extracted from the former ``unsplash_service.py`` monolith.  When the
API key is empty the provider returns harmless fallback data so the rest
of the pipeline can continue.
"""

from __future__ import annotations

import httpx

from app.models.schemas import PhotoItem
from app.providers.photo.base import IPhotoProvider


class UnsplashPhotoProvider(IPhotoProvider):
    """Photo provider backed by the Unsplash API."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._base_url = "https://api.unsplash.com"

    @property
    def provider_name(self) -> str:  # noqa: D401
        return "unsplash"

    def search_photos(self, query: str, per_page: int = 5) -> list[PhotoItem]:
        """Search Unsplash for photos; return empty list when key is missing."""
        if not self._api_key:
            return [
                PhotoItem(
                    id="unsplash-fallback",
                    url=None,
                    thumb=None,
                    description=f"[unsplash] {query}",
                    photographer=None,
                )
            ]

        url = f"{self._base_url}/search/photos"
        params = {
            "query": query,
            "per_page": per_page,
            "client_id": self._api_key,
        }

        try:
            with httpx.Client(timeout=10) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
            data = response.json()
            results = data.get("results", [])
            photos: list[PhotoItem] = []
            for photo in results:
                photos.append(
                    PhotoItem(
                        id=photo.get("id"),
                        url=photo.get("urls", {}).get("regular"),
                        thumb=photo.get("urls", {}).get("thumb"),
                        description=photo.get("description") or photo.get("alt_description"),
                        photographer=photo.get("user", {}).get("name"),
                    )
                )
            return photos
        except Exception:
            return []

    def get_photo_url(self, query: str) -> str | None:
        """Return first image URL for a query."""
        photos = self.search_photos(query, per_page=1)
        if photos and photos[0].url:
            return photos[0].url
        return None
