"""RAG (Retrieval-Augmented Generation) subsystem.

Provides destination knowledge retrieval for AttractionAgent via a pluggable
retriever interface.  The actual data pipeline (Wikivoyage ingestion) and
external MCP RAG bridge are implemented in Phase D; this package exposes
the contracts and factory used by C8 onwards.
"""

from app.rag.retriever import IRAGRetriever, get_rag_retriever, reset_rag_retriever

__all__ = [
    "IRAGRetriever",
    "get_rag_retriever",
    "reset_rag_retriever",
]
