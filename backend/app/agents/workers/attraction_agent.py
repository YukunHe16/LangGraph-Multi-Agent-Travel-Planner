"""AttractionAgent — LangGraph worker that searches attractions via pluggable providers.

Rewritten for C2 to use ProviderRegistry instead of hard-coded services.
Enhanced in C8 to integrate RAG tool for Wikivoyage knowledge retrieval.
Retains backward-compatible ``run()`` signature and adds ``as_worker()``
for the PlannerAgent WorkerFn protocol.

C8 RAG integration strategy:
  1. If RAG is enabled, search Wikivoyage docs for destination first.
  2. Merge RAG-sourced attractions with map POI search results.
  3. RAG-sourced attractions carry ``source_url`` from Wikivoyage.
  4. If RAG fails or returns empty, fall back to map-only search.

Source prompt: trip_planner_agent.py ATTRACTION_AGENT_PROMPT (migrated in A2).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from app.models.schemas import Attraction, Location, RAGDocument, TripRequest
from app.prompts.trip_prompts import ATTRACTION_AGENT_PROMPT

if TYPE_CHECKING:
    from app.providers.registry import ProviderRegistry
    from app.rag.retriever import IRAGRetriever

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fallback city-center coordinates (used when POI search returns nothing)
# ---------------------------------------------------------------------------

CITY_CENTER: dict[str, tuple[float, float]] = {
    "北京": (116.397128, 39.916527),
    "上海": (121.4737, 31.2304),
    "广州": (113.2644, 23.1291),
    "深圳": (114.0579, 22.5431),
    "成都": (104.0665, 30.5723),
    "杭州": (120.1551, 30.2741),
    "西安": (108.9402, 34.3416),
    "南京": (118.7969, 32.0603),
    "重庆": (106.5516, 29.5630),
    "武汉": (114.3054, 30.5931),
}

# Maximum POIs to fetch per search
_MAX_POIS = 6

# Maximum RAG documents to fetch per search
_MAX_RAG_DOCS = 5

# Default visit duration in minutes
_DEFAULT_VISIT_DURATION = 120


class AttractionAgent:
    """Search and rank attraction candidates for a given city and preferences.

    Uses ``ProviderRegistry`` to access map (POI search) and photo providers,
    and ``IRAGRetriever`` to search Wikivoyage knowledge base for
    destination-specific attraction information (C8).

    RAG integration follows a **merge strategy**:
    - RAG docs are converted to ``Attraction`` models with Wikivoyage source_url.
    - Map POI results are appended after RAG-sourced attractions.
    - Deduplication by name prevents showing the same attraction twice.
    - If RAG fails, the agent silently falls back to map-only search.

    Args:
        registry: Optional pre-built ``ProviderRegistry``. When *None*,
            the module-level singleton is resolved lazily on first call.
        retriever: Optional pre-built ``IRAGRetriever``. When *None*,
            the module-level singleton is resolved lazily on first call.
    """

    prompt: str = ATTRACTION_AGENT_PROMPT

    def __init__(
        self,
        registry: "ProviderRegistry | None" = None,
        retriever: "IRAGRetriever | None" = None,
    ) -> None:
        self._registry = registry
        self._retriever = retriever

    # ------------------------------------------------------------------
    # Provider access (lazy)
    # ------------------------------------------------------------------

    @property
    def _reg(self) -> "ProviderRegistry":
        """Lazy-resolve the provider registry."""
        if self._registry is None:
            from app.providers.registry import get_provider_registry

            self._registry = get_provider_registry()
        return self._registry

    @property
    def _rag(self) -> "IRAGRetriever":
        """Lazy-resolve the RAG retriever."""
        if self._retriever is None:
            from app.rag.retriever import get_rag_retriever

            self._retriever = get_rag_retriever()
        return self._retriever

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def run(self, request: TripRequest) -> list[Attraction]:
        """Return attraction candidates using RAG + map + photo providers.

        C8 strategy:
        1. Search Wikivoyage via RAG retriever (if enabled).
        2. Search map POIs via map provider.
        3. Merge RAG-sourced attractions (first) with map attractions.
        4. Deduplicate by name.
        5. Return combined list; never empty (falls back to deterministic defaults).

        Args:
            request: A ``TripRequest`` with at least ``city`` populated.

        Returns:
            A list of ``Attraction`` models; never empty.
        """
        keyword = request.preferences[0] if request.preferences else "景点"
        logger.info("AttractionAgent.run: city=%s keyword=%s", request.city, keyword)

        # Step 1: RAG search (best-effort)
        rag_attractions = self._search_rag(request.city, request.preferences)

        # Step 2: Map POI search
        map_attractions = self._search_map(request.city, keyword)

        # Step 3: Merge and deduplicate
        merged = self._merge_attractions(rag_attractions, map_attractions)

        if merged:
            return merged

        # Step 4: Fallback when both RAG and map return nothing
        logger.info("No attractions found, using fallback for %s", request.city)
        return self._build_fallback(request.city, keyword)

    # ------------------------------------------------------------------
    # RAG search (C8)
    # ------------------------------------------------------------------

    def _search_rag(
        self,
        city: str,
        preferences: list[str] | None = None,
    ) -> list[Attraction]:
        """Search Wikivoyage knowledge base for destination attractions.

        Returns a list of ``Attraction`` models built from RAG documents.
        On failure, returns an empty list (graceful degradation).
        """
        try:
            result = self._rag.search_docs(
                destination=city,
                limit=_MAX_RAG_DOCS,
                preferences=preferences,
            )
        except Exception:
            logger.warning(
                "RAG search failed for city=%s, degrading to map-only",
                city,
                exc_info=True,
            )
            return []

        if not result.items:
            logger.debug("RAG returned 0 docs for city=%s", city)
            return []

        attractions = [
            self._rag_doc_to_attraction(doc, city, idx)
            for idx, doc in enumerate(result.items)
        ]
        logger.info(
            "RAG returned %d attractions for city=%s (provider=%s)",
            len(attractions),
            city,
            result.provider,
        )
        return attractions

    def _rag_doc_to_attraction(
        self,
        doc: RAGDocument,
        city: str,
        idx: int,
    ) -> Attraction:
        """Convert a RAG document into an ``Attraction`` model.

        The ``source_url`` is preserved from the Wikivoyage page link
        for full citation traceability.
        """
        # Use city center coords as approximation (RAG docs lack precise coords)
        lon, lat = CITY_CENTER.get(city, (116.397128, 39.916527))

        # Extract a name from the page title or content
        name = self._extract_attraction_name(doc, city, idx)

        # Fetch photo (best-effort)
        photo_url = self._get_photo_safe(f"{name} {city}")

        return Attraction(
            name=name,
            address=f"{city}（来源：Wikivoyage）",
            location=Location(
                longitude=lon + idx * 0.005,
                latitude=lat + idx * 0.005,
            ),
            visit_duration=_DEFAULT_VISIT_DURATION,
            description=doc.content[:200] if len(doc.content) > 200 else doc.content,
            category="Wikivoyage推荐",
            rating=round(min(5.0, 4.0 + doc.relevance_score), 1),
            image_url=photo_url,
            source_url=doc.source_url,
            ticket_price=0,
        )

    @staticmethod
    def _extract_attraction_name(doc: RAGDocument, city: str, idx: int) -> str:
        """Extract a meaningful attraction name from a RAG document.

        Tries to use the page_title; falls back to a generic name.
        """
        title = doc.page_title.strip()
        if title and title.lower() not in ("", city.lower()):
            # Use sub-page name if present (e.g. "Beijing/Dongcheng" → "Dongcheng")
            if "/" in title:
                return title.split("/")[-1].strip()
            return title
        return f"{city}Wikivoyage推荐景点{idx + 1}"

    # ------------------------------------------------------------------
    # Map search (original C2 logic, extracted)
    # ------------------------------------------------------------------

    def _search_map(self, city: str, keyword: str) -> list[Attraction]:
        """Search map POIs and convert to Attraction models."""
        try:
            pois = self._reg.map.search_poi(
                keywords=keyword,
                city=city,
                citylimit=True,
            )
        except Exception:
            logger.warning("POI search failed, returning empty", exc_info=True)
            return []

        if not pois:
            return []

        return self._build_from_pois(pois[:_MAX_POIS], city, keyword)

    # ------------------------------------------------------------------
    # Merge & deduplicate
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_attractions(
        rag_attractions: list[Attraction],
        map_attractions: list[Attraction],
    ) -> list[Attraction]:
        """Merge RAG-sourced and map-sourced attractions, deduplicating by name.

        RAG attractions appear first (higher trust for curated knowledge),
        followed by map attractions not already present.
        """
        seen_names: set[str] = set()
        merged: list[Attraction] = []

        for a in rag_attractions:
            key = a.name.lower().strip()
            if key not in seen_names:
                seen_names.add(key)
                merged.append(a)

        for a in map_attractions:
            key = a.name.lower().strip()
            if key not in seen_names:
                seen_names.add(key)
                merged.append(a)

        return merged

    # ------------------------------------------------------------------
    # POI → Attraction conversion
    # ------------------------------------------------------------------

    def _build_from_pois(
        self,
        pois: list[Any],
        city: str,
        keyword: str,
    ) -> list[Attraction]:
        """Convert POI results into ``Attraction`` models with photos.

        Each attraction includes:
        - ``source_url``: deep link to the map provider search result.
        - ``image_url``: first matching photo from the photo provider.
        """
        results: list[Attraction] = []
        map_name = self._reg.map.provider_name

        for idx, poi in enumerate(pois):
            # Fetch photo (best-effort)
            photo_url = self._get_photo_safe(f"{poi.name} {city}")

            # Build detail / source URLs
            source_url = self._make_source_url(map_name, poi.name, city)

            results.append(
                Attraction(
                    name=poi.name,
                    address=poi.address,
                    location=poi.location,
                    visit_duration=_DEFAULT_VISIT_DURATION,
                    description=f"{poi.name}是{city}的推荐{keyword}景点。",
                    category=keyword,
                    rating=round(4.5 - idx * 0.1, 1),
                    image_url=photo_url,
                    poi_id=getattr(poi, "id", ""),
                    source_url=source_url,
                    ticket_price=60 + idx * 10,
                )
            )

        return results

    # ------------------------------------------------------------------
    # Fallback attractions (no network)
    # ------------------------------------------------------------------

    def _build_fallback(self, city: str, keyword: str) -> list[Attraction]:
        """Generate deterministic fallback attractions when search fails."""
        lon, lat = CITY_CENTER.get(city, (116.397128, 39.916527))
        return [
            Attraction(
                name=f"{city}{keyword}推荐点{i + 1}",
                address=f"{city}市区",
                location=Location(longitude=lon + i * 0.01, latitude=lat + i * 0.01),
                visit_duration=_DEFAULT_VISIT_DURATION,
                description=f"适合{keyword}主题的推荐景点。",
                category=keyword,
                rating=round(4.6 - i * 0.1, 1),
                source_url=f"https://ditu.amap.com/search?query={city}{keyword}",
                ticket_price=50 + i * 20,
            )
            for i in range(3)
        ]

    # ------------------------------------------------------------------
    # Photo helper (best-effort)
    # ------------------------------------------------------------------

    def _get_photo_safe(self, query: str) -> str | None:
        """Fetch a photo URL via the photo provider, return *None* on failure."""
        try:
            return self._reg.photo.get_photo_url(query)
        except Exception:
            logger.debug("Photo fetch failed for query=%s", query, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # URL helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_source_url(provider: str, name: str, city: str) -> str:
        """Build a source URL appropriate for the active map provider."""
        if provider == "google":
            return f"https://www.google.com/maps/search/{name}+{city}"
        # Default: Amap
        return f"https://ditu.amap.com/search?query={name}"

    # ------------------------------------------------------------------
    # WorkerFn protocol adapter
    # ------------------------------------------------------------------

    def as_worker(self) -> Callable[..., dict]:
        """Return a ``WorkerFn``-compatible callable for PlannerAgent.

        The returned function takes ``PlannerState`` and returns a dict
        with key ``attractions`` containing serialised ``Attraction`` list,
        and ``rag_sources`` listing Wikivoyage source URLs (C8).
        """

        def _worker(state: dict) -> dict:
            request = TripRequest(**state["request"])
            attractions = self.run(request)
            # Collect RAG source URLs for PlannerAgent source_links aggregation
            rag_sources = [
                a.source_url
                for a in attractions
                if a.source_url and "wikivoyage.org" in a.source_url
            ]
            return {
                "attractions": [
                    a.model_dump() for a in attractions
                ],
                "rag_sources": rag_sources,
            }

        return _worker
