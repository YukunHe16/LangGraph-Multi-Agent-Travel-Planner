"""Photo provider factory with automatic fallback wrapper.

Usage::

    provider = get_photo_provider()           # reads settings.yaml
    photos = provider.search_photos("故宫")

When ``settings.providers.photo_provider`` is ``"unsplash"`` (default), an
``UnsplashPhotoProvider`` is returned.  Set it to ``"google"`` to switch.

The ``FallbackPhotoProvider`` wraps a *primary* and *secondary* provider:
if the primary call raises or returns empty, the secondary is tried.
"""

from __future__ import annotations

import logging

from app.config.settings import get_settings
from app.models.schemas import PhotoItem
from app.providers.photo.base import IPhotoProvider
from app.providers.photo.google_provider import GooglePhotoProvider
from app.providers.photo.unsplash_provider import UnsplashPhotoProvider

logger = logging.getLogger(__name__)

# ── Registry ─────────────────────────────────────────────────────────
_PROVIDER_MAP: dict[str, type[IPhotoProvider]] = {
    "unsplash": UnsplashPhotoProvider,
    "google": GooglePhotoProvider,
}


# ── Fallback wrapper ─────────────────────────────────────────────────
class FallbackPhotoProvider(IPhotoProvider):
    """Transparent fallback: try *primary*, on failure try *secondary*."""

    def __init__(self, primary: IPhotoProvider, secondary: IPhotoProvider) -> None:
        self._primary = primary
        self._secondary = secondary

    @property
    def provider_name(self) -> str:  # noqa: D401
        return f"{self._primary.provider_name}+{self._secondary.provider_name}"

    def search_photos(self, query: str, per_page: int = 5) -> list[PhotoItem]:
        """Try primary; fall back to secondary on exception or empty result."""
        try:
            result = self._primary.search_photos(query, per_page)
            if result:
                return result
        except Exception:
            logger.warning(
                "Photo provider '%s' search_photos failed, falling back to '%s'",
                self._primary.provider_name,
                self._secondary.provider_name,
            )
        return self._secondary.search_photos(query, per_page)

    def get_photo_url(self, query: str) -> str | None:
        """Try primary; fall back to secondary on exception."""
        try:
            result = self._primary.get_photo_url(query)
            if result is not None:
                return result
        except Exception:
            logger.warning(
                "Photo provider '%s' get_photo_url failed, falling back to '%s'",
                self._primary.provider_name,
                self._secondary.provider_name,
            )
        return self._secondary.get_photo_url(query)


# ── Factory ──────────────────────────────────────────────────────────
def _build_provider(name: str) -> IPhotoProvider:
    """Instantiate a photo provider by name using current settings."""
    settings = get_settings()
    if name == "unsplash":
        return UnsplashPhotoProvider(api_key=settings.providers.unsplash_access_key)
    if name == "google":
        return GooglePhotoProvider(api_key=settings.providers.google_places_api_key)
    raise ValueError(f"Unknown photo provider: {name!r}. Available: {list(_PROVIDER_MAP)}")


_photo_provider: IPhotoProvider | None = None


def get_photo_provider() -> IPhotoProvider:
    """Return a singleton ``IPhotoProvider`` driven by ``settings.yaml``.

    If ``photo_provider_fallback`` is configured, the returned instance wraps
    primary+secondary in a ``FallbackPhotoProvider``.
    """
    global _photo_provider
    if _photo_provider is not None:
        return _photo_provider

    settings = get_settings()
    primary_name = settings.providers.photo_provider
    fallback_name = settings.providers.photo_provider_fallback

    primary = _build_provider(primary_name)

    if fallback_name and fallback_name != primary_name:
        secondary = _build_provider(fallback_name)
        _photo_provider = FallbackPhotoProvider(primary, secondary)
    else:
        _photo_provider = primary

    return _photo_provider


def reset_photo_provider() -> None:
    """Reset the singleton (useful in tests)."""
    global _photo_provider
    _photo_provider = None
