"""AttractionAgent — LangGraph worker that searches attractions via pluggable providers.

Rewritten for C2 to use ProviderRegistry instead of hard-coded services.
Retains backward-compatible ``run()`` signature and adds ``as_worker()``
for the PlannerAgent WorkerFn protocol.

Source prompt: trip_planner_agent.py ATTRACTION_AGENT_PROMPT (migrated in A2).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from app.models.schemas import Attraction, Location, TripRequest
from app.prompts.trip_prompts import ATTRACTION_AGENT_PROMPT

if TYPE_CHECKING:
    from app.providers.registry import ProviderRegistry

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

# Default visit duration in minutes
_DEFAULT_VISIT_DURATION = 120


class AttractionAgent:
    """Search and rank attraction candidates for a given city and preferences.

    Uses ``ProviderRegistry`` to access map (POI search) and photo providers,
    making the underlying API fully pluggable via ``settings.yaml``.

    Args:
        registry: Optional pre-built ``ProviderRegistry``. When *None*,
            the module-level singleton is resolved lazily on first call.
    """

    prompt: str = ATTRACTION_AGENT_PROMPT

    def __init__(self, registry: "ProviderRegistry | None" = None) -> None:
        self._registry = registry

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

    # ------------------------------------------------------------------
    # Core logic
    # ------------------------------------------------------------------

    def run(self, request: TripRequest) -> list[Attraction]:
        """Return attraction candidates using map + photo providers.

        Args:
            request: A ``TripRequest`` with at least ``city`` populated.

        Returns:
            A list of ``Attraction`` models; never empty (falls back to
            deterministic defaults when no POIs are found).
        """
        keyword = request.preferences[0] if request.preferences else "景点"
        logger.info("AttractionAgent.run: city=%s keyword=%s", request.city, keyword)

        try:
            pois = self._reg.map.search_poi(
                keywords=keyword,
                city=request.city,
                citylimit=True,
            )
        except Exception:
            logger.warning("POI search failed, falling back to defaults", exc_info=True)
            pois = []

        if pois:
            return self._build_from_pois(pois[:_MAX_POIS], request.city, keyword)

        logger.info("No POIs found, using fallback attractions for %s", request.city)
        return self._build_fallback(request.city, keyword)

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
        with key ``attractions`` containing serialised ``Attraction`` list.
        """

        def _worker(state: dict) -> dict:
            request = TripRequest(**state["request"])
            attractions = self.run(request)
            return {
                "attractions": [
                    a.model_dump() for a in attractions
                ],
            }

        return _worker
