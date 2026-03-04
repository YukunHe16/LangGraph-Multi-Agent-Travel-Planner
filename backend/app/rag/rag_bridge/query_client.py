"""RAG bridge query client — stub for Phase D2 implementation.

This module will eventually call ``MODULAR-RAG-MCP-SERVER`` to perform
semantic search over the Wikivoyage index.  For now it provides a
``MCPRAGRetriever`` that returns curated stub data so that the
AttractionAgent RAG integration (C8) can be tested end-to-end without
the external server running.

Phase D2 will replace the stub logic with real HTTP/MCP calls while
keeping the same ``IRAGRetriever`` interface.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.models.schemas import RAGDocument, RAGSearchOutput
from app.rag.retriever import IRAGRetriever

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Curated stub knowledge — used until D2 wires real MCP RAG
# ---------------------------------------------------------------------------

_STUB_DOCS: dict[str, list[dict]] = {
    "北京": [
        {
            "page_title": "Beijing",
            "content": "北京故宫是中国最大的古代宫殿建筑群，位于北京市中心，是明清两代皇宫。"
                       "建议游览时间3-4小时，门票60元。周边有景山公园和北海公园。",
            "source_url": "https://en.wikivoyage.org/wiki/Beijing",
            "relevance_score": 0.95,
        },
        {
            "page_title": "Beijing/Dongcheng",
            "content": "天坛公园是世界文化遗产，明清帝王祭天的场所。"
                       "祈年殿是其标志性建筑。门票联票34元，建议游览2-3小时。",
            "source_url": "https://en.wikivoyage.org/wiki/Beijing/Dongcheng",
            "relevance_score": 0.88,
        },
    ],
    "上海": [
        {
            "page_title": "Shanghai",
            "content": "外滩是上海最著名的景点之一，沿黄浦江西岸延伸约1.5公里，"
                       "汇集了52幢风格各异的历史建筑。免费参观，建议傍晚前往欣赏夜景。",
            "source_url": "https://en.wikivoyage.org/wiki/Shanghai",
            "relevance_score": 0.92,
        },
    ],
    "东京": [
        {
            "page_title": "Tokyo",
            "content": "浅草寺是东京最古老的寺庙，建于公元628年。"
                       "雷门和仲见世通商业街是必游之地。免费参观，建议游览1-2小时。",
            "source_url": "https://en.wikivoyage.org/wiki/Tokyo",
            "relevance_score": 0.90,
        },
    ],
    "京都": [
        {
            "page_title": "Kyoto",
            "content": "金阁寺（鹿苑寺）是京都最著名的景点之一，"
                       "金色的楼阁倒映在镜湖池中。门票400日元，建议游览1-2小时。",
            "source_url": "https://en.wikivoyage.org/wiki/Kyoto",
            "relevance_score": 0.93,
        },
    ],
}


class MCPRAGRetriever(IRAGRetriever):
    """Bridge retriever that queries the external MCP RAG server.

    **Current status (C8 stub)**:
    Returns curated stub data for selected Chinese/Japanese destinations.
    Phase D2 will replace the body of ``search_docs`` with real MCP calls
    while preserving this class's contract.

    **Phase D2 plan**:
    - Read ``rag.mcp_rag_project_root`` from settings
    - Call the MCP RAG server's query endpoint via HTTP/subprocess
    - Map response documents to ``RAGDocument`` schema
    """

    @property
    def provider_name(self) -> str:
        return "mcp_rag"

    def search_docs(
        self,
        destination: str,
        *,
        limit: int = 5,
        preferences: list[str] | None = None,
    ) -> RAGSearchOutput:
        """Search Wikivoyage knowledge base for destination info.

        Args:
            destination: City or region name.
            limit: Maximum documents to return.
            preferences: Optional tags to refine search (future use).

        Returns:
            ``RAGSearchOutput`` with matching ``RAGDocument`` items.
        """
        logger.info(
            "MCPRAGRetriever.search_docs: destination=%s limit=%d preferences=%s",
            destination,
            limit,
            preferences,
        )

        # --- Stub implementation (C8) ---
        # Phase D2 will replace this block with real MCP RAG calls.
        stub_entries = _STUB_DOCS.get(destination, [])

        if not stub_entries:
            logger.debug("No stub docs for destination=%s", destination)
            return RAGSearchOutput(provider=self.provider_name, items=[])

        now = datetime.now(timezone.utc).isoformat()
        docs = [
            RAGDocument(
                page_title=entry["page_title"],
                content=entry["content"],
                source_url=entry["source_url"],
                relevance_score=entry.get("relevance_score", 0.0),
                retrieved_at=now,
            )
            for entry in stub_entries[:limit]
        ]

        logger.info(
            "MCPRAGRetriever returned %d docs for destination=%s",
            len(docs),
            destination,
        )
        return RAGSearchOutput(provider=self.provider_name, items=docs)
