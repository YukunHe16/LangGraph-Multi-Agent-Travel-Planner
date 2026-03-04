"""Integration tests for C1: PlannerAgent routing to all 6 workers.

Validates:
  - Default mode routes to attraction/weather/hotel/flight/visa
  - Attraction-enhanced mode routes to same 5 workers (with mode flag)
  - Export mode routes only to export worker
  - All registered workers are actually invoked
  - Backward-compatible plan_trip() still works
"""

from __future__ import annotations

import pytest

from app.agents.planner.planner_agent import (
    ALL_PLANNING_WORKERS,
    WORKER_NAMES,
    PlannerAgent,
    PlannerMode,
    PlannerState,
    WorkerFn,
)
from app.models.schemas import TripRequest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_REQUEST = TripRequest(
    city="北京",
    start_date="2026-06-01",
    end_date="2026-06-03",
    travel_days=3,
    transportation="公共交通",
    accommodation="经济型酒店",
    preferences=["历史文化"],
)


def _make_stub_worker(name: str) -> WorkerFn:
    """Create a stub worker that records invocations and returns result."""
    calls: list[dict] = []

    def _worker(state: PlannerState) -> dict:
        calls.append({"worker": name, "mode": state.get("mode")})
        return {f"{name}_data": f"stub_{name}_result"}

    _worker.calls = calls  # type: ignore[attr-defined]
    return _worker


def _build_all_stub_workers() -> dict[str, WorkerFn]:
    """Build a dict of all 6 stub workers."""
    return {name: _make_stub_worker(name) for name in WORKER_NAMES}


# ---------------------------------------------------------------------------
# Test: Default mode routes to all 5 planning workers
# ---------------------------------------------------------------------------

class TestDefaultModeRouting:
    """Default mode should invoke attraction/weather/hotel/flight/visa."""

    def test_default_mode_routes_all_planning_workers(self) -> None:
        workers = _build_all_stub_workers()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(_SAMPLE_REQUEST, mode=PlannerMode.DEFAULT)

        assert set(result["workers_ran"]) == set(ALL_PLANNING_WORKERS)

    def test_default_mode_does_not_route_export(self) -> None:
        workers = _build_all_stub_workers()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(_SAMPLE_REQUEST, mode=PlannerMode.DEFAULT)

        assert "export" not in result["workers_ran"]
        assert workers["export"].calls == []  # type: ignore[attr-defined]

    def test_default_mode_records_worker_results(self) -> None:
        workers = _build_all_stub_workers()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(_SAMPLE_REQUEST, mode=PlannerMode.DEFAULT)

        for name in ALL_PLANNING_WORKERS:
            assert result.get(f"{name}_result") is not None

    def test_default_mode_workers_to_run_matches_ran(self) -> None:
        workers = _build_all_stub_workers()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(_SAMPLE_REQUEST, mode=PlannerMode.DEFAULT)

        assert set(result["workers_to_run"]) == set(result["workers_ran"])


# ---------------------------------------------------------------------------
# Test: Attraction-enhanced mode
# ---------------------------------------------------------------------------

class TestAttractionEnhancedRouting:
    """Attraction-enhanced mode should invoke same workers with mode flag."""

    def test_enhanced_mode_routes_all_planning_workers(self) -> None:
        workers = _build_all_stub_workers()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(_SAMPLE_REQUEST, mode=PlannerMode.ATTRACTION_ENHANCED)

        assert set(result["workers_ran"]) == set(ALL_PLANNING_WORKERS)

    def test_enhanced_mode_passes_mode_to_workers(self) -> None:
        workers = _build_all_stub_workers()
        agent = PlannerAgent(workers=workers)

        agent.plan(_SAMPLE_REQUEST, mode=PlannerMode.ATTRACTION_ENHANCED)

        for name in ALL_PLANNING_WORKERS:
            calls = workers[name].calls  # type: ignore[attr-defined]
            assert len(calls) == 1
            assert calls[0]["mode"] == PlannerMode.ATTRACTION_ENHANCED.value


# ---------------------------------------------------------------------------
# Test: Export mode
# ---------------------------------------------------------------------------

class TestExportModeRouting:
    """Export mode should only invoke the export worker."""

    def test_export_mode_routes_only_export(self) -> None:
        workers = _build_all_stub_workers()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(_SAMPLE_REQUEST, mode=PlannerMode.EXPORT)

        assert result["workers_ran"] == ["export"]

    def test_export_mode_skips_planning_workers(self) -> None:
        workers = _build_all_stub_workers()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(_SAMPLE_REQUEST, mode=PlannerMode.EXPORT)

        for name in ALL_PLANNING_WORKERS:
            assert workers[name].calls == []  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Test: Worker coverage — all 6 workers can be routed
# ---------------------------------------------------------------------------

class TestAllWorkersRoutable:
    """PlannerAgent can route to all 6 worker types."""

    def test_all_six_workers_are_accepted(self) -> None:
        workers = _build_all_stub_workers()
        agent = PlannerAgent(workers=workers)

        assert set(agent.workers.keys()) == set(WORKER_NAMES)

    def test_default_plus_export_covers_all_six(self) -> None:
        workers = _build_all_stub_workers()
        agent = PlannerAgent(workers=workers)

        r1 = agent.plan(_SAMPLE_REQUEST, mode=PlannerMode.DEFAULT)
        r2 = agent.plan(_SAMPLE_REQUEST, mode=PlannerMode.EXPORT)

        all_ran = set(r1["workers_ran"]) | set(r2["workers_ran"])
        assert all_ran == set(WORKER_NAMES)


# ---------------------------------------------------------------------------
# Test: Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Verify plan_trip() legacy interface still works."""

    def test_plan_trip_returns_trip_plan(self) -> None:
        """plan_trip with stub workers should return a valid TripPlan."""
        from app.models.schemas import Attraction, Hotel, Location, WeatherInfo

        def attraction_worker(state: PlannerState) -> dict:
            return {
                "attractions": [
                    Attraction(
                        name="故宫", address="北京市东城区",
                        location=Location(longitude=116.397, latitude=39.917),
                        visit_duration=120, description="皇家宫殿",
                        ticket_price=60,
                    ).model_dump(),
                    Attraction(
                        name="天坛", address="北京市东城区",
                        location=Location(longitude=116.411, latitude=39.882),
                        visit_duration=90, description="祭天场所",
                        ticket_price=35,
                    ).model_dump(),
                ]
            }

        def weather_worker(state: PlannerState) -> dict:
            return {
                "weather_info": [
                    WeatherInfo(date="2026-06-01", day_weather="晴", night_weather="多云",
                                day_temp=32, night_temp=20).model_dump(),
                    WeatherInfo(date="2026-06-02", day_weather="多云", night_weather="阴",
                                day_temp=30, night_temp=19).model_dump(),
                    WeatherInfo(date="2026-06-03", day_weather="小雨", night_weather="阴",
                                day_temp=28, night_temp=18).model_dump(),
                ]
            }

        def hotel_worker(state: PlannerState) -> dict:
            return {
                "hotel": Hotel(
                    name="如家酒店", address="北京市中心",
                    estimated_cost=200,
                ).model_dump()
            }

        workers = {
            "attraction": attraction_worker,
            "weather": weather_worker,
            "hotel": hotel_worker,
        }
        agent = PlannerAgent(workers=workers)
        plan = agent.plan_trip(_SAMPLE_REQUEST)

        assert plan.city == "北京"
        assert len(plan.days) == 3
        assert len(plan.weather_info) == 3
        assert plan.budget is not None
        assert plan.budget.total > 0

    def test_plan_trip_fallback_on_empty_workers(self) -> None:
        """plan_trip with no workers should return plan with empty attractions."""
        agent = PlannerAgent(workers={})
        plan = agent.plan_trip(_SAMPLE_REQUEST)

        assert plan.city == "北京"
        assert len(plan.days) == 3
        # No attraction worker → each day has empty attractions
        for day in plan.days:
            assert day.attractions == []


# ---------------------------------------------------------------------------
# Test: Missing workers are silently skipped
# ---------------------------------------------------------------------------

class TestPartialWorkerRegistration:
    """Planner gracefully handles partial worker registration."""

    def test_missing_worker_skipped_not_errored(self) -> None:
        """Only attraction registered; other slots skipped without error."""
        workers = {"attraction": _make_stub_worker("attraction")}
        agent = PlannerAgent(workers=workers)

        result = agent.plan(_SAMPLE_REQUEST, mode=PlannerMode.DEFAULT)

        assert result["workers_ran"] == ["attraction"]
        assert "weather" not in result["workers_ran"]

    def test_workers_to_run_includes_unregistered(self) -> None:
        """workers_to_run reflects intent; workers_ran reflects reality."""
        workers = {"attraction": _make_stub_worker("attraction")}
        agent = PlannerAgent(workers=workers)

        result = agent.plan(_SAMPLE_REQUEST, mode=PlannerMode.DEFAULT)

        assert set(result["workers_to_run"]) == set(ALL_PLANNING_WORKERS)
        assert result["workers_ran"] == ["attraction"]
