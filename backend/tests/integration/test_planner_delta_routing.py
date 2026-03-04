"""Integration tests for C1: PlannerAgent delta (incremental) routing.

Validates:
  - Delta mode only invokes workers affected by user modification
  - Keyword-based affected-worker detection works for all 6 workers
  - Unknown delta falls back to all planning workers
  - Multiple keywords can trigger multiple workers
  - Previous plan is passed through state
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
    _compute_affected_workers,
)
from app.models.schemas import TripRequest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_REQUEST = TripRequest(
    city="东京",
    start_date="2026-07-01",
    end_date="2026-07-05",
    travel_days=5,
    transportation="地铁",
    accommodation="商务酒店",
    preferences=["美食", "购物"],
)


def _make_stub_worker(name: str) -> WorkerFn:
    """Stub worker that records calls."""
    calls: list[dict] = []

    def _worker(state: PlannerState) -> dict:
        calls.append({"worker": name, "delta": state.get("user_delta")})
        return {f"{name}_data": f"stub_{name}"}

    _worker.calls = calls  # type: ignore[attr-defined]
    return _worker


def _build_all_stubs() -> dict[str, WorkerFn]:
    return {name: _make_stub_worker(name) for name in WORKER_NAMES}


# ---------------------------------------------------------------------------
# Test: _compute_affected_workers unit logic
# ---------------------------------------------------------------------------

class TestComputeAffectedWorkers:
    """Unit tests for delta keyword matching logic."""

    def test_flight_keywords(self) -> None:
        assert "flight" in _compute_affected_workers("我想换航班")
        assert "flight" in _compute_affected_workers("change flight")
        assert "flight" in _compute_affected_workers("更改机票")

    def test_hotel_keywords(self) -> None:
        assert "hotel" in _compute_affected_workers("换一家酒店")
        assert "hotel" in _compute_affected_workers("change hotel")
        assert "hotel" in _compute_affected_workers("住宿改五星")

    def test_attraction_keywords(self) -> None:
        assert "attraction" in _compute_affected_workers("增加景点")
        assert "attraction" in _compute_affected_workers("add attraction")
        assert "attraction" in _compute_affected_workers("换个景区")

    def test_weather_keywords(self) -> None:
        assert "weather" in _compute_affected_workers("查看天气")
        assert "weather" in _compute_affected_workers("check weather")

    def test_visa_keywords(self) -> None:
        assert "visa" in _compute_affected_workers("需要签证吗")
        assert "visa" in _compute_affected_workers("check visa")

    def test_export_keywords(self) -> None:
        assert "export" in _compute_affected_workers("导出行程")
        assert "export" in _compute_affected_workers("export to calendar")
        assert "export" in _compute_affected_workers("生成PDF")

    def test_empty_delta_falls_back_to_all(self) -> None:
        assert set(_compute_affected_workers("")) == set(ALL_PLANNING_WORKERS)
        assert set(_compute_affected_workers(None)) == set(ALL_PLANNING_WORKERS)

    def test_unknown_delta_falls_back_to_all(self) -> None:
        assert set(_compute_affected_workers("随便看看")) == set(ALL_PLANNING_WORKERS)

    def test_multiple_keywords_trigger_multiple_workers(self) -> None:
        affected = _compute_affected_workers("换航班和酒店")
        assert "flight" in affected
        assert "hotel" in affected


# ---------------------------------------------------------------------------
# Test: Delta routing — flight only
# ---------------------------------------------------------------------------

class TestDeltaRoutingFlightOnly:
    """Delta mode with flight change should only invoke flight worker."""

    def test_delta_flight_only_invokes_flight(self) -> None:
        workers = _build_all_stubs()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(
            _SAMPLE_REQUEST,
            mode=PlannerMode.DELTA,
            user_delta="我想换一个航班",
        )

        assert result["workers_ran"] == ["flight"]

    def test_delta_flight_skips_other_workers(self) -> None:
        workers = _build_all_stubs()
        agent = PlannerAgent(workers=workers)

        agent.plan(
            _SAMPLE_REQUEST,
            mode=PlannerMode.DELTA,
            user_delta="更改机票时间",
        )

        for name in ["attraction", "weather", "hotel", "visa", "export"]:
            assert workers[name].calls == []  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Test: Delta routing — hotel only
# ---------------------------------------------------------------------------

class TestDeltaRoutingHotelOnly:
    """Delta mode with hotel change should only invoke hotel worker."""

    def test_delta_hotel_only(self) -> None:
        workers = _build_all_stubs()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(
            _SAMPLE_REQUEST,
            mode=PlannerMode.DELTA,
            user_delta="换一家五星级酒店",
        )

        assert result["workers_ran"] == ["hotel"]

    def test_delta_hotel_english_keyword(self) -> None:
        workers = _build_all_stubs()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(
            _SAMPLE_REQUEST,
            mode=PlannerMode.DELTA,
            user_delta="I want a different hotel",
        )

        assert result["workers_ran"] == ["hotel"]


# ---------------------------------------------------------------------------
# Test: Delta routing — multiple workers
# ---------------------------------------------------------------------------

class TestDeltaRoutingMultiple:
    """Delta with multiple keywords should invoke multiple workers."""

    def test_delta_flight_and_hotel(self) -> None:
        workers = _build_all_stubs()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(
            _SAMPLE_REQUEST,
            mode=PlannerMode.DELTA,
            user_delta="换航班，同时换酒店",
        )

        assert set(result["workers_ran"]) == {"flight", "hotel"}

    def test_delta_attraction_and_weather(self) -> None:
        workers = _build_all_stubs()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(
            _SAMPLE_REQUEST,
            mode=PlannerMode.DELTA,
            user_delta="加几个景点，顺便看下天气",
        )

        assert set(result["workers_ran"]) == {"attraction", "weather"}


# ---------------------------------------------------------------------------
# Test: Delta routing — unknown delta falls back
# ---------------------------------------------------------------------------

class TestDeltaFallback:
    """Unknown delta text should fall back to all planning workers."""

    def test_unknown_delta_runs_all_planning_workers(self) -> None:
        workers = _build_all_stubs()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(
            _SAMPLE_REQUEST,
            mode=PlannerMode.DELTA,
            user_delta="整体再优化一下",
        )

        assert set(result["workers_ran"]) == set(ALL_PLANNING_WORKERS)


# ---------------------------------------------------------------------------
# Test: Delta routing preserves previous_plan in state
# ---------------------------------------------------------------------------

class TestDeltaPreviousPlan:
    """Delta mode should pass previous_plan through state."""

    def test_previous_plan_accessible_in_worker(self) -> None:
        seen_plan: list[dict | None] = []

        def flight_worker(state: PlannerState) -> dict:
            seen_plan.append(state.get("previous_plan"))
            return {"flight_data": "updated"}

        workers = {"flight": flight_worker}
        agent = PlannerAgent(workers=workers)

        fake_prev = {"city": "东京", "days": []}
        agent.plan(
            _SAMPLE_REQUEST,
            mode=PlannerMode.DELTA,
            user_delta="换航班",
            previous_plan=fake_prev,
        )

        assert len(seen_plan) == 1
        assert seen_plan[0] == fake_prev


# ---------------------------------------------------------------------------
# Test: Delta routing — export keyword
# ---------------------------------------------------------------------------

class TestDeltaExport:
    """Delta mode with export keyword triggers export worker."""

    def test_delta_export_only(self) -> None:
        workers = _build_all_stubs()
        agent = PlannerAgent(workers=workers)

        result = agent.plan(
            _SAMPLE_REQUEST,
            mode=PlannerMode.DELTA,
            user_delta="导出到日历",
        )

        assert result["workers_ran"] == ["export"]
