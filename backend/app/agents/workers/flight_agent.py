"""FlightAgent — LangGraph worker that searches flights via pluggable flight provider.

Implemented for C6 to use ProviderRegistry.flight.search_flights().
Follows the same pattern as AttractionAgent/WeatherAgent/HotelAgent:
lazy ProviderRegistry resolution, ``run()`` for direct use, ``as_worker()``
for PlannerAgent WorkerFn protocol.

Acceptance: Structured flight plan with sorted offers, ranking reasons,
booking_url (falls back to source_url with annotation when unavailable).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from app.models.schemas import FlightOffer, FlightSearchInput, TripRequest
from app.prompts.trip_prompts import FLIGHT_AGENT_PROMPT

if TYPE_CHECKING:
    from app.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# City → IATA mapping (major Chinese + international cities)
# ---------------------------------------------------------------------------

CITY_IATA: dict[str, str] = {
    # Domestic
    "北京": "PEK",
    "上海": "PVG",
    "广州": "CAN",
    "深圳": "SZX",
    "成都": "CTU",
    "杭州": "HGH",
    "西安": "XIY",
    "南京": "NKG",
    "重庆": "CKG",
    "武汉": "WUH",
    "长沙": "CSX",
    "昆明": "KMG",
    "厦门": "XMN",
    "青岛": "TAO",
    "大连": "DLC",
    "三亚": "SYX",
    "海口": "HAK",
    "哈尔滨": "HRB",
    "贵阳": "KWE",
    "桂林": "KWL",
    "拉萨": "LXA",
    "乌鲁木齐": "URC",
    "天津": "TSN",
    "郑州": "CGO",
    "济南": "TNA",
    "福州": "FOC",
    "合肥": "HFE",
    "太原": "TYN",
    "沈阳": "SHE",
    "长春": "CGQ",
    "南昌": "KHN",
    "南宁": "NNG",
    "兰州": "LHW",
    "银川": "INC",
    "西宁": "XNN",
    "呼和浩特": "HET",
    "石家庄": "SJW",
    # International
    "东京": "NRT",
    "大阪": "KIX",
    "首尔": "ICN",
    "曼谷": "BKK",
    "新加坡": "SIN",
    "吉隆坡": "KUL",
    "香港": "HKG",
    "澳门": "MFM",
    "台北": "TPE",
    "巴黎": "CDG",
    "伦敦": "LHR",
    "纽约": "JFK",
    "洛杉矶": "LAX",
    "悉尼": "SYD",
    "墨尔本": "MEL",
    "迪拜": "DXB",
}

# Default departure city if not inferrable from request
_DEFAULT_ORIGIN_CITY = "北京"


class FlightAgent:
    """Search and rank flight offers for a trip.

    Uses ``ProviderRegistry.flight.search_flights()`` to fetch real flight
    offers, making the underlying API fully pluggable via ``settings.yaml``.

    Args:
        registry: Optional pre-built ``ProviderRegistry``. When *None*,
            the module-level singleton is resolved lazily on first call.
        origin_city: Default departure city name. When the trip request
            does not imply an origin, this city is used.
    """

    prompt: str = FLIGHT_AGENT_PROMPT

    def __init__(
        self,
        registry: "ProviderRegistry | None" = None,
        origin_city: str = _DEFAULT_ORIGIN_CITY,
    ) -> None:
        self._registry = registry
        self._origin_city = origin_city

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

    def run(
        self,
        request: TripRequest,
        *,
        origin_city: str | None = None,
        max_results: int = 5,
    ) -> dict:
        """Search flights and return a structured flight plan.

        Args:
            request: A ``TripRequest`` with ``city``, ``start_date``,
                ``end_date`` populated.
            origin_city: Override departure city for this call.
            max_results: Maximum number of flight offers to return.

        Returns:
            A dict conforming to the planner's ``flight_plan`` schema::

                {
                    "offers": [...],        # sorted FlightOffer dicts
                    "ranking_reason": "...", # explanation of sort order
                    "source_url": "...",     # provider source URL
                    "origin": "PEK",
                    "destination": "NRT",
                }
        """
        dep_city = origin_city or self._origin_city
        dest_city = request.city

        origin_iata = self._city_to_iata(dep_city)
        dest_iata = self._city_to_iata(dest_city)

        logger.info(
            "FlightAgent.run: %s(%s) → %s(%s)  %s ~ %s",
            dep_city, origin_iata, dest_city, dest_iata,
            request.start_date, request.end_date,
        )

        # Compute return date (end_date if round-trip makes sense)
        return_date: str | None = None
        if request.end_date and request.end_date != request.start_date:
            return_date = request.end_date

        try:
            offers = self._reg.flight.search_flights(
                origin=origin_iata,
                destination=dest_iata,
                departure_date=request.start_date,
                return_date=return_date,
                adults=1,
                max_results=max_results,
            )
        except Exception:
            logger.warning("FlightAgent search failed, returning empty plan", exc_info=True)
            offers = []

        # Sort by price ascending
        sorted_offers = sorted(offers, key=lambda o: o.price)

        # Annotate booking_url fallback
        annotated = [self._annotate_offer(o) for o in sorted_offers]

        ranking_reason = self._build_ranking_reason(annotated)
        source_url = self._pick_source_url(annotated)

        return {
            "offers": [o.model_dump() for o in sorted_offers],
            "annotated_offers": annotated,
            "ranking_reason": ranking_reason,
            "source_url": source_url,
            "origin": origin_iata,
            "destination": dest_iata,
            "origin_city": dep_city,
            "destination_city": dest_city,
        }

    # ------------------------------------------------------------------
    # Offer annotation
    # ------------------------------------------------------------------

    @staticmethod
    def _annotate_offer(offer: FlightOffer) -> dict:
        """Annotate an offer with booking link and fallback status.

        When ``booking_url`` is ``None``, falls back to ``source_url``
        and sets ``booking_url_is_fallback = True``.
        """
        data = offer.model_dump()
        if offer.booking_url:
            data["display_url"] = offer.booking_url
            data["booking_url_is_fallback"] = False
        else:
            data["display_url"] = offer.source_url or "https://www.google.com/flights"
            data["booking_url_is_fallback"] = True
        return data

    # ------------------------------------------------------------------
    # Ranking & source helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_ranking_reason(annotated: list[dict]) -> str:
        """Build a human-readable ranking explanation."""
        if not annotated:
            return "暂无航班数据"

        count = len(annotated)
        cheapest = annotated[0]
        price = cheapest.get("price", 0)
        currency = cheapest.get("currency", "CNY")
        carrier = cheapest.get("carrier_name", "未知航空")

        return (
            f"共找到 {count} 个航班方案，按价格从低到高排序。"
            f"最优选择：{carrier}，价格 {price} {currency}。"
        )

    @staticmethod
    def _pick_source_url(annotated: list[dict]) -> str:
        """Pick a representative source URL from the offers."""
        for item in annotated:
            url = item.get("source_url") or item.get("display_url")
            if url:
                return url
        return "https://www.google.com/flights"

    # ------------------------------------------------------------------
    # City → IATA
    # ------------------------------------------------------------------

    @staticmethod
    def _city_to_iata(city: str) -> str:
        """Convert a Chinese city name to its primary IATA airport code.

        Falls back to ``"PEK"`` for unknown cities.
        """
        return CITY_IATA.get(city, "PEK")

    # ------------------------------------------------------------------
    # WorkerFn protocol adapter
    # ------------------------------------------------------------------

    def as_worker(self) -> Callable[..., dict]:
        """Return a ``WorkerFn``-compatible callable for PlannerAgent.

        The returned function takes ``PlannerState`` and returns a dict
        with key ``flight_plan`` containing the structured flight data.
        """

        def _worker(state: dict) -> dict:
            request = TripRequest(**state["request"])
            plan = self.run(request)
            return {
                "flight_plan": plan,
            }

        return _worker
