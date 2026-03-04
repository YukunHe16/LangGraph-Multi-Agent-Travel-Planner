"""Planner agent rewritten to LangGraph while preserving hello-agents baseline behavior."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.workers import AttractionAgent, HotelAgent, WeatherAgent
from app.models.schemas import (
    Attraction,
    AttractionWorkerOutput,
    Budget,
    DayPlan,
    Hotel,
    HotelWorkerOutput,
    Meal,
    PlannerSynthesisInput,
    TripPlan,
    TripRequest,
    WeatherWorkerOutput,
    WeatherInfo,
)
from app.prompts.trip_prompts import PLANNER_AGENT_PROMPT


class PlannerState(TypedDict, total=False):
    """State container for planner graph orchestration."""

    request: TripRequest
    attractions: list[Attraction]
    weather_info: list[WeatherInfo]
    hotel: Hotel
    trip_plan: TripPlan


@dataclass
class PlannerAgent:
    """LangGraph planner that coordinates attraction/weather/hotel workers."""

    attraction_agent: AttractionAgent
    weather_agent: WeatherAgent
    hotel_agent: HotelAgent
    prompt: str = PLANNER_AGENT_PROMPT

    def __post_init__(self) -> None:
        self._graph = self._build_graph()

    def _build_graph(self):
        graph_builder = StateGraph(PlannerState)
        graph_builder.add_node("attraction", self._run_attraction)
        graph_builder.add_node("weather", self._run_weather)
        graph_builder.add_node("hotel", self._run_hotel)
        graph_builder.add_node("synthesize", self._synthesize)

        graph_builder.add_edge(START, "attraction")
        graph_builder.add_edge("attraction", "weather")
        graph_builder.add_edge("weather", "hotel")
        graph_builder.add_edge("hotel", "synthesize")
        graph_builder.add_edge("synthesize", END)
        return graph_builder.compile()

    def _run_attraction(self, state: PlannerState) -> PlannerState:
        request = state["request"]
        output = AttractionWorkerOutput(attractions=self.attraction_agent.run(request))
        return output.model_dump()

    def _run_weather(self, state: PlannerState) -> PlannerState:
        request = state["request"]
        output = WeatherWorkerOutput(weather_info=self.weather_agent.run(request))
        return output.model_dump()

    def _run_hotel(self, state: PlannerState) -> PlannerState:
        request = state["request"]
        output = HotelWorkerOutput(hotel=self.hotel_agent.run(request))
        return output.model_dump()

    def _synthesize(self, state: PlannerState) -> PlannerState:
        synthesis_input = PlannerSynthesisInput(
            request=state["request"],
            attractions=state.get("attractions", []),
            weather_info=state.get("weather_info", []),
            hotel=state.get("hotel"),
        )
        request = synthesis_input.request
        attractions = synthesis_input.attractions
        weather_info = synthesis_input.weather_info
        hotel = synthesis_input.hotel

        start_date = datetime.strptime(request.start_date, "%Y-%m-%d")
        days: list[DayPlan] = []

        for day_index in range(request.travel_days):
            current_date = (start_date + timedelta(days=day_index)).strftime("%Y-%m-%d")
            start = day_index * 2
            end = start + 2
            day_attractions = attractions[start:end] if attractions[start:end] else attractions[:2]

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

    def plan_trip(self, request: TripRequest) -> TripPlan:
        """Generate trip plan through LangGraph workflow."""
        result = self._graph.invoke({"request": request})
        return result["trip_plan"]


_planner_agent: PlannerAgent | None = None


def get_planner_agent() -> PlannerAgent:
    """Get singleton planner agent instance."""
    global _planner_agent
    if _planner_agent is None:
        _planner_agent = PlannerAgent(
            attraction_agent=AttractionAgent(),
            weather_agent=WeatherAgent(),
            hotel_agent=HotelAgent(),
        )
    return _planner_agent
