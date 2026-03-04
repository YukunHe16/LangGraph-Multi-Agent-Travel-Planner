"""RAG bridge — connects Project1 to the external MODULAR-RAG-MCP-SERVER.

This sub-package owns:
  • ``query_client.py`` — search the RAG index (Phase D2)
  • ``ingest_runner.py`` — trigger full-rebuild ingestion (Phase D1)

Until D1/D2 are implemented, ``query_client`` exposes a stub
``MCPRAGRetriever`` that the retriever factory can attempt to import.
"""
