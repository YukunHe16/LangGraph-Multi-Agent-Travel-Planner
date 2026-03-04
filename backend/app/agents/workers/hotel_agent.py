"""Hotel worker migrated from hello-agents and rewritten for LangGraph runtime."""

from __future__ import annotations

from app.models.schemas import Hotel, Location, TripRequest
from app.prompts.trip_prompts import HOTEL_AGENT_PROMPT


class HotelAgent:
    """Recommend one hotel candidate for the trip."""

    prompt: str = HOTEL_AGENT_PROMPT

    def run(self, request: TripRequest) -> Hotel:
        """Return a deterministic hotel recommendation."""
        level = request.accommodation or "舒适型酒店"
        return Hotel(
            name=f"{request.city}{level}推荐酒店",
            address=f"{request.city}市中心商圈",
            location=Location(longitude=116.4, latitude=39.9),
            price_range="300-500元/晚",
            rating="4.6",
            distance="距离核心景点约2公里",
            type=level,
            source_url=f"https://ditu.amap.com/search?query={request.city}酒店",
            estimated_cost=420,
        )
