"""Full-rebuild ingestion entrypoints for the external RAG bridge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config.settings import get_settings
from app.rag.rag_bridge.external_bridge import BridgeIngestResult, ModularRAGBridge
from app.rag.wikivoyage_ingestion import (
    build_wikivoyage_ingestion_bundle,
    export_payloads_jsonl,
)


@dataclass(slots=True)
class FullRebuildResult:
    """Result object for manual/scheduled full rebuilds."""

    trigger: str
    collection: str
    cleaned_pages: int
    documents: int
    exported_jsonl_path: str
    bridge_result: BridgeIngestResult


def run_manual_full_rebuild(
    dump_path: str | Path,
    *,
    settings: Any | None = None,
    bridge: ModularRAGBridge | None = None,
) -> FullRebuildResult:
    """Trigger a user-initiated full rebuild for the Wikivoyage index."""
    return run_full_rebuild(
        dump_path,
        trigger="manual",
        settings=settings,
        bridge=bridge,
    )


def run_scheduled_full_rebuild(
    dump_path: str | Path,
    *,
    settings: Any | None = None,
    bridge: ModularRAGBridge | None = None,
) -> FullRebuildResult:
    """Trigger a scheduler-initiated full rebuild for the Wikivoyage index."""
    return run_full_rebuild(
        dump_path,
        trigger="scheduled",
        settings=settings,
        bridge=bridge,
    )


def run_full_rebuild(
    dump_path: str | Path,
    *,
    trigger: str,
    settings: Any | None = None,
    bridge: ModularRAGBridge | None = None,
) -> FullRebuildResult:
    """Build D1 artifacts and push them through the external RAG bridge."""
    settings = settings or get_settings()
    bundle = build_wikivoyage_ingestion_bundle(dump_path, settings=settings)
    collection = settings.rag.index_name

    export_dir = Path(__file__).resolve().parents[3] / "data" / "rag_bridge" / collection
    export_path = export_payloads_jsonl(bundle["payloads"], export_dir / "wikivoyage_payloads.jsonl")

    bridge = bridge or ModularRAGBridge(repo_root=settings.rag.mcp_rag_project_root)
    bridge_result = bridge.ingest_documents(
        documents=bundle["documents"],
        collection=collection,
        trigger=trigger,
    )

    return FullRebuildResult(
        trigger=trigger,
        collection=collection,
        cleaned_pages=len(bundle["pages"]),
        documents=len(bundle["documents"]),
        exported_jsonl_path=str(export_path),
        bridge_result=bridge_result,
    )
