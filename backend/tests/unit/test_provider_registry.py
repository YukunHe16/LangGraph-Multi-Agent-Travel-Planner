"""Tests for ProviderRegistry — unified settings-driven provider assembly.

Validates:
- Registry exposes all 4 domain providers via typed properties.
- Providers are assembled from settings (config-driven).
- ``reset_all()`` clears every domain singleton.
- ``provider_names()`` returns correct introspection dict.
- ``get_provider_registry()`` returns a singleton.
- ``reset_provider_registry()`` clears registry + domain singletons.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.config.settings import ProviderSettings, Settings
from app.providers.flight.base import IFlightProvider
from app.providers.map.base import IMapProvider
from app.providers.photo.base import IPhotoProvider
from app.providers.registry import (
    ProviderRegistry,
    get_provider_registry,
    reset_provider_registry,
)
from app.providers.visa.base import IVisaSourceProvider


# ── Helpers ───────────────────────────────────────────────────────────

def _make_settings(**overrides: str) -> Settings:
    """Create a ``Settings`` instance with custom provider fields."""
    provider_defaults = {
        "map_provider": "amap",
        "photo_provider": "unsplash",
        "flight_provider": "amadeus",
        "visa_provider": "sherpa",
        "amap_api_key": "test-amap-key",
        "unsplash_access_key": "test-unsplash-key",
        "amadeus_client_id": "test-id",
        "amadeus_client_secret": "test-secret",
        "sherpa_api_key": "test-sherpa-key",
    }
    provider_defaults.update(overrides)
    return Settings(providers=ProviderSettings(**provider_defaults))


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_singletons():
    """Ensure every test starts with a clean slate."""
    reset_provider_registry()
    ProviderRegistry.reset_all()  # also clear domain singletons directly
    yield
    reset_provider_registry()
    ProviderRegistry.reset_all()


@pytest.fixture()
def settings():
    """Return default test settings."""
    return _make_settings()


# ── Tests ─────────────────────────────────────────────────────────────

class TestProviderRegistryProperties:
    """Registry exposes correctly typed provider instances."""

    def test_map_property_returns_imap_provider(self, settings: Settings) -> None:
        with patch("app.providers.map.factory.get_settings", return_value=settings):
            registry = ProviderRegistry()
            assert isinstance(registry.map, IMapProvider)

    def test_photo_property_returns_iphoto_provider(self, settings: Settings) -> None:
        with patch("app.providers.photo.factory.get_settings", return_value=settings):
            registry = ProviderRegistry()
            assert isinstance(registry.photo, IPhotoProvider)

    def test_flight_property_returns_iflight_provider(self, settings: Settings) -> None:
        with patch("app.providers.flight.factory.get_settings", return_value=settings):
            registry = ProviderRegistry()
            assert isinstance(registry.flight, IFlightProvider)

    def test_visa_property_returns_ivisa_provider(self, settings: Settings) -> None:
        with patch("app.providers.visa.factory.get_settings", return_value=settings):
            registry = ProviderRegistry()
            assert isinstance(registry.visa, IVisaSourceProvider)


class TestProviderNames:
    """``provider_names()`` returns an introspection dictionary."""

    def test_default_provider_names(self, settings: Settings) -> None:
        with (
            patch("app.providers.map.factory.get_settings", return_value=settings),
            patch("app.providers.photo.factory.get_settings", return_value=settings),
            patch("app.providers.flight.factory.get_settings", return_value=settings),
            patch("app.providers.visa.factory.get_settings", return_value=settings),
        ):
            registry = ProviderRegistry()
            names = registry.provider_names()

        assert set(names.keys()) == {"map", "photo", "flight", "visa"}
        assert names["map"] == "amap"
        assert names["photo"] == "unsplash"
        assert names["flight"] == "amadeus"
        assert names["visa"] == "sherpa"

    def test_fallback_provider_names_contain_plus(self) -> None:
        fb_settings = _make_settings(
            map_provider_fallback="google",
            google_maps_api_key="test-google-key",
        )
        with patch("app.providers.map.factory.get_settings", return_value=fb_settings):
            registry = ProviderRegistry()
            assert "+" in registry.map.provider_name


class TestConfigDriven:
    """Provider selection is driven purely by settings.yaml values."""

    def test_switching_map_provider_to_google(self) -> None:
        google_settings = _make_settings(
            map_provider="google",
            google_maps_api_key="test-google-key",
        )
        with patch("app.providers.map.factory.get_settings", return_value=google_settings):
            registry = ProviderRegistry()
            assert registry.map.provider_name == "google"

    def test_switching_photo_provider_to_google(self) -> None:
        google_settings = _make_settings(
            photo_provider="google",
            google_places_api_key="test-google-key",
        )
        with patch("app.providers.photo.factory.get_settings", return_value=google_settings):
            registry = ProviderRegistry()
            assert registry.photo.provider_name == "google"


class TestResetAll:
    """``reset_all()`` clears all domain singletons."""

    def test_reset_all_allows_reconfiguration(self, settings: Settings) -> None:
        # First access — creates singletons with default settings
        with (
            patch("app.providers.map.factory.get_settings", return_value=settings),
            patch("app.providers.photo.factory.get_settings", return_value=settings),
            patch("app.providers.flight.factory.get_settings", return_value=settings),
            patch("app.providers.visa.factory.get_settings", return_value=settings),
        ):
            registry = ProviderRegistry()
            assert registry.map.provider_name == "amap"

        # Reset all singletons
        registry.reset_all()

        # Second access — reconfigure with different settings
        new_settings = _make_settings(
            map_provider="google",
            google_maps_api_key="new-google-key",
        )
        with patch("app.providers.map.factory.get_settings", return_value=new_settings):
            assert registry.map.provider_name == "google"


class TestSingleton:
    """Module-level ``get_provider_registry()`` returns a singleton."""

    def test_get_provider_registry_returns_same_instance(self) -> None:
        r1 = get_provider_registry()
        r2 = get_provider_registry()
        assert r1 is r2

    def test_reset_provider_registry_clears_singleton(self) -> None:
        r1 = get_provider_registry()
        reset_provider_registry()
        r2 = get_provider_registry()
        assert r1 is not r2


class TestAllProvidersAssembled:
    """Integration-style: all 4 providers resolve without error."""

    def test_all_providers_accessible(self, settings: Settings) -> None:
        with (
            patch("app.providers.map.factory.get_settings", return_value=settings),
            patch("app.providers.photo.factory.get_settings", return_value=settings),
            patch("app.providers.flight.factory.get_settings", return_value=settings),
            patch("app.providers.visa.factory.get_settings", return_value=settings),
        ):
            registry = ProviderRegistry()
            # All properties should resolve without raising
            _ = registry.map
            _ = registry.photo
            _ = registry.flight
            _ = registry.visa

            names = registry.provider_names()
            assert len(names) == 4
            assert all(isinstance(v, str) and v for v in names.values())
