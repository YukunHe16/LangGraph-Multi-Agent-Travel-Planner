"""Integration tests for Phase D2 RAG bridge retrieval and rebuild entrypoints."""

from __future__ import annotations

import bz2
from pathlib import Path

from app.config.settings import Settings
from app.models.schemas import RAGDocument
from app.rag.rag_bridge.external_bridge import BridgeIngestResult, BridgeQueryHit
from app.rag.rag_bridge.ingest_runner import (
    run_manual_full_rebuild,
    run_scheduled_full_rebuild,
)
from app.rag.rag_bridge.query_client import MCPRAGRetriever


_SAMPLE_DUMP = """<mediawiki xmlns="http://www.mediawiki.org/xml/export-0.11/">
  <page>
    <title>Beijing</title>
    <ns>0</ns>
    <id>101</id>
    <revision>
      <id>5001</id>
      <text xml:space="preserve">[[Category:Cities in China]]
| country = China
'''Beijing''' is the capital of China and includes the Forbidden City.
Temple of Heaven and hutongs provide more cultural context for travelers.</text>
    </revision>
  </page>
</mediawiki>
"""


def _write_dump(path: Path) -> Path:
    path.write_bytes(bz2.compress(_SAMPLE_DUMP.encode("utf-8")))
    return path


def _build_settings(tmp_path: Path) -> Settings:
    settings = Settings()
    settings.rag.enabled = True
    settings.rag.index_name = "wikivoyage_cn_jp_attractions"
    settings.rag.allowed_countries = ["China", "Japan"]
    settings.rag.wikivoyage.min_cleaned_chars = 30
    settings.rag.wikivoyage.chunk_size_chars = 120
    settings.rag.wikivoyage.chunk_overlap_chars = 20
    settings.rag.mcp_rag_project_root = str(tmp_path / "external-rag")
    return settings


class _RecordingBridge:
    """Test double for the external bridge adapter."""

    def __init__(self, *, hits: list[BridgeQueryHit] | None = None) -> None:
        self.hits = hits or []
        self.ingest_calls: list[dict] = []
        self.query_calls: list[dict] = []

    def ingest_documents(self, *, documents, collection, trigger):
        self.ingest_calls.append(
            {
                "documents": list(documents),
                "collection": collection,
                "trigger": trigger,
            }
        )
        return BridgeIngestResult(
            collection=collection,
            trigger=trigger,
            documents_written=len(documents),
            bm25_index_path=f"/tmp/{collection}_bm25.json",
        )

    def query(self, *, query, collection, limit):
        self.query_calls.append(
            {"query": query, "collection": collection, "limit": limit}
        )
        return self.hits[:limit]


class _FailingBridge:
    """Bridge double that forces stub fallback paths."""

    def query(self, *, query, collection, limit):
        raise RuntimeError("bridge unavailable")


class TestRAGRetrievalService:
    """Integration coverage for D2 bridge entrypoints."""

    def test_manual_full_rebuild_pushes_documents_into_bridge(self, tmp_path: Path) -> None:
        dump_path = _write_dump(tmp_path / "wikivoyage.xml.bz2")
        settings = _build_settings(tmp_path)
        bridge = _RecordingBridge()

        result = run_manual_full_rebuild(dump_path, settings=settings, bridge=bridge)

        assert result.trigger == "manual"
        assert result.collection == settings.rag.index_name
        assert result.cleaned_pages == 1
        assert result.documents >= 1
        assert Path(result.exported_jsonl_path).exists()
        assert bridge.ingest_calls[0]["trigger"] == "manual"
        assert bridge.ingest_calls[0]["collection"] == settings.rag.index_name
        first_document = bridge.ingest_calls[0]["documents"][0]
        assert isinstance(first_document, RAGDocument)
        assert first_document.page_title == "Beijing"

    def test_scheduled_full_rebuild_marks_trigger_type(self, tmp_path: Path) -> None:
        dump_path = _write_dump(tmp_path / "wikivoyage.xml.bz2")
        settings = _build_settings(tmp_path)
        bridge = _RecordingBridge()

        result = run_scheduled_full_rebuild(dump_path, settings=settings, bridge=bridge)

        assert result.trigger == "scheduled"
        assert bridge.ingest_calls[0]["trigger"] == "scheduled"

    def test_query_client_maps_bridge_hits_to_rag_documents(self, tmp_path: Path) -> None:
        settings = _build_settings(tmp_path)
        bridge = _RecordingBridge(
            hits=[
                BridgeQueryHit(
                    page_title="Beijing",
                    content="Forbidden City is a palace complex.",
                    source_url="https://en.wikivoyage.org/wiki/Beijing",
                    relevance_score=0.91,
                    page_id="101",
                    revision_id="5001",
                    retrieved_at="2026-03-13T00:00:00+00:00",
                )
            ]
        )
        retriever = MCPRAGRetriever(settings=settings, bridge=bridge)

        result = retriever.search_docs("北京", limit=3, preferences=["历史", "美食"])

        assert result.provider == "mcp_rag"
        assert len(result.items) == 1
        assert result.items[0].page_title == "Beijing"
        assert result.items[0].page_id == "101"
        assert bridge.query_calls[0]["collection"] == settings.rag.index_name
        assert "历史" in bridge.query_calls[0]["query"]

    def test_query_client_falls_back_to_stub_on_bridge_failure(self, tmp_path: Path) -> None:
        settings = _build_settings(tmp_path)
        retriever = MCPRAGRetriever(settings=settings, bridge=_FailingBridge())

        result = retriever.search_docs("北京", limit=2)

        assert result.items
        assert result.items[0].source_url.startswith("https://en.wikivoyage.org/wiki/")
