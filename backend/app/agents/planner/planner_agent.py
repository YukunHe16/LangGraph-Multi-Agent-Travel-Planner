"""PlannerAgent: LangGraph orchestrator routing 6 workers with 3 modes.

Modes:
  - DEFAULT: parallel-call Attraction/Weather/Hotel/Flight/Visa then synthesize.
  - ATTRACTION_ENHANCED: same workers with RAG flag for AttractionAgent.
  - DELTA: only re-run workers affected by user modification.
  - EXPORT: only run ExportAgent.

Graph flow: START -> classify -> gather -> synthesize -> END
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.models.schemas import (
    Attraction,
    Budget,
    DayPlan,
    Hotel,
    Meal,
    TripPlan,
    TripRequest,
    WeatherInfo,
)
from app.prompts.trip_prompts import PLANNER_AGENT_PROMPT


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_PLANNING_WORKERS: list[str] = [
    "attraction", "weather", "hotel", "flight", "visa",
]
"""Workers invoked for default and attraction-enhanced planning modes."""

WORKER_NAMES: list[str] = [
    "attraction", "weather", "hotel", "flight", "visa", "export",
]
"""Canonical ordered list of all 6 worker names."""

DELTA_KEYWORDS: dict[str, list[str]] = {
    "flight": ["航班", "飞机", "flight", "机票"],
    "hotel": ["酒店", "住宿", "hotel", "accommodation"],
    "attraction": ["景点", "attraction", "游览", "参观", "景区"],
    "weather": ["天气", "weather", "气温"],
    "visa": ["签证", "visa"],
    "export": ["导出", "export", "日历", "calendar", "pdf"],
}
"""Keyword mapping used to compute affected workers in delta mode."""


class PlannerMode(str, Enum):
    """Intent modes supported by PlannerAgent routing."""

    DEFAULT = "default"
    ATTRACTION_ENHANCED = "attraction_enhanced"
    DELTA = "delta"
    EXPORT = "export"


# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------

class PlannerState(TypedDict, total=False):
    """State container for the PlannerAgent LangGraph orchestration."""

    # --- input ---
    request: dict  # TripRequest.model_dump()
    mode: str  # PlannerMode value
    previous_plan: Optional[dict]
    user_delta: Optional[str]

    # --- routing ---
    workers_to_run: list[str]
    workers_ran: list[str]

    # --- worker results ---
    attraction_result: Optional[dict]
    weather_result: Optional[dict]
    hotel_result: Optional[dict]
    flight_result: Optional[dict]
    visa_result: Optional[dict]
    export_result: Optional[dict]

    # --- legacy compat (used by _synthesize_legacy) ---
    attractions: Optional[list]
    weather_info: Optional[list]
    hotel: Optional[dict]

    # --- output ---
    trip_plan: Optional[dict]


# ---------------------------------------------------------------------------
# Worker callable type
# ---------------------------------------------------------------------------

WorkerFn = Callable[[PlannerState], dict]
"""Callable protocol for worker functions: takes state, returns partial dict."""


# ---------------------------------------------------------------------------
# PlannerAgent
# ---------------------------------------------------------------------------

class PlannerAgent:
    """LangGraph planner that classifies intent and routes to 6 workers.

    Args:
        workers: Dict mapping worker names to callables.
            Each callable receives ``PlannerState`` and returns a ``dict``
            with result keys matching ``{name}_result``.
        prompt: System prompt for the Planner LLM (used in C5/C9).
    """

    def __init__(
        self,
        workers: dict[str, WorkerFn] | None = None,
        *,
        prompt: str = PLANNER_AGENT_PROMPT,
        # Legacy kwargs for backward compat with A2 dataclass signature
        attraction_agent: Any = None,
        weather_agent: Any = None,
        hotel_agent: Any = None,
        flight_worker: WorkerFn | None = None,
        visa_worker: WorkerFn | None = None,
        export_worker: WorkerFn | None = None,
    ) -> None:
        self.prompt = prompt

        # Build workers dict ------------------------------------------------
        if workers is not None:
            self._workers: dict[str, WorkerFn] = dict(workers)
        else:
            self._workers = {}

        # Merge legacy kwargs — they are added only if the key is not already
        # present in the workers dict, allowing callers to mix both styles.
        if attraction_agent is not None and "attraction" not in self._workers:
            self._workers["attraction"] = _wrap_legacy_attraction(attraction_agent)
        if weather_agent is not None and "weather" not in self._workers:
            self._workers["weather"] = _wrap_legacy_weather(weather_agent)
        if hotel_agent is not None and "hotel" not in self._workers:
            self._workers["hotel"] = _wrap_legacy_hotel(hotel_agent)
        if flight_worker is not None and "flight" not in self._workers:
            self._workers["flight"] = flight_worker
        if visa_worker is not None and "visa" not in self._workers:
            self._workers["visa"] = visa_worker
        if export_worker is not None and "export" not in self._workers:
            self._workers["export"] = export_worker

        self._graph = self._build_graph()

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self) -> Any:
        """Build LangGraph: classify -> gather -> synthesize."""
        builder = StateGraph(PlannerState)
        builder.add_node("classify", self._classify_intent)
        builder.add_node("gather", self._gather_results)
        builder.add_node("synthesize", self._synthesize)

        builder.add_edge(START, "classify")
        builder.add_edge("classify", "gather")
        builder.add_edge("gather", "synthesize")
        builder.add_edge("synthesize", END)
        return builder.compile()

    # ------------------------------------------------------------------
    # Node: classify
    # ------------------------------------------------------------------

    def _classify_intent(self, state: PlannerState) -> dict:
        """Determine planning mode and which workers to invoke.

        Returns:
            dict with ``mode`` and ``workers_to_run``.
        """
        mode = state.get("mode", PlannerMode.DEFAULT.value)

        if mode == PlannerMode.DELTA.value:
            workers = _compute_affected_workers(state.get("user_delta"))
        elif mode == PlannerMode.EXPORT.value:
            workers = ["export"]
        else:
            # DEFAULT and ATTRACTION_ENHANCED both call all planning workers
            workers = list(ALL_PLANNING_WORKERS)

        return {"workers_to_run": workers, "mode": mode}

    # ------------------------------------------------------------------
    # Node: gather
    # ------------------------------------------------------------------

    def _gather_results(self, state: PlannerState) -> dict:
        """Invoke each worker in ``workers_to_run`` sequentially.

        Returns:
            dict with ``{name}_result`` for each worker and ``workers_ran``.
        """
        workers_to_run = state.get("workers_to_run", [])
        results: dict[str, Any] = {}
        workers_ran: list[str] = []

        for name in workers_to_run:
            worker_fn = self._workers.get(name)
            if worker_fn is None:
                # Worker not registered — skip silently (stub not provided)
                continue
            result = worker_fn(state)
            results[f"{name}_result"] = result
            workers_ran.append(name)

            # Legacy compat: propagate familiar keys for _synthesize_legacy
            if name == "attraction" and "attractions" in result:
                results["attractions"] = result["attractions"]
            elif name == "weather" and "weather_info" in result:
                results["weather_info"] = result["weather_info"]
            elif name == "hotel" and "hotel" in result:
                results["hotel"] = result["hotel"]

        results["workers_ran"] = workers_ran
        return results

    # ------------------------------------------------------------------
    # Node: synthesize
    # ------------------------------------------------------------------

    def _synthesize(self, state: PlannerState) -> dict:
        """Generate trip plan from gathered worker results.

        C1 provides a deterministic synthesis matching the A2 baseline.
        Full LLM-powered synthesis will be implemented in C5.
        """
        return self._synthesize_legacy(state)

    def _synthesize_legacy(self, state: PlannerState) -> dict:
        """Deterministic synthesis preserving A2 baseline behavior."""
        request_dict = state.get("request", {})
        try:
            request = TripRequest(**request_dict)
        except Exception:
            return {"trip_plan": None}

        attractions_raw = state.get("attractions", [])
        attractions = [
            a if isinstance(a, Attraction) else Attraction(**a)
            for a in (attractions_raw or [])
        ]
        weather_raw = state.get("weather_info", [])
        weather_info = [
            w if isinstance(w, WeatherInfo) else WeatherInfo(**w)
            for w in (weather_raw or [])
        ]
        hotel_raw = state.get("hotel")
        hotel: Hotel | None = None
        if hotel_raw is not None:
            hotel = hotel_raw if isinstance(hotel_raw, Hotel) else Hotel(**hotel_raw)

        start_date = datetime.strptime(request.start_date, "%Y-%m-%d")
        days: list[DayPlan] = []

        for day_index in range(request.travel_days):
            current_date = (start_date + timedelta(days=day_index)).strftime("%Y-%m-%d")
            start_idx = day_index * 2
            end_idx = start_idx + 2
            day_attractions = (
                attractions[start_idx:end_idx]
                if attractions[start_idx:end_idx]
                else attractions[:2]
            )

            meals = [
                Meal(type="breakfast", name="酒店早餐", description="补充碳水与蛋白", estimated_cost=30),
                Meal(type="lunch", name="本地特色午餐", description="靠近景点的口碑餐馆", estimated_cost=60),
                Meal(type="dinner", name="晚餐推荐", description="步行可达的晚餐选择", estimated_cost=90),
            ]

            days.append(
                DayPlan(
                    date=current_date,
                    day_index=day_index,
                    description=f"第{day_index + 1}天围绕{request.city}核心区域游览",
                    transportation=request.transportation,
                    accommodation=request.accommodation,
                    hotel=hotel,
                    attractions=day_attractions,
                    meals=meals,
                )
            )

        total_attractions = sum(a.ticket_price for day in days for a in day.attractions)
        total_hotels = (hotel.estimated_cost if hotel else 0) * request.travel_days
        total_meals = sum(m.estimated_cost for day in days for m in day.meals)
        total_transportation = 60 * request.travel_days

        budget = Budget(
            total_attractions=total_attractions,
            total_hotels=total_hotels,
            total_meals=total_meals,
            total_transportation=total_transportation,
            total=total_attractions + total_hotels + total_meals + total_transportation,
        )

        trip_plan = TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=days,
            weather_info=weather_info,
            overall_suggestions="已根据景点、天气和酒店偏好生成基础行程，建议出发前再次确认营业时间。",
            budget=budget,
        )

        return {"trip_plan": trip_plan}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan(
        self,
        request: TripRequest,
        *,
        mode: PlannerMode | str = PlannerMode.DEFAULT,
        previous_plan: dict | None = None,
        user_delta: str | None = None,
    ) -> PlannerState:
        """Run the planner graph with explicit mode and optional delta.

        Args:
            request: Travel request payload.
            mode: Planning mode (default / attraction_enhanced / delta / export).
            previous_plan: Previous plan dict for delta mode.
            user_delta: User modification description for delta mode.

        Returns:
            Full ``PlannerState`` dict including routing metadata.
        """
        mode_value = mode.value if isinstance(mode, PlannerMode) else str(mode)
        initial: PlannerState = {
            "request": request.model_dump(),
            "mode": mode_value,
            "previous_plan": previous_plan,
            "user_delta": user_delta,
        }
        return self._graph.invoke(initial)

    def plan_trip(self, request: TripRequest) -> TripPlan:
        """Backward-compatible entry: generate trip plan via default mode.

        Preserves the A2 baseline signature used by ``/api/trip/plan``.
        """
        result = self.plan(request, mode=PlannerMode.DEFAULT)
        plan = result.get("trip_plan")
        if plan is None:
            return self._fallback_plan(request)
        if isinstance(plan, TripPlan):
            return plan
        return TripPlan(**plan)

    @property
    def workers(self) -> dict[str, WorkerFn]:
        """Registered worker callables (read-only)."""
        return dict(self._workers)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_plan(request: TripRequest) -> TripPlan:
        """Minimal valid TripPlan when synthesis fails."""
        return TripPlan(
            city=request.city,
            start_date=request.start_date,
            end_date=request.end_date,
            days=[],
            weather_info=[],
            overall_suggestions="规划生成失败，请稍后重试。",
            budget=Budget(),
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _compute_affected_workers(user_delta: str | None) -> list[str]:
    """Parse ``user_delta`` text and return list of affected worker names.

    Falls back to all planning workers if no keywords match.
    """
    if not user_delta:
        return list(ALL_PLANNING_WORKERS)

    delta_lower = user_delta.lower()
    affected: list[str] = []

    for worker, keywords in DELTA_KEYWORDS.items():
        if any(kw in delta_lower for kw in keywords):
            affected.append(worker)

    return affected if affected else list(ALL_PLANNING_WORKERS)


# ---------------------------------------------------------------------------
# Legacy worker wrappers
# ---------------------------------------------------------------------------

def _wrap_legacy_attraction(agent: Any) -> WorkerFn:
    """Wrap A2-style AttractionAgent.run(request) into WorkerFn."""
    def _worker(state: PlannerState) -> dict:
        request = TripRequest(**state["request"])
        attractions = agent.run(request)
        return {"attractions": [a.model_dump() if hasattr(a, "model_dump") else a for a in attractions]}
    return _worker


def _wrap_legacy_weather(agent: Any) -> WorkerFn:
    """Wrap A2-style WeatherAgent.run(request) into WorkerFn."""
    def _worker(state: PlannerState) -> dict:
        request = TripRequest(**state["request"])
        weather_info = agent.run(request)
        return {"weather_info": [w.model_dump() if hasattr(w, "model_dump") else w for w in weather_info]}
    return _worker


def _wrap_legacy_hotel(agent: Any) -> WorkerFn:
    """Wrap A2-style HotelAgent.run(request) into WorkerFn."""
    def _worker(state: PlannerState) -> dict:
        request = TripRequest(**state["request"])
        hotel = agent.run(request)
        return {"hotel": hotel.model_dump() if hasattr(hotel, "model_dump") else hotel}
    return _worker


# ---------------------------------------------------------------------------
# Singleton factory (backward compat)
# ---------------------------------------------------------------------------

_planner_agent: PlannerAgent | None = None


def get_planner_agent() -> PlannerAgent:
    """Get singleton planner agent instance with legacy workers.

    AttractionAgent / WeatherAgent use the new ``as_worker()`` protocol (C2/C3+).
    HotelAgent still uses legacy wrapper until C4.
    """
    global _planner_agent
    if _planner_agent is None:
        from app.agents.workers import AttractionAgent, HotelAgent, WeatherAgent

        attraction = AttractionAgent()
        weather = WeatherAgent()
        _planner_agent = PlannerAgent(
            workers={
                "attraction": attraction.as_worker(),
                "weather": weather.as_worker(),
            },
            hotel_agent=HotelAgent(),
        )
    return _planner_agent


def reset_planner_agent() -> None:
    """Reset singleton for testing."""
    global _planner_agent
    _planner_agent = None
