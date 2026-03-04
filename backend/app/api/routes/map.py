"""Map service routes migrated from hello-agents backend."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    ErrorResponse,
    POIInfo,
    POISearchResponse,
    RouteInfo,
    RouteRequest,
    RouteResponse,
    WeatherResponse,
)
from app.services import get_amap_service

router = APIRouter(prefix="/map", tags=["地图服务"])


@router.get(
    "/poi",
    response_model=POISearchResponse,
    responses={500: {"model": ErrorResponse}},
    summary="搜索POI",
)
def search_poi(
    keywords: str = Query(..., description="搜索关键词"),
    city: str = Query(..., description="城市"),
    citylimit: bool = Query(True, description="是否限制在城市范围内"),
) -> POISearchResponse:
    """Search POIs by keywords and city."""
    try:
        pois = get_amap_service().search_poi(keywords=keywords, city=city, citylimit=citylimit)
        return POISearchResponse(success=True, message="POI搜索成功", data=pois)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"POI搜索失败: {exc}") from exc


@router.get(
    "/weather",
    response_model=WeatherResponse,
    responses={500: {"model": ErrorResponse}},
    summary="查询天气",
)
def get_weather(city: str = Query(..., description="城市名称")) -> WeatherResponse:
    """Query weather by city."""
    try:
        weather = get_amap_service().get_weather(city)
        return WeatherResponse(success=True, message="天气查询成功", data=weather)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"天气查询失败: {exc}") from exc


@router.post(
    "/route",
    response_model=RouteResponse,
    responses={500: {"model": ErrorResponse}},
    summary="规划路线",
)
def plan_route(request: RouteRequest) -> RouteResponse:
    """Plan route between two points."""
    try:
        route_data = get_amap_service().plan_route(
            origin_address=request.origin_address,
            destination_address=request.destination_address,
            origin_city=request.origin_city,
            destination_city=request.destination_city,
            route_type=request.route_type,
        )
        return RouteResponse(
            success=True,
            message="路线规划成功",
            data=RouteInfo(**route_data),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"路线规划失败: {exc}") from exc


@router.get("/health", summary="地图服务健康检查")
def health_check() -> dict[str, str]:
    """Health endpoint for map service route group."""
    return {"status": "healthy", "service": "map-service"}
