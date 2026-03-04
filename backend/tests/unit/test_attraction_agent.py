"""Unit tests for C2 AttractionAgent — pluggable provider integration.

Tests verify:
- POI search via map provider → Attraction list with source_url
- Photo enrichment via photo provider → image_url populated
- Fallback when POI search returns empty
- Fallback when POI search raises an exception
- as_worker() protocol compliance with PlannerState
- Provider is accessed via registry (not hard-coded services)
- Attraction schema fields match FinalPlan contract
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.workers.attraction_agent import (
    CITY_CENTER,
    AttractionAgent,
    _DEFAULT_VISIT_DURATION,
    _MAX_POIS,
)
from app.models.schemas import Attraction, Location, POIInfo, TripRequest
from app.rag.retriever import NullRetriever

# All C2 unit tests inject NullRetriever to isolate from RAG (C8).
_NULL_RETRIEVER = NullRetriever()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_request(**overrides: Any) -> TripRequest:
    """Build a minimal valid TripRequest with sensible defaults."""
    defaults = {
        "city": "北京",
        "start_date": "2026-06-01",
        "end_date": "2026-06-03",
        "travel_days": 3,
        "transportation": "公共交通",
        "accommodation": "经济型酒店",
        "preferences": ["历史文化"],
    }
    defaults.update(overrides)
    return TripRequest(**defaults)


def _make_poi(name: str = "故宫", idx: int = 0) -> POIInfo:
    """Create a stub POIInfo."""
    return POIInfo(
        id=f"poi_{idx}",
        name=name,
        type="景点",
        address=f"北京{name}地址",
        location=Location(longitude=116.397 + idx * 0.01, latitude=39.916 + idx * 0.01),
    )


def _make_registry_mock(
    pois: list[POIInfo] | None = None,
    photo_url: str | None = "https://images.unsplash.com/test",
    search_raises: bool = False,
    photo_raises: bool = False,
) -> MagicMock:
    """Create a mock ProviderRegistry with map and photo stubs."""
    registry = MagicMock()

    # Map provider
    if search_raises:
        registry.map.search_poi.side_effect = RuntimeError("API down")
    else:
        registry.map.search_poi.return_value = pois or []
    registry.map.provider_name = "amap"

    # Photo provider
    if photo_raises:
        registry.photo.get_photo_url.side_effect = RuntimeError("Photo API down")
    else:
        registry.photo.get_photo_url.return_value = photo_url
    registry.photo.provider_name = "unsplash"

    return registry


# ---------------------------------------------------------------------------
# Tests: Core run() with POI results
# ---------------------------------------------------------------------------

class TestAttractionFromPOI:
    """Verify attraction generation from successful POI searches."""

    def test_returns_attractions_from_pois(self) -> None:
        pois = [_make_poi(f"景点{i}", i) for i in range(3)]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        assert len(result) == 3
        assert all(isinstance(a, Attraction) for a in result)

    def test_limits_to_max_pois(self) -> None:
        pois = [_make_poi(f"景点{i}", i) for i in range(10)]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        assert len(result) == _MAX_POIS

    def test_attraction_has_source_url(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        assert result[0].source_url is not None
        assert len(result[0].source_url) > 0

    def test_attraction_has_image_url(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois, photo_url="https://example.com/photo.jpg")
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        assert result[0].image_url == "https://example.com/photo.jpg"

    def test_attraction_has_visit_duration(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        assert result[0].visit_duration == _DEFAULT_VISIT_DURATION

    def test_attraction_has_category_from_preference(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request(preferences=["历史文化"]))

        assert result[0].category == "历史文化"

    def test_uses_first_preference_as_keyword(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        agent.run(_make_request(preferences=["公园", "博物馆"]))

        registry.map.search_poi.assert_called_once_with(
            keywords="公园", city="北京", citylimit=True
        )

    def test_default_keyword_when_no_preferences(self) -> None:
        pois = [_make_poi("某景点")]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        agent.run(_make_request(preferences=[]))

        registry.map.search_poi.assert_called_once_with(
            keywords="景点", city="北京", citylimit=True
        )

    def test_rating_decreases_with_index(self) -> None:
        pois = [_make_poi(f"景点{i}", i) for i in range(3)]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        assert result[0].rating > result[1].rating > result[2].rating


# ---------------------------------------------------------------------------
# Tests: Photo enrichment edge cases
# ---------------------------------------------------------------------------

class TestPhotoEnrichment:
    """Verify photo provider integration and graceful degradation."""

    def test_photo_failure_returns_none_image_url(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois, photo_raises=True)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        assert result[0].image_url is None

    def test_photo_called_with_name_and_city(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        agent.run(_make_request())

        # With NullRetriever (no RAG), photo is called once per map POI
        registry.photo.get_photo_url.assert_called_once_with("故宫 北京")


# ---------------------------------------------------------------------------
# Tests: Fallback (no POIs)
# ---------------------------------------------------------------------------

class TestFallback:
    """Verify deterministic fallback when POI search returns nothing."""

    def test_empty_pois_triggers_fallback(self) -> None:
        registry = _make_registry_mock(pois=[])
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        assert len(result) == 3
        assert all("推荐点" in a.name for a in result)

    def test_fallback_has_source_url(self) -> None:
        registry = _make_registry_mock(pois=[])
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        assert all(a.source_url is not None for a in result)
        assert all(len(a.source_url) > 0 for a in result)

    def test_fallback_uses_city_center_coordinates(self) -> None:
        registry = _make_registry_mock(pois=[])
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request(city="上海"))

        expected_lon, expected_lat = CITY_CENTER["上海"]
        assert result[0].location.longitude == pytest.approx(expected_lon)
        assert result[0].location.latitude == pytest.approx(expected_lat)

    def test_fallback_default_coordinates_for_unknown_city(self) -> None:
        registry = _make_registry_mock(pois=[])
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request(city="拉萨"))

        # Should use default Beijing coordinates
        assert result[0].location.longitude == pytest.approx(116.397128)

    def test_exception_triggers_fallback(self) -> None:
        registry = _make_registry_mock(search_raises=True)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        assert len(result) == 3
        assert all("推荐点" in a.name for a in result)


# ---------------------------------------------------------------------------
# Tests: Source URL generation
# ---------------------------------------------------------------------------

class TestSourceURL:
    """Verify source_url generation based on provider type."""

    def test_amap_source_url(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)
        registry.map.provider_name = "amap"
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        # Map-sourced attraction should have amap URL
        map_attraction = [a for a in result if a.category != "Wikivoyage推荐"][0]
        assert "ditu.amap.com" in map_attraction.source_url

    def test_google_source_url(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)
        registry.map.provider_name = "google"
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        # Map-sourced attraction should have google URL
        map_attraction = [a for a in result if a.category != "Wikivoyage推荐"][0]
        assert "google.com/maps" in map_attraction.source_url


# ---------------------------------------------------------------------------
# Tests: as_worker() WorkerFn protocol
# ---------------------------------------------------------------------------

class TestAsWorker:
    """Verify as_worker() returns a valid WorkerFn for PlannerAgent."""

    def test_worker_returns_dict_with_attractions_key(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)
        worker = agent.as_worker()

        state = {"request": _make_request().model_dump()}
        result = worker(state)

        assert "attractions" in result
        assert isinstance(result["attractions"], list)

    def test_worker_attractions_are_dicts(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)
        worker = agent.as_worker()

        state = {"request": _make_request().model_dump()}
        result = worker(state)

        assert all(isinstance(a, dict) for a in result["attractions"])

    def test_worker_attraction_dict_has_required_fields(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)
        worker = agent.as_worker()

        state = {"request": _make_request().model_dump()}
        result = worker(state)

        attraction = result["attractions"][0]
        required = ["name", "address", "location", "visit_duration", "description", "source_url"]
        for field in required:
            assert field in attraction, f"Missing field: {field}"

    def test_worker_fallback_on_empty_search(self) -> None:
        registry = _make_registry_mock(pois=[])
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)
        worker = agent.as_worker()

        state = {"request": _make_request().model_dump()}
        result = worker(state)

        assert len(result["attractions"]) == 3


# ---------------------------------------------------------------------------
# Tests: Registry lazy resolution
# ---------------------------------------------------------------------------

class TestRegistryLazy:
    """Verify registry is lazily resolved when not injected."""

    def test_lazy_resolution(self) -> None:
        mock_registry = _make_registry_mock(pois=[])
        agent = AttractionAgent(retriever=_NULL_RETRIEVER)  # No registry injected

        # Manually set the registry to simulate lazy resolution
        with patch.object(agent, "_registry", None):
            # Patch the import inside the property
            import app.providers.registry as reg_mod
            with patch.object(reg_mod, "get_provider_registry", return_value=mock_registry) as mock_get:
                agent.run(_make_request())
                mock_get.assert_called_once()

    def test_injected_registry_not_lazily_resolved(self) -> None:
        registry = _make_registry_mock(pois=[])
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        # The registry is already set, so lazy resolution should not trigger
        import app.providers.registry as reg_mod
        original_get = reg_mod.get_provider_registry
        call_count = 0

        def tracking_get():
            nonlocal call_count
            call_count += 1
            return original_get()

        reg_mod.get_provider_registry = tracking_get
        try:
            agent.run(_make_request())
            assert call_count == 0, "get_provider_registry should not be called when registry is injected"
        finally:
            reg_mod.get_provider_registry = original_get


# ---------------------------------------------------------------------------
# Tests: Schema compliance
# ---------------------------------------------------------------------------

class TestSchemaCompliance:
    """Verify output matches Attraction schema contract."""

    def test_all_fields_serializable(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        # Should not raise
        data = result[0].model_dump()
        assert isinstance(data, dict)
        assert "name" in data
        assert "source_url" in data
        assert "location" in data

    def test_ticket_price_positive(self) -> None:
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)
        agent = AttractionAgent(registry=registry, retriever=_NULL_RETRIEVER)

        result = agent.run(_make_request())

        assert result[0].ticket_price > 0
