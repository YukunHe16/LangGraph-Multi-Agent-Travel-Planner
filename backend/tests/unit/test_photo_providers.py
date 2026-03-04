"""Unit tests for B2: Photo Provider abstraction & dual implementation.

Covers:
- IPhotoProvider contract compliance for Unsplash and Google
- Config-driven provider selection (no code change to switch)
- FallbackPhotoProvider automatic degradation
- Factory singleton + reset
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.models.schemas import PhotoItem
from app.providers.photo.base import IPhotoProvider
from app.providers.photo.factory import (
    FallbackPhotoProvider,
    _build_provider,
    get_photo_provider,
    reset_photo_provider,
)
from app.providers.photo.google_provider import GooglePhotoProvider
from app.providers.photo.unsplash_provider import UnsplashPhotoProvider


# ── helpers ──────────────────────────────────────────────────────────

class _FailingPhotoProvider(IPhotoProvider):
    """Always raises so we can test fallback."""

    @property
    def provider_name(self) -> str:
        return "failing"

    def search_photos(self, query: str, per_page: int = 5) -> list[PhotoItem]:
        raise RuntimeError("boom")

    def get_photo_url(self, query: str) -> str | None:
        raise RuntimeError("boom")


# ── IPhotoProvider contract ──────────────────────────────────────────

class TestUnsplashContract:
    """UnsplashPhotoProvider implements IPhotoProvider correctly."""

    def setup_method(self) -> None:
        self.provider = UnsplashPhotoProvider(api_key="")  # fallback mode

    def test_is_instance_of_interface(self) -> None:
        assert isinstance(self.provider, IPhotoProvider)

    def test_provider_name(self) -> None:
        assert self.provider.provider_name == "unsplash"

    def test_search_photos_returns_list(self) -> None:
        result = self.provider.search_photos("故宫")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert isinstance(result[0], PhotoItem)

    def test_search_photos_fallback_description(self) -> None:
        result = self.provider.search_photos("景点")
        assert result[0].description is not None
        assert "unsplash" in result[0].description

    def test_get_photo_url_returns_none_without_key(self) -> None:
        # No key → fallback item has url=None → get_photo_url returns None
        result = self.provider.get_photo_url("故宫")
        assert result is None


class TestGooglePhotoContract:
    """GooglePhotoProvider implements IPhotoProvider correctly."""

    def setup_method(self) -> None:
        self.provider = GooglePhotoProvider(api_key="")  # fallback mode

    def test_is_instance_of_interface(self) -> None:
        assert isinstance(self.provider, IPhotoProvider)

    def test_provider_name(self) -> None:
        assert self.provider.provider_name == "google"

    def test_search_photos_returns_list(self) -> None:
        result = self.provider.search_photos("故宫")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert isinstance(result[0], PhotoItem)

    def test_search_photos_fallback_description(self) -> None:
        result = self.provider.search_photos("景点")
        assert result[0].description is not None
        assert "google" in result[0].description

    def test_get_photo_url_returns_none_without_key(self) -> None:
        result = self.provider.get_photo_url("故宫")
        assert result is None


# ── Fallback ─────────────────────────────────────────────────────────

class TestPhotoFallback:
    """FallbackPhotoProvider degrades gracefully when primary fails."""

    def setup_method(self) -> None:
        self.failing = _FailingPhotoProvider()
        self.good = UnsplashPhotoProvider(api_key="")
        self.fb = FallbackPhotoProvider(primary=self.failing, secondary=self.good)

    def test_provider_name_composite(self) -> None:
        assert self.fb.provider_name == "failing+unsplash"

    def test_search_photos_falls_back(self) -> None:
        result = self.fb.search_photos("故宫")
        assert len(result) >= 1
        assert isinstance(result[0], PhotoItem)

    def test_get_photo_url_falls_back(self) -> None:
        # Secondary (unsplash, no key) returns None for url — that's valid
        result = self.fb.get_photo_url("故宫")
        # Just verify it doesn't raise; None is acceptable
        assert result is None


# ── Config-driven factory ────────────────────────────────────────────

class TestPhotoFactory:
    """Factory builds provider from settings without code changes."""

    def teardown_method(self) -> None:
        reset_photo_provider()

    def test_default_provider_is_unsplash(self) -> None:
        provider = get_photo_provider()
        assert "unsplash" in provider.provider_name

    def test_config_switch_to_google(self) -> None:
        """Switching photo_provider in settings yields google provider."""
        from app.config.settings import ProviderSettings, Settings

        mock_settings = Settings(
            providers=ProviderSettings(photo_provider="google"),
        )
        with patch("app.providers.photo.factory.get_settings", return_value=mock_settings):
            reset_photo_provider()
            provider = get_photo_provider()
            assert "google" in provider.provider_name

    def test_config_with_fallback(self) -> None:
        """When fallback is configured, FallbackPhotoProvider is returned."""
        from app.config.settings import ProviderSettings, Settings

        mock_settings = Settings(
            providers=ProviderSettings(
                photo_provider="unsplash",
                photo_provider_fallback="google",
            ),
        )
        with patch("app.providers.photo.factory.get_settings", return_value=mock_settings):
            reset_photo_provider()
            provider = get_photo_provider()
            assert isinstance(provider, FallbackPhotoProvider)
            assert "unsplash+google" in provider.provider_name

    def test_invalid_provider_raises(self) -> None:
        from app.config.settings import ProviderSettings, Settings

        mock_settings = Settings(
            providers=ProviderSettings(photo_provider="invalid_xyz"),
        )
        with patch("app.providers.photo.factory.get_settings", return_value=mock_settings):
            reset_photo_provider()
            with pytest.raises(ValueError, match="Unknown photo provider"):
                get_photo_provider()

    def test_reset_clears_singleton(self) -> None:
        """reset_photo_provider allows re-creation with new settings."""
        p1 = get_photo_provider()
        reset_photo_provider()
        p2 = get_photo_provider()
        # They should be different instances after reset
        assert p1 is not p2
