"""Chunk cleaned Wikivoyage pages into RAG-ready ingestion payloads."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.models.schemas import RAGDocument

from .cleaner import CleanedWikivoyagePage


_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？.!?])\s+")


def build_rag_documents(
    pages: list[CleanedWikivoyagePage],
    *,
    chunk_size_chars: int = 900,
    chunk_overlap_chars: int = 120,
) -> list[RAGDocument]:
    """Convert cleaned pages into chunked ``RAGDocument`` items."""
    documents: list[RAGDocument] = []
    for page in pages:
        for chunk in split_text_into_chunks(
            page.content,
            chunk_size_chars=chunk_size_chars,
            chunk_overlap_chars=chunk_overlap_chars,
        ):
            documents.append(
                RAGDocument(
                    page_title=page.page_title,
                    content=chunk,
                    source_url=page.source_url,
                    page_id=page.page_id,
                    revision_id=page.revision_id,
                    retrieved_at=page.retrieved_at,
                )
            )
    return documents


def build_ingest_payloads(
    documents: list[RAGDocument],
    *,
    index_name: str,
) -> list[dict[str, Any]]:
    """Convert chunked documents into ingest-ready payload dictionaries."""
    payloads: list[dict[str, Any]] = []
    for doc in documents:
        payloads.append(
            {
                "index_name": index_name,
                "content": doc.content,
                "metadata": {
                    "page_title": doc.page_title,
                    "page_id": doc.page_id,
                    "revision_id": doc.revision_id,
                    "source_url": doc.source_url,
                    "retrieved_at": doc.retrieved_at,
                },
            }
        )
    return payloads


def export_payloads_jsonl(payloads: list[dict[str, Any]], output_path: str | Path) -> Path:
    """Persist ingest payloads to JSONL for later bridge ingestion."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for payload in payloads:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return path


def split_text_into_chunks(
    text: str,
    *,
    chunk_size_chars: int = 900,
    chunk_overlap_chars: int = 120,
) -> list[str]:
    """Split text into overlapping chunks while preferring sentence boundaries."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    if len(normalized) <= chunk_size_chars:
        return [normalized]

    sentences = [part.strip() for part in _SENTENCE_BOUNDARY_RE.split(normalized) if part.strip()]
    if not sentences:
        return _split_long_text(normalized, chunk_size_chars, chunk_overlap_chars)

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = sentence if not current else f"{current} {sentence}"
        if len(candidate) <= chunk_size_chars:
            current = candidate
            continue

        if current:
            chunks.append(current)
            overlap = current[-chunk_overlap_chars:].strip()
            current = f"{overlap} {sentence}".strip()
        else:
            chunks.extend(_split_long_text(sentence, chunk_size_chars, chunk_overlap_chars))
            current = ""

    if current:
        chunks.append(current)

    deduped: list[str] = []
    for chunk in chunks:
        cleaned = chunk.strip()
        if cleaned and (not deduped or deduped[-1] != cleaned):
            deduped.append(cleaned)
    return deduped


def _split_long_text(text: str, chunk_size_chars: int, chunk_overlap_chars: int) -> list[str]:
    """Fallback splitter for oversized spans with no sentence boundaries."""
    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size_chars - chunk_overlap_chars)
    while start < len(text):
        chunk = text[start : start + chunk_size_chars].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks
