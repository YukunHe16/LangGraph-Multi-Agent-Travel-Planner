"""Shared bridge adapter for the external Modular RAG repository."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import unquote, urlparse

from app.models.schemas import RAGDocument


@dataclass(slots=True)
class BridgeQueryHit:
    """Structured query result returned by the external RAG bridge."""

    page_title: str
    content: str
    source_url: str
    relevance_score: float
    page_id: str | None = None
    revision_id: str | None = None
    retrieved_at: str | None = None


@dataclass(slots=True)
class BridgeIngestResult:
    """Structured ingestion result returned by the external RAG bridge."""

    collection: str
    trigger: str
    documents_written: int
    bm25_index_path: str


class ModularRAGBridge:
    """Adapter that calls the external Modular RAG repository in-process."""

    def __init__(
        self,
        *,
        repo_root: str | Path,
        config_path: str | Path | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.config_path = (
            Path(config_path).expanduser().resolve()
            if config_path is not None
            else self.repo_root / "config" / "settings.yaml"
        )

    def query(
        self,
        *,
        query: str,
        collection: str,
        limit: int = 5,
    ) -> list[BridgeQueryHit]:
        """Query the external HybridSearch stack and map results to bridge hits."""
        if not query.strip():
            return []

        with self._activate_repo():
            from src.core.query_engine.dense_retriever import create_dense_retriever
            from src.core.query_engine.hybrid_search import create_hybrid_search
            from src.core.query_engine.query_processor import QueryProcessor
            from src.core.query_engine.sparse_retriever import create_sparse_retriever
            from src.core.settings import load_settings
            from src.ingestion.storage.bm25_indexer import BM25Indexer
            from src.libs.embedding.embedding_factory import EmbeddingFactory
            from src.libs.vector_store.vector_store_factory import VectorStoreFactory

            settings = load_settings(str(self.config_path))
            vector_store = VectorStoreFactory.create(settings, collection_name=collection)
            embedding_client = EmbeddingFactory.create(settings)
            dense_retriever = create_dense_retriever(
                settings=settings,
                embedding_client=embedding_client,
                vector_store=vector_store,
            )
            sparse_retriever = create_sparse_retriever(
                settings=settings,
                bm25_indexer=BM25Indexer(index_dir=str(self.repo_root / "data" / "db" / "bm25")),
                vector_store=vector_store,
            )
            sparse_retriever.default_collection = collection

            hybrid_search = create_hybrid_search(
                settings=settings,
                query_processor=QueryProcessor(),
                dense_retriever=dense_retriever,
                sparse_retriever=sparse_retriever,
            )
            results = hybrid_search.search(query=query, top_k=limit)

        now = datetime.now(timezone.utc).isoformat()
        hits: list[BridgeQueryHit] = []
        for result in results:
            metadata = result.metadata or {}
            source_url = str(metadata.get("source_url") or metadata.get("source_path") or "").strip()
            page_title = str(metadata.get("page_title") or _derive_page_title(source_url) or "Untitled")
            hits.append(
                BridgeQueryHit(
                    page_title=page_title,
                    content=result.text,
                    source_url=source_url,
                    relevance_score=_normalize_score(result.score),
                    page_id=_optional_text(metadata.get("page_id")),
                    revision_id=_optional_text(metadata.get("revision_id")),
                    retrieved_at=_optional_text(metadata.get("retrieved_at")) or now,
                )
            )
        return hits

    def ingest_documents(
        self,
        *,
        documents: Sequence[RAGDocument],
        collection: str,
        trigger: str,
    ) -> BridgeIngestResult:
        """Embed and ingest D1-produced documents into the external RAG backends."""
        if not documents:
            raise ValueError("documents cannot be empty")

        with self._activate_repo():
            from src.core.settings import load_settings
            from src.core.types import Chunk
            from src.ingestion.embedding.sparse_encoder import SparseEncoder
            from src.ingestion.storage.bm25_indexer import BM25Indexer
            from src.ingestion.storage.vector_upserter import VectorUpserter
            from src.libs.embedding.embedding_factory import EmbeddingFactory
            from src.libs.vector_store.vector_store_factory import VectorStoreFactory

            settings = load_settings(str(self.config_path))
            vector_store = VectorStoreFactory.create(settings, collection_name=collection)
            try:
                vector_store.clear(collection_name=collection)
            except NotImplementedError:
                pass

            chunks = [
                Chunk(
                    id=f"wikivoyage_{idx}",
                    text=document.content,
                    metadata={
                        "source_path": document.source_url,
                        "source_url": document.source_url,
                        "page_title": document.page_title,
                        "page_id": document.page_id or "",
                        "revision_id": document.revision_id or "",
                        "retrieved_at": document.retrieved_at or "",
                        "chunk_index": idx,
                        "collection": collection,
                    },
                )
                for idx, document in enumerate(documents)
            ]

            embedding_client = EmbeddingFactory.create(settings)
            vectors = embedding_client.embed([chunk.text for chunk in chunks])

            upserter = VectorUpserter(settings, collection_name=collection)
            chunk_ids = upserter.upsert(chunks, vectors)

            sparse_encoder = SparseEncoder()
            term_stats = sparse_encoder.encode(chunks)
            for stat, chunk_id in zip(term_stats, chunk_ids):
                stat["chunk_id"] = chunk_id

            bm25_indexer = BM25Indexer(index_dir=str(self.repo_root / "data" / "db" / "bm25"))
            bm25_indexer.build(term_stats, collection=collection)
            bm25_index_path = str(self.repo_root / "data" / "db" / "bm25" / f"{collection}_bm25.json")

        return BridgeIngestResult(
            collection=collection,
            trigger=trigger,
            documents_written=len(documents),
            bm25_index_path=bm25_index_path,
        )

    @contextmanager
    def _activate_repo(self) -> Iterator[None]:
        """Temporarily add the external repo root to ``sys.path`` for imports."""
        if not self.repo_root.exists():
            raise FileNotFoundError(f"External RAG repo not found: {self.repo_root}")
        sys.path.insert(0, str(self.repo_root))
        try:
            yield
        finally:
            if sys.path and sys.path[0] == str(self.repo_root):
                sys.path.pop(0)


def _normalize_score(score: float) -> float:
    """Clamp arbitrary retrieval scores to the ``RAGDocument`` range."""
    return max(0.0, min(float(score), 1.0))


def _optional_text(value: Any) -> str | None:
    """Return a stripped string or ``None`` for empty values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _derive_page_title(source_url: str) -> str | None:
    """Derive a Wikivoyage page title from the URL path."""
    if not source_url:
        return None
    parsed = urlparse(source_url)
    path = parsed.path.rsplit("/", 1)[-1]
    if not path:
        return None
    return unquote(path).replace("_", " ")
