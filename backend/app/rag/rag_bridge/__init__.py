"""RAG bridge — connects Project1 to the external MODULAR-RAG-MCP-SERVER.

This sub-package owns:
  • ``query_client.py`` — search the RAG index (Phase D2)
  • ``ingest_runner.py`` — trigger full-rebuild ingestion (Phase D2)
"""

from .external_bridge import BridgeIngestResult, BridgeQueryHit, ModularRAGBridge
from .ingest_runner import (
    FullRebuildResult,
    run_full_rebuild,
    run_manual_full_rebuild,
    run_scheduled_full_rebuild,
)
from .query_client import MCPRAGRetriever

__all__ = [
    "BridgeIngestResult",
    "BridgeQueryHit",
    "FullRebuildResult",
    "MCPRAGRetriever",
    "ModularRAGBridge",
    "run_full_rebuild",
    "run_manual_full_rebuild",
    "run_scheduled_full_rebuild",
]
