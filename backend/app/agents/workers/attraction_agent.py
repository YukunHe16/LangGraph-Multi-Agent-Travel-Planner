"""Attraction worker migrated from hello-agents and rewritten for LangGraph runtime."""

from __future__ import annotations

from app.models.schemas import Attraction, Location, TripRequest
from app.prompts.trip_prompts import ATTRACTION_AGENT_PROMPT
from app.services import get_amap_service, get_unsplash_service


CITY_CENTER = {
    "北京": (116.397128, 39.916527),
    "上海": (121.4737, 31.2304),
    "广州": (113.2644, 23.1291),
    "深圳": (114.0579, 22.5431),
}


class AttractionAgent:
    """Generate attraction candidates based on city and user preferences."""

    prompt: str = ATTRACTION_AGENT_PROMPT

    def __init__(self) -> None:
        self.amap_service = get_amap_service()
        self.unsplash_service = get_unsplash_service()

    def run(self, request: TripRequest) -> list[Attraction]:
        """Return attractions using map search plus deterministic fallback."""
        keyword = request.preferences[0] if request.preferences else "景点"
        pois = self.amap_service.search_poi(keywords=keyword, city=request.city, citylimit=True)

        if pois:
            results: list[Attraction] = []
            for idx, poi in enumerate(pois[:6]):
                photo_url = self.unsplash_service.get_photo_url(f"{poi.name} {request.city}")
                results.append(
                    Attraction(
                        name=poi.name,
                        address=poi.address,
                        location=poi.location,
                        visit_duration=120,
                        description=f"{poi.name}是{request.city}的推荐{keyword}景点。",
                        category=keyword,
                        rating=4.5 - idx * 0.1,
                        image_url=photo_url,
                        source_url=f"https://ditu.amap.com/search?query={poi.name}",
                        ticket_price=60 + idx * 10,
                    )
                )
            return results

        lon, lat = CITY_CENTER.get(request.city, (116.397128, 39.916527))
        return [
            Attraction(
                name=f"{request.city}{keyword}推荐点{i + 1}",
                address=f"{request.city}市区",
                location=Location(longitude=lon + i * 0.01, latitude=lat + i * 0.01),
                visit_duration=120,
                description=f"适合{keyword}主题的推荐景点。",
                category=keyword,
                rating=4.6 - i * 0.1,
                source_url=f"https://ditu.amap.com/search?query={request.city}{keyword}",
                ticket_price=50 + i * 20,
            )
            for i in range(3)
        ]
