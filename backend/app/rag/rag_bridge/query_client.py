"""RAG bridge query client with external bridge + stub fallback."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config.settings import get_settings
from app.models.schemas import RAGDocument, RAGSearchOutput
from app.rag.retriever import IRAGRetriever
from .external_bridge import BridgeQueryHit, ModularRAGBridge

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

    D2 implementation:
    - Uses ``ModularRAGBridge`` to call the external repo's query stack.
    - Falls back to curated stub documents when the bridge is unavailable,
      preserving existing AttractionAgent tests and offline development.
    """

    def __init__(
        self,
        *,
        settings: Any | None = None,
        bridge: ModularRAGBridge | None = None,
        use_stub_fallback: bool = True,
    ) -> None:
        self._settings = settings or get_settings()
        self._bridge = bridge
        self._use_stub_fallback = use_stub_fallback

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
        search_query = destination.strip()
        if preferences:
            search_query = f"{search_query} {' '.join(preferences)}".strip()

        try:
            bridge = self._bridge or ModularRAGBridge(
                repo_root=self._settings.rag.mcp_rag_project_root,
            )
            hits = bridge.query(
                query=search_query,
                collection=self._settings.rag.index_name,
                limit=limit,
            )
            docs = [_hit_to_document(hit) for hit in hits]
            logger.info(
                "MCPRAGRetriever bridge returned %d docs for destination=%s",
                len(docs),
                destination,
            )
            return RAGSearchOutput(provider=self.provider_name, items=docs)
        except Exception as exc:
            logger.warning("External RAG bridge query failed, using stub fallback: %s", exc)
            if not self._use_stub_fallback:
                raise
            return _build_stub_output(destination, limit)


def _build_stub_output(destination: str, limit: int) -> RAGSearchOutput:
    """Build curated fallback documents for offline/test environments."""
    stub_entries = _STUB_DOCS.get(destination, [])
    if not stub_entries:
        logger.debug("No stub docs for destination=%s", destination)
        return RAGSearchOutput(provider="mcp_rag", items=[])

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
    return RAGSearchOutput(provider="mcp_rag", items=docs)


def _hit_to_document(hit: BridgeQueryHit) -> RAGDocument:
    """Map a bridge hit into Project1's ``RAGDocument`` schema."""
    return RAGDocument(
        page_title=hit.page_title,
        content=hit.content,
        source_url=hit.source_url,
        relevance_score=hit.relevance_score,
        page_id=hit.page_id,
        revision_id=hit.revision_id,
        retrieved_at=hit.retrieved_at,
    )
