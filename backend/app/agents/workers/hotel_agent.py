"""HotelAgent — LangGraph worker that searches hotels via pluggable map provider.

Rewritten for C4 to use ProviderRegistry instead of hard-coded defaults.
Retains backward-compatible ``run()`` signature and adds ``as_worker()``
for the PlannerAgent WorkerFn protocol.

Source prompt: trip_planner_agent.py HOTEL_AGENT_PROMPT (migrated in A2).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from app.models.schemas import Hotel, Location, TripRequest
from app.prompts.trip_prompts import HOTEL_AGENT_PROMPT

if TYPE_CHECKING:
    from app.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Budget / accommodation tier mapping
# ---------------------------------------------------------------------------

_ACCOMMODATION_TIERS: dict[str, dict[str, Any]] = {
    "经济型": {"keyword": "快捷酒店", "price_range": "100-200元/晚", "estimated_cost": 150},
    "经济型酒店": {"keyword": "快捷酒店", "price_range": "100-200元/晚", "estimated_cost": 150},
    "舒适型": {"keyword": "酒店", "price_range": "300-500元/晚", "estimated_cost": 400},
    "舒适型酒店": {"keyword": "酒店", "price_range": "300-500元/晚", "estimated_cost": 400},
    "豪华型": {"keyword": "五星级酒店", "price_range": "800-1500元/晚", "estimated_cost": 1100},
    "豪华型酒店": {"keyword": "五星级酒店", "price_range": "800-1500元/晚", "estimated_cost": 1100},
}

_DEFAULT_TIER = {"keyword": "酒店", "price_range": "300-500元/晚", "estimated_cost": 420}

# Fallback city-center coordinates (shared with AttractionAgent)
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


class HotelAgent:
    """Search and recommend a hotel candidate for the trip.

    Uses ``ProviderRegistry.map.search_poi()`` with hotel-related keywords
    to find real candidates, making the underlying API fully pluggable via
    ``settings.yaml``.

    Args:
        registry: Optional pre-built ``ProviderRegistry``. When *None*,
            the module-level singleton is resolved lazily on first call.
    """

    prompt: str = HOTEL_AGENT_PROMPT

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

    def run(self, request: TripRequest) -> Hotel:
        """Return a hotel recommendation using map provider POI search.

        Args:
            request: A ``TripRequest`` with at least ``city`` and optionally
                ``accommodation`` populated.

        Returns:
            A single ``Hotel`` model. Falls back to deterministic defaults
            when POI search returns no results.
        """
        level = request.accommodation or "舒适型酒店"
        tier = _ACCOMMODATION_TIERS.get(level, _DEFAULT_TIER)
        keyword: str = tier["keyword"]

        logger.info(
            "HotelAgent.run: city=%s level=%s keyword=%s",
            request.city, level, keyword,
        )

        try:
            pois = self._reg.map.search_poi(
                keywords=keyword,
                city=request.city,
                citylimit=True,
            )
        except Exception:
            logger.warning("Hotel POI search failed, falling back to defaults", exc_info=True)
            pois = []

        if pois:
            return self._build_from_poi(pois[0], request.city, level, tier)

        logger.info("No hotel POIs found, using fallback for %s", request.city)
        return self._build_fallback(request.city, level, tier)

    # ------------------------------------------------------------------
    # POI → Hotel conversion
    # ------------------------------------------------------------------

    def _build_from_poi(
        self,
        poi: Any,
        city: str,
        level: str,
        tier: dict[str, Any],
    ) -> Hotel:
        """Convert a POI result into a ``Hotel`` model.

        Generates ``source_url`` appropriate for the active map provider.
        """
        map_name = self._reg.map.provider_name
        source_url = self._make_source_url(map_name, poi.name, city)

        return Hotel(
            name=poi.name,
            address=poi.address,
            location=poi.location,
            price_range=tier["price_range"],
            rating="4.6",
            distance="距离核心景点约2公里",
            type=level,
            source_url=source_url,
            estimated_cost=tier["estimated_cost"],
        )

    # ------------------------------------------------------------------
    # Fallback hotel (no network)
    # ------------------------------------------------------------------

    def _build_fallback(
        self,
        city: str,
        level: str,
        tier: dict[str, Any],
    ) -> Hotel:
        """Generate a deterministic fallback hotel when search fails."""
        lon, lat = CITY_CENTER.get(city, (116.397128, 39.916527))
        return Hotel(
            name=f"{city}{level}推荐酒店",
            address=f"{city}市中心商圈",
            location=Location(longitude=lon, latitude=lat),
            price_range=tier["price_range"],
            rating="4.6",
            distance="距离核心景点约2公里",
            type=level,
            source_url=f"https://ditu.amap.com/search?query={city}酒店",
            estimated_cost=tier["estimated_cost"],
        )

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
        with key ``hotel`` containing a serialised ``Hotel`` dict.
        """

        def _worker(state: dict) -> dict:
            request = TripRequest(**state["request"])
            hotel = self.run(request)
            return {
                "hotel": hotel.model_dump(),
            }

        return _worker
