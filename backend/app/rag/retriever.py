"""RAG retriever abstraction — pluggable interface for destination knowledge search.

Design:
  • ``IRAGRetriever`` defines the contract any retriever must satisfy.
  • ``get_rag_retriever()`` returns a module-level singleton built from
    ``settings.yaml`` (``rag.enabled`` / ``rag.integration_mode``).
  • When ``rag.enabled=false`` or settings are absent, a ``NullRetriever``
    is returned that always yields empty results — callers never need to
    check feature flags themselves.
  • The real MCP-bridge retriever is implemented in Phase D2
    (``rag_bridge.query_client``); once ready it plugs into the same
    factory without touching AttractionAgent.

RAG documents carry mandatory provenance fields:
  ``page_title``, ``source_url``, ``retrieved_at``
so that downstream consumers can produce traceable citations.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.models.schemas import RAGDocument, RAGSearchInput, RAGSearchOutput

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ── Abstract interface ────────────────────────────────────────────────

class IRAGRetriever(ABC):
    """Contract for all RAG retriever implementations.

    Implementers must override ``search_docs`` and ``provider_name``.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable identifier (e.g. ``"mcp_rag"``, ``"null"``)."""

    @abstractmethod
    def search_docs(
        self,
        destination: str,
        *,
        limit: int = 5,
        preferences: list[str] | None = None,
    ) -> RAGSearchOutput:
        """Search the knowledge base for destination-relevant documents.

        Args:
            destination: City or region name (e.g. ``"京都"``).
            limit: Maximum number of documents to return.
            preferences: Optional preference tags to refine the query.

        Returns:
            ``RAGSearchOutput`` with zero or more ``RAGDocument`` items.
        """


# ── Null implementation (RAG disabled / not yet wired) ────────────────

class NullRetriever(IRAGRetriever):
    """No-op retriever used when RAG is disabled or not yet configured.

    Always returns an empty result set so that callers can treat the
    retriever uniformly without feature-flag checks.
    """

    @property
    def provider_name(self) -> str:
        return "null"

    def search_docs(
        self,
        destination: str,
        *,
        limit: int = 5,
        preferences: list[str] | None = None,
    ) -> RAGSearchOutput:
        logger.debug(
            "NullRetriever.search_docs called (RAG disabled): destination=%s",
            destination,
        )
        return RAGSearchOutput(provider="null", items=[])


# ── Factory / singleton ──────────────────────────────────────────────

_retriever: IRAGRetriever | None = None


def _build_retriever() -> IRAGRetriever:
    """Construct a retriever based on ``settings.yaml`` configuration.

    Currently returns ``NullRetriever`` unless ``rag.enabled=true`` AND
    ``rag.integration_mode=external_mcp_rag``, in which case it defers
    to the bridge query client (Phase D2 — imported lazily to avoid
    circular dependencies before D2 is implemented).
    """
    try:
        from app.config.settings import get_settings

        settings = get_settings()
        rag_cfg = getattr(settings, "rag", None)
    except Exception:
        logger.debug("Settings unavailable — using NullRetriever")
        return NullRetriever()

    if rag_cfg is None:
        logger.info("No 'rag' section in settings — RAG disabled")
        return NullRetriever()

    enabled = rag_cfg.get("enabled", False) if isinstance(rag_cfg, dict) else getattr(rag_cfg, "enabled", False)
    if not enabled:
        logger.info("rag.enabled=false — using NullRetriever")
        return NullRetriever()

    mode = (
        rag_cfg.get("integration_mode", "")
        if isinstance(rag_cfg, dict)
        else getattr(rag_cfg, "integration_mode", "")
    )

    if mode == "external_mcp_rag":
        try:
            from app.rag.rag_bridge.query_client import MCPRAGRetriever

            logger.info("RAG enabled — using MCPRAGRetriever (external_mcp_rag)")
            return MCPRAGRetriever()
        except ImportError:
            logger.warning(
                "MCPRAGRetriever not available yet (Phase D2) — falling back to NullRetriever"
            )
            return NullRetriever()

    logger.warning("Unknown rag.integration_mode=%s — using NullRetriever", mode)
    return NullRetriever()


def get_rag_retriever() -> IRAGRetriever:
    """Return (or create) the module-level retriever singleton."""
    global _retriever
    if _retriever is None:
        _retriever = _build_retriever()
        logger.info(
            "RAG retriever initialised: provider=%s", _retriever.provider_name
        )
    return _retriever


def reset_rag_retriever() -> None:
    """Reset the retriever singleton — intended for tests only."""
    global _retriever
    _retriever = None
    logger.debug("RAG retriever singleton reset")
