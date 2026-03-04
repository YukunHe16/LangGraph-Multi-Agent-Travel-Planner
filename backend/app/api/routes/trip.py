"""Trip planning routes migrated from hello-agents backend."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.agents.planner import get_planner_agent
from app.models import ErrorResponse, TripPlanResponse, TripRequest

router = APIRouter(prefix="/trip", tags=["旅行规划"])


@router.post(
    "/plan",
    response_model=TripPlanResponse,
    responses={500: {"model": ErrorResponse}},
    summary="生成旅行计划",
)
def plan_trip(request: TripRequest) -> TripPlanResponse:
    """Generate trip plan through migrated LangGraph planner."""
    try:
        planner = get_planner_agent()
        trip_plan = planner.plan_trip(request)
        return TripPlanResponse(success=True, message="旅行计划生成成功", data=trip_plan)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"生成旅行计划失败: {exc}") from exc


@router.get("/health", summary="旅行规划服务健康检查")
def health_check() -> dict[str, str]:
    """Health endpoint for planner route group."""
    return {"status": "healthy", "service": "trip-planner"}
