"""Integration tests for C8 — AttractionAgent RAG tool integration.

Tests verify:
- RAG retriever is called when enabled
- RAG documents are converted to Attraction models with Wikivoyage source_url
- RAG + map results are merged with deduplication
- RAG failure degrades gracefully to map-only search
- NullRetriever returns empty when RAG is disabled
- as_worker() includes rag_sources in output
- Source URL traceability from Wikivoyage to final output
- AttractionAgent constructor accepts retriever parameter
- RAG search respects preferences parameter
- Edge cases: empty RAG, empty map, both empty
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.workers.attraction_agent import (
    CITY_CENTER,
    AttractionAgent,
    _DEFAULT_VISIT_DURATION,
    _MAX_RAG_DOCS,
)
from app.models.schemas import (
    Attraction,
    Location,
    POIInfo,
    RAGDocument,
    RAGSearchOutput,
    TripRequest,
)
from app.rag.retriever import IRAGRetriever, NullRetriever, reset_rag_retriever


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


def _make_rag_doc(
    page_title: str = "Beijing",
    content: str = "故宫是中国最大的古代宫殿建筑群。",
    source_url: str = "https://en.wikivoyage.org/wiki/Beijing",
    relevance_score: float = 0.92,
) -> RAGDocument:
    """Create a stub RAGDocument."""
    return RAGDocument(
        page_title=page_title,
        content=content,
        source_url=source_url,
        relevance_score=relevance_score,
        retrieved_at=datetime.now(timezone.utc).isoformat(),
    )


def _make_registry_mock(
    pois: list[POIInfo] | None = None,
    photo_url: str | None = "https://images.unsplash.com/test",
    search_raises: bool = False,
    photo_raises: bool = False,
) -> MagicMock:
    """Create a mock ProviderRegistry with map and photo stubs."""
    registry = MagicMock()

    if search_raises:
        registry.map.search_poi.side_effect = RuntimeError("API down")
    else:
        registry.map.search_poi.return_value = pois or []
    registry.map.provider_name = "amap"

    if photo_raises:
        registry.photo.get_photo_url.side_effect = RuntimeError("Photo API down")
    else:
        registry.photo.get_photo_url.return_value = photo_url
    registry.photo.provider_name = "unsplash"

    return registry


class _MockRAGRetriever(IRAGRetriever):
    """In-memory RAG retriever for testing."""

    def __init__(
        self,
        docs: list[RAGDocument] | None = None,
        raises: bool = False,
    ) -> None:
        self._docs = docs or []
        self._raises = raises
        self.call_count = 0
        self.last_destination: str | None = None
        self.last_preferences: list[str] | None = None

    @property
    def provider_name(self) -> str:
        return "mock_rag"

    def search_docs(
        self,
        destination: str,
        *,
        limit: int = 5,
        preferences: list[str] | None = None,
    ) -> RAGSearchOutput:
        self.call_count += 1
        self.last_destination = destination
        self.last_preferences = preferences
        if self._raises:
            raise RuntimeError("RAG service unavailable")
        return RAGSearchOutput(
            provider=self.provider_name,
            items=self._docs[:limit],
        )


# ---------------------------------------------------------------------------
# Test Class: RAG Search Integration
# ---------------------------------------------------------------------------


class TestRAGSearchIntegration:
    """Verify RAG retriever is called and results are merged."""

    def test_rag_docs_become_attractions(self):
        """RAG documents should be converted to Attraction models."""
        docs = [
            _make_rag_doc("Beijing", "故宫是北京必游景点。"),
            _make_rag_doc("Beijing/Dongcheng", "天坛公园世界文化遗产。"),
        ]
        retriever = _MockRAGRetriever(docs=docs)
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert len(result) >= 2
        assert retriever.call_count == 1

    def test_rag_attractions_appear_before_map(self):
        """RAG attractions should precede map attractions in output."""
        rag_doc = _make_rag_doc("Beijing", "故宫知识库内容。")
        retriever = _MockRAGRetriever(docs=[rag_doc])

        pois = [_make_poi("圆明园", 0)]
        registry = _make_registry_mock(pois=pois)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert len(result) == 2
        # RAG result first
        assert result[0].category == "Wikivoyage推荐"
        # Map result second
        assert result[1].name == "圆明园"

    def test_rag_destination_matches_city(self):
        """RAG search should be called with the request city."""
        retriever = _MockRAGRetriever()
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        agent.run(_make_request(city="上海"))

        assert retriever.last_destination == "上海"

    def test_rag_preferences_passed_through(self):
        """RAG search should receive the request preferences."""
        retriever = _MockRAGRetriever()
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        agent.run(_make_request(preferences=["自然风光", "温泉"]))

        assert retriever.last_preferences == ["自然风光", "温泉"]


# ---------------------------------------------------------------------------
# Test Class: Source URL Traceability
# ---------------------------------------------------------------------------


class TestSourceURLTraceability:
    """Verify Wikivoyage source URLs are preserved through the pipeline."""

    def test_rag_attraction_has_wikivoyage_url(self):
        """RAG-sourced attractions must carry Wikivoyage source_url."""
        doc = _make_rag_doc(
            source_url="https://en.wikivoyage.org/wiki/Beijing",
        )
        retriever = _MockRAGRetriever(docs=[doc])
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        rag_attraction = result[0]
        assert "wikivoyage.org" in rag_attraction.source_url

    def test_map_attraction_has_map_url(self):
        """Map-sourced attractions should carry map provider URL."""
        retriever = _MockRAGRetriever()
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        map_attraction = result[0]
        assert "amap" in map_attraction.source_url or "ditu" in map_attraction.source_url

    def test_as_worker_includes_rag_sources(self):
        """as_worker() output should include rag_sources list."""
        doc = _make_rag_doc(
            source_url="https://en.wikivoyage.org/wiki/Beijing",
        )
        retriever = _MockRAGRetriever(docs=[doc])
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        worker = agent.as_worker()
        state = {"request": _make_request().model_dump()}
        output = worker(state)

        assert "rag_sources" in output
        assert len(output["rag_sources"]) >= 1
        assert "wikivoyage.org" in output["rag_sources"][0]


# ---------------------------------------------------------------------------
# Test Class: RAG Document Conversion
# ---------------------------------------------------------------------------


class TestRAGDocConversion:
    """Verify RAG documents are correctly converted to Attractions."""

    def test_page_title_becomes_name(self):
        """Page title should be used as attraction name."""
        doc = _make_rag_doc(page_title="Kyoto")
        retriever = _MockRAGRetriever(docs=[doc])
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request(city="京都"))

        assert result[0].name == "Kyoto"

    def test_sub_page_extracts_subname(self):
        """Sub-page title like 'Beijing/Dongcheng' should extract 'Dongcheng'."""
        doc = _make_rag_doc(page_title="Beijing/Dongcheng")
        retriever = _MockRAGRetriever(docs=[doc])
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert result[0].name == "Dongcheng"

    def test_content_truncated_for_description(self):
        """Long content should be truncated to 200 chars for description."""
        long_content = "A" * 500
        doc = _make_rag_doc(content=long_content)
        retriever = _MockRAGRetriever(docs=[doc])
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert len(result[0].description) == 200

    def test_category_is_wikivoyage(self):
        """RAG attractions should have category 'Wikivoyage推荐'."""
        doc = _make_rag_doc()
        retriever = _MockRAGRetriever(docs=[doc])
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert result[0].category == "Wikivoyage推荐"

    def test_relevance_score_affects_rating(self):
        """Higher relevance_score should produce higher rating."""
        high = _make_rag_doc(page_title="HighRel", relevance_score=0.99)
        low = _make_rag_doc(page_title="LowRel", relevance_score=0.5)
        retriever = _MockRAGRetriever(docs=[high, low])
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert result[0].rating > result[1].rating


# ---------------------------------------------------------------------------
# Test Class: Merge and Deduplication
# ---------------------------------------------------------------------------


class TestMergeDeduplication:
    """Verify RAG + map merge with deduplication by name."""

    def test_same_name_deduplicated(self):
        """If RAG and map return the same attraction name, only RAG version kept."""
        doc = _make_rag_doc(page_title="故宫")
        retriever = _MockRAGRetriever(docs=[doc])
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        # Only one 故宫 should appear
        names = [a.name for a in result]
        assert names.count("故宫") == 1
        # And it should be the RAG version (first)
        assert result[0].category == "Wikivoyage推荐"

    def test_different_names_all_kept(self):
        """Attractions with different names should all appear."""
        doc = _make_rag_doc(page_title="颐和园")
        retriever = _MockRAGRetriever(docs=[doc])
        pois = [_make_poi("故宫"), _make_poi("天坛", 1)]
        registry = _make_registry_mock(pois=pois)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        names = [a.name for a in result]
        assert "颐和园" in names
        assert "故宫" in names
        assert "天坛" in names

    def test_case_insensitive_dedup(self):
        """Deduplication should be case-insensitive."""
        doc = _make_rag_doc(page_title="tokyo")
        retriever = _MockRAGRetriever(docs=[doc])
        # Simulate a map POI named "Tokyo" (different case)
        pois = [_make_poi("Tokyo")]
        registry = _make_registry_mock(pois=pois)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request(city="東京"))

        tokyo_count = sum(1 for a in result if a.name.lower() == "tokyo")
        assert tokyo_count == 1


# ---------------------------------------------------------------------------
# Test Class: Graceful Degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Verify fallback behavior when RAG or map searches fail."""

    def test_rag_failure_falls_back_to_map(self):
        """If RAG raises, should still return map results."""
        retriever = _MockRAGRetriever(raises=True)
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert len(result) >= 1
        assert result[0].name == "故宫"

    def test_rag_empty_uses_map_only(self):
        """If RAG returns nothing, should use map results."""
        retriever = _MockRAGRetriever(docs=[])
        pois = [_make_poi("长城")]
        registry = _make_registry_mock(pois=pois)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert len(result) == 1
        assert result[0].name == "长城"

    def test_map_failure_uses_rag_only(self):
        """If map raises, should still return RAG results."""
        doc = _make_rag_doc(page_title="Beijing")
        retriever = _MockRAGRetriever(docs=[doc])
        registry = _make_registry_mock(search_raises=True)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert len(result) >= 1
        assert result[0].category == "Wikivoyage推荐"

    def test_both_fail_uses_fallback(self):
        """If both RAG and map fail, should use deterministic fallback."""
        retriever = _MockRAGRetriever(raises=True)
        registry = _make_registry_mock(search_raises=True)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert len(result) >= 1
        assert "推荐点" in result[0].name or "fallback" in result[0].name.lower()

    def test_both_empty_uses_fallback(self):
        """If both RAG and map return empty, should use deterministic fallback."""
        retriever = _MockRAGRetriever(docs=[])
        registry = _make_registry_mock(pois=[])

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert len(result) >= 1


# ---------------------------------------------------------------------------
# Test Class: NullRetriever
# ---------------------------------------------------------------------------


class TestNullRetriever:
    """Verify NullRetriever behavior when RAG is disabled."""

    def test_null_returns_empty(self):
        """NullRetriever should always return empty items."""
        null = NullRetriever()
        result = null.search_docs("北京")

        assert result.items == []
        assert result.provider == "null"

    def test_null_provider_name(self):
        """NullRetriever should identify as 'null'."""
        null = NullRetriever()
        assert null.provider_name == "null"

    def test_agent_with_null_retriever_uses_map(self):
        """Agent with NullRetriever should rely entirely on map search."""
        retriever = NullRetriever()
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert len(result) >= 1
        assert result[0].name == "故宫"


# ---------------------------------------------------------------------------
# Test Class: RAG Retriever Factory
# ---------------------------------------------------------------------------


class TestRAGRetrieverFactory:
    """Verify the retriever factory honors settings."""

    def test_enabled_returns_mcp_retriever(self):
        """When rag.enabled=true, factory should return MCPRAGRetriever."""
        reset_rag_retriever()
        try:
            from app.rag.retriever import get_rag_retriever

            retriever = get_rag_retriever()
            # With current settings.yaml (rag.enabled=true), should be mcp_rag
            assert retriever.provider_name == "mcp_rag"
        finally:
            reset_rag_retriever()

    def test_disabled_returns_null_retriever(self):
        """When rag.enabled=false, factory should return NullRetriever."""
        reset_rag_retriever()
        try:
            from app.config.settings import RAGSettings, Settings
            from app.rag.retriever import _build_retriever

            # Build a settings object with RAG disabled
            disabled_settings = Settings(
                rag=RAGSettings(enabled=False),
            )
            with patch(
                "app.config.settings.get_settings",
                return_value=disabled_settings,
            ):
                retriever = _build_retriever()
                assert retriever.provider_name == "null"
        finally:
            reset_rag_retriever()

    def test_reset_clears_singleton(self):
        """reset_rag_retriever() should clear the cached singleton."""
        from app.rag.retriever import get_rag_retriever

        reset_rag_retriever()
        r1 = get_rag_retriever()
        reset_rag_retriever()
        r2 = get_rag_retriever()

        # After reset, a new instance should be created
        assert r1 is not r2


# ---------------------------------------------------------------------------
# Test Class: as_worker Protocol
# ---------------------------------------------------------------------------


class TestAsWorkerProtocol:
    """Verify as_worker() compatibility with PlannerAgent."""

    def test_worker_returns_attractions_key(self):
        """Worker output must contain 'attractions' key."""
        retriever = _MockRAGRetriever()
        pois = [_make_poi("故宫")]
        registry = _make_registry_mock(pois=pois)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        worker = agent.as_worker()
        state = {"request": _make_request().model_dump()}
        output = worker(state)

        assert "attractions" in output
        assert isinstance(output["attractions"], list)

    def test_worker_returns_rag_sources_key(self):
        """Worker output must contain 'rag_sources' key (C8)."""
        retriever = _MockRAGRetriever()
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        worker = agent.as_worker()
        state = {"request": _make_request().model_dump()}
        output = worker(state)

        assert "rag_sources" in output
        assert isinstance(output["rag_sources"], list)

    def test_worker_rag_sources_only_wikivoyage(self):
        """rag_sources should only contain wikivoyage.org URLs."""
        doc = _make_rag_doc(
            source_url="https://en.wikivoyage.org/wiki/Beijing",
        )
        retriever = _MockRAGRetriever(docs=[doc])
        pois = [_make_poi("天坛")]
        registry = _make_registry_mock(pois=pois)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        worker = agent.as_worker()
        state = {"request": _make_request().model_dump()}
        output = worker(state)

        for url in output["rag_sources"]:
            assert "wikivoyage.org" in url


# ---------------------------------------------------------------------------
# Test Class: MCPRAGRetriever Stub
# ---------------------------------------------------------------------------


class TestMCPRAGRetrieverStub:
    """Verify the stub MCPRAGRetriever returns curated data."""

    def test_beijing_returns_docs(self):
        """Stub should return docs for 北京."""
        from app.rag.rag_bridge.query_client import MCPRAGRetriever

        retriever = MCPRAGRetriever()
        result = retriever.search_docs("北京")

        assert len(result.items) > 0
        assert result.provider == "mcp_rag"

    def test_unknown_city_returns_empty(self):
        """Stub should return empty for unknown cities."""
        from app.rag.rag_bridge.query_client import MCPRAGRetriever

        retriever = MCPRAGRetriever()
        result = retriever.search_docs("乌鲁木齐")

        assert len(result.items) == 0

    def test_docs_have_source_url(self):
        """All stub docs should have valid source_url."""
        from app.rag.rag_bridge.query_client import MCPRAGRetriever

        retriever = MCPRAGRetriever()
        result = retriever.search_docs("东京")

        for doc in result.items:
            assert doc.source_url
            assert "wikivoyage.org" in doc.source_url

    def test_docs_have_retrieved_at(self):
        """All stub docs should have retrieved_at timestamp."""
        from app.rag.rag_bridge.query_client import MCPRAGRetriever

        retriever = MCPRAGRetriever()
        result = retriever.search_docs("京都")

        for doc in result.items:
            assert doc.retrieved_at is not None

    def test_limit_respected(self):
        """Stub should respect the limit parameter."""
        from app.rag.rag_bridge.query_client import MCPRAGRetriever

        retriever = MCPRAGRetriever()
        result = retriever.search_docs("北京", limit=1)

        assert len(result.items) <= 1


# ---------------------------------------------------------------------------
# Test Class: Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Verify edge case handling."""

    def test_empty_preferences(self):
        """Should work with empty preferences list."""
        retriever = _MockRAGRetriever()
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request(preferences=[]))

        assert isinstance(result, list)

    def test_rag_doc_empty_title(self):
        """RAG doc with empty title should get a fallback name."""
        doc = _make_rag_doc(page_title="")
        retriever = _MockRAGRetriever(docs=[doc])
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert result[0].name  # Should not be empty

    def test_rag_doc_city_as_title(self):
        """When page_title equals city name, should get a qualified name."""
        doc = _make_rag_doc(page_title="北京")
        retriever = _MockRAGRetriever(docs=[doc])
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request(city="北京"))

        # Should fallback to "北京Wikivoyage推荐景点1" since title == city
        assert "Wikivoyage" in result[0].name

    def test_photo_failure_still_returns_attraction(self):
        """Photo fetch failure should not break RAG attraction creation."""
        doc = _make_rag_doc()
        retriever = _MockRAGRetriever(docs=[doc])
        registry = _make_registry_mock(photo_raises=True)

        agent = AttractionAgent(registry=registry, retriever=retriever)
        result = agent.run(_make_request())

        assert len(result) >= 1
        assert result[0].image_url is None

    def test_constructor_accepts_both_params(self):
        """AttractionAgent constructor should accept registry and retriever."""
        retriever = NullRetriever()
        registry = _make_registry_mock()

        agent = AttractionAgent(registry=registry, retriever=retriever)
        assert agent._retriever is retriever
        assert agent._registry is registry
