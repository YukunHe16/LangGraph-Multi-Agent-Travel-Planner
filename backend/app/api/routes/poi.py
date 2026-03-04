"""POI routes migrated from hello-agents backend."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models import ErrorResponse
from app.services import get_amap_service, get_unsplash_service

router = APIRouter(prefix="/poi", tags=["POI"])


@router.get(
    "/detail/{poi_id}",
    responses={500: {"model": ErrorResponse}},
    summary="获取POI详情",
)
def get_poi_detail(poi_id: str) -> dict[str, object]:
    """Get detail payload by POI ID."""
    try:
        detail = get_amap_service().get_poi_detail(poi_id)
        return {"success": True, "message": "获取POI详情成功", "data": detail}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取POI详情失败: {exc}") from exc


@router.get(
    "/search",
    responses={500: {"model": ErrorResponse}},
    summary="搜索POI",
)
def search_poi(keywords: str, city: str = "北京") -> dict[str, object]:
    """Search POIs via amap service."""
    try:
        result = get_amap_service().search_poi(keywords, city)
        return {"success": True, "message": "搜索成功", "data": [item.model_dump() for item in result]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"搜索POI失败: {exc}") from exc


@router.get(
    "/photo",
    responses={500: {"model": ErrorResponse}},
    summary="获取景点图片",
)
def get_attraction_photo(name: str) -> dict[str, object]:
    """Search attraction photo from Unsplash."""
    try:
        photo_url = get_unsplash_service().get_photo_url(f"{name} China landmark")
        if not photo_url:
            photo_url = get_unsplash_service().get_photo_url(name)
        return {
            "success": True,
            "message": "获取图片成功",
            "data": {"name": name, "photo_url": photo_url},
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取景点图片失败: {exc}") from exc
