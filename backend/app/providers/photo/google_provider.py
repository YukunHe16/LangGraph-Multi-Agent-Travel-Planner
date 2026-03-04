"""Google Places Photo implementation of IPhotoProvider.

Uses the Google Places (New) API ``searchText`` + ``photos`` endpoints.
When the API key is empty the provider returns harmless fallback data.
"""

from __future__ import annotations

import httpx

from app.models.schemas import PhotoItem
from app.providers.photo.base import IPhotoProvider


class GooglePhotoProvider(IPhotoProvider):
    """Photo provider backed by the Google Places (New) API."""

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        self._base_url = "https://places.googleapis.com/v1"

    @property
    def provider_name(self) -> str:  # noqa: D401
        return "google"

    def search_photos(self, query: str, per_page: int = 5) -> list[PhotoItem]:
        """Search Google Places for photos; return fallback when key is missing."""
        if not self._api_key:
            return [
                PhotoItem(
                    id="google-fallback",
                    url=None,
                    thumb=None,
                    description=f"[google] {query}",
                    photographer=None,
                )
            ]

        try:
            # Step 1: search for a place
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self._api_key,
                "X-Goog-FieldMask": "places.id,places.displayName,places.photos",
            }
            body = {"textQuery": query, "maxResultCount": 1}

            with httpx.Client(timeout=10) as client:
                resp = client.post(
                    f"{self._base_url}/places:searchText",
                    json=body,
                    headers=headers,
                )
                resp.raise_for_status()

            places = resp.json().get("places", [])
            if not places:
                return []

            place = places[0]
            photo_refs = place.get("photos", [])[:per_page]
            if not photo_refs:
                return []

            # Step 2: build photo URLs from photo references
            photos: list[PhotoItem] = []
            for ref in photo_refs:
                photo_name = ref.get("name", "")
                photo_url = (
                    f"{self._base_url}/{photo_name}/media"
                    f"?maxWidthPx=800&key={self._api_key}"
                )
                photos.append(
                    PhotoItem(
                        id=photo_name,
                        url=photo_url,
                        thumb=photo_url.replace("maxWidthPx=800", "maxWidthPx=200"),
                        description=place.get("displayName", {}).get("text"),
                        photographer=ref.get("authorAttributions", [{}])[0].get(
                            "displayName"
                        ),
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
