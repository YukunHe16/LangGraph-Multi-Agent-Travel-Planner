"""Pipeline helpers for Wikivoyage dump ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config.settings import get_settings
from app.models.schemas import RAGDocument

from .chunk_exporter import build_ingest_payloads, build_rag_documents, export_payloads_jsonl
from .cleaner import CleanedWikivoyagePage, clean_wikivoyage_page
from .dump_loader import WikivoyageRawPage, iter_wikivoyage_pages


def build_wikivoyage_ingestion_bundle(
    dump_path: str | Path,
    *,
    settings: Any | None = None,
) -> dict[str, list]:
    """Load, clean, chunk, and package a dump for downstream ingestion."""
    settings = settings or get_settings()
    rag_cfg = settings.rag
    wiki_cfg = rag_cfg.wikivoyage

    cleaned_pages: list[CleanedWikivoyagePage] = []
    for page in iter_wikivoyage_pages(dump_path):
        cleaned = clean_wikivoyage_page(
            page,
            allowed_countries=list(rag_cfg.allowed_countries),
            category_roots=list(wiki_cfg.category_roots),
            min_cleaned_chars=wiki_cfg.min_cleaned_chars,
        )
        if cleaned is not None:
            cleaned_pages.append(cleaned)

    documents = build_rag_documents(
        cleaned_pages,
        chunk_size_chars=wiki_cfg.chunk_size_chars,
        chunk_overlap_chars=wiki_cfg.chunk_overlap_chars,
    )
    payloads = build_ingest_payloads(documents, index_name=rag_cfg.index_name)
    return {
        "pages": cleaned_pages,
        "documents": documents,
        "payloads": payloads,
    }


__all__ = [
    "CleanedWikivoyagePage",
    "RAGDocument",
    "WikivoyageRawPage",
    "build_ingest_payloads",
    "build_rag_documents",
    "build_wikivoyage_ingestion_bundle",
    "clean_wikivoyage_page",
    "export_payloads_jsonl",
    "iter_wikivoyage_pages",
]
