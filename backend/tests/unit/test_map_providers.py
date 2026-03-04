"""Unit tests for B1: Map Provider abstraction & dual implementation.

Covers:
- IMapProvider contract compliance for Amap and Google
- Config-driven provider selection (no code change to switch)
- FallbackMapProvider automatic degradation
- Factory singleton + reset
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import patch

import pytest

from app.models.schemas import Location, POIDetail, POIInfo, WeatherInfo
from app.providers.map.amap_provider import AmapMapProvider
from app.providers.map.base import IMapProvider
from app.providers.map.factory import (
    FallbackMapProvider,
    _build_provider,
    get_map_provider,
    reset_map_provider,
)
from app.providers.map.google_provider import GoogleMapProvider


# ── helpers ──────────────────────────────────────────────────────────

class _FailingProvider(IMapProvider):
    """Always raises so we can test fallback."""

    @property
    def provider_name(self) -> str:
        return "failing"

    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> list[POIInfo]:
        raise RuntimeError("boom")

    def get_poi_detail(self, poi_id: str) -> POIDetail:
        raise RuntimeError("boom")

    def get_weather(self, city: str) -> list[WeatherInfo]:
        raise RuntimeError("boom")

    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking",
    ) -> dict[str, Any]:
        raise RuntimeError("boom")


# ── IMapProvider contract ────────────────────────────────────────────

class TestAmapContract:
    """AmapMapProvider implements IMapProvider and returns valid data."""

    def setup_method(self) -> None:
        self.provider = AmapMapProvider(api_key="")  # fallback mode

    def test_is_instance_of_interface(self) -> None:
        assert isinstance(self.provider, IMapProvider)

    def test_provider_name(self) -> None:
        assert self.provider.provider_name == "amap"

    def test_search_poi_returns_list(self) -> None:
        result = self.provider.search_poi("景点", "北京")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert isinstance(result[0], POIInfo)

    def test_get_weather_returns_list(self) -> None:
        result = self.provider.get_weather("北京")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert isinstance(result[0], WeatherInfo)

    def test_get_poi_detail_returns_model(self) -> None:
        result = self.provider.get_poi_detail("test-123")
        assert isinstance(result, POIDetail)
        assert result.source == "amap"

    def test_plan_route_returns_dict(self) -> None:
        result = self.provider.plan_route("故宫", "颐和园")
        assert isinstance(result, dict)
        assert "distance" in result
        assert "duration" in result


class TestGoogleContract:
    """GoogleMapProvider implements IMapProvider and returns valid data."""

    def setup_method(self) -> None:
        self.provider = GoogleMapProvider(api_key="")  # fallback mode

    def test_is_instance_of_interface(self) -> None:
        assert isinstance(self.provider, IMapProvider)

    def test_provider_name(self) -> None:
        assert self.provider.provider_name == "google"

    def test_search_poi_returns_list(self) -> None:
        result = self.provider.search_poi("景点", "北京")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert isinstance(result[0], POIInfo)

    def test_get_weather_returns_list(self) -> None:
        result = self.provider.get_weather("北京")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_get_poi_detail_returns_model(self) -> None:
        result = self.provider.get_poi_detail("test-456")
        assert isinstance(result, POIDetail)
        assert result.source == "google"

    def test_plan_route_returns_dict(self) -> None:
        result = self.provider.plan_route("故宫", "颐和园")
        assert isinstance(result, dict)
        assert "distance" in result


# ── Fallback ─────────────────────────────────────────────────────────

class TestFallback:
    """FallbackMapProvider degrades gracefully when primary fails."""

    def setup_method(self) -> None:
        self.failing = _FailingProvider()
        self.good = AmapMapProvider(api_key="")
        self.fb = FallbackMapProvider(primary=self.failing, secondary=self.good)

    def test_provider_name_composite(self) -> None:
        assert self.fb.provider_name == "failing+amap"

    def test_search_poi_falls_back(self) -> None:
        result = self.fb.search_poi("景点", "北京")
        assert len(result) >= 1

    def test_get_weather_falls_back(self) -> None:
        result = self.fb.get_weather("北京")
        assert len(result) >= 1

    def test_get_poi_detail_falls_back(self) -> None:
        result = self.fb.get_poi_detail("id-1")
        assert isinstance(result, POIDetail)

    def test_plan_route_falls_back(self) -> None:
        result = self.fb.plan_route("A", "B")
        assert "distance" in result


# ── Config-driven factory ────────────────────────────────────────────

class TestFactory:
    """Factory builds provider from settings without code changes."""

    def teardown_method(self) -> None:
        reset_map_provider()

    def test_default_provider_is_amap(self) -> None:
        provider = get_map_provider()
        # default config → amap (or amap+fallback)
        assert "amap" in provider.provider_name

    def test_config_switch_to_google(self) -> None:
        """Switching map_provider in settings yields google provider."""
        from app.config.settings import ProviderSettings, Settings

        mock_settings = Settings(
            providers=ProviderSettings(map_provider="google"),
        )
        with patch("app.providers.map.factory.get_settings", return_value=mock_settings):
            reset_map_provider()
            provider = get_map_provider()
            assert "google" in provider.provider_name

    def test_config_with_fallback(self) -> None:
        """When fallback is configured, FallbackMapProvider is returned."""
        from app.config.settings import ProviderSettings, Settings

        mock_settings = Settings(
            providers=ProviderSettings(map_provider="amap", map_provider_fallback="google"),
        )
        with patch("app.providers.map.factory.get_settings", return_value=mock_settings):
            reset_map_provider()
            provider = get_map_provider()
            assert isinstance(provider, FallbackMapProvider)
            assert "amap+google" in provider.provider_name

    def test_invalid_provider_raises(self) -> None:
        from app.config.settings import ProviderSettings, Settings

        mock_settings = Settings(
            providers=ProviderSettings(map_provider="invalid_xyz"),
        )
        with patch("app.providers.map.factory.get_settings", return_value=mock_settings):
            reset_map_provider()
            with pytest.raises(ValueError, match="Unknown map provider"):
                get_map_provider()
