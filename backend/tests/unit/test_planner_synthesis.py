"""Unit tests for C5 PlannerAgent synthesis & conflict handling.

Covers:
- Worker result integration (attraction/weather/hotel/flight/visa)
- Per-day itinerary assembly
- Budget calculation
- Conflict detection (weather/hotel/flight)
- Source link collection & traceability
- flight_plan / visa_summary passthrough
- Weather-aware day descriptions
- Overall suggestions with conflict summary
- Backward compatibility with plan_trip()
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.agents.planner.planner_agent import (
    PlannerAgent,
    PlannerMode,
    PlannerState,
    WorkerFn,
    _build_day_description,
    _build_overall_suggestions,
    _collect_source_links,
    _compute_budget,
    _detect_flight_conflict,
    _detect_hotel_conflict,
    _detect_weather_conflict,
    _extract_attractions,
    _extract_hotel,
    _extract_weather,
)
from app.models.schemas import (
    Attraction,
    Budget,
    DayPlan,
    Hotel,
    Location,
    Meal,
    TripPlan,
    TripRequest,
    WeatherInfo,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(**overrides: Any) -> TripRequest:
    defaults = {
        "city": "北京",
        "start_date": "2026-06-01",
        "end_date": "2026-06-03",
        "travel_days": 3,
        "transportation": "公共交通",
        "accommodation": "舒适型酒店",
        "preferences": ["历史文化"],
    }
    defaults.update(overrides)
    return TripRequest(**defaults)


def _make_attraction(name: str = "故宫", ticket_price: int = 60) -> Attraction:
    return Attraction(
        name=name,
        address="北京市东城区",
        location=Location(longitude=116.40, latitude=39.91),
        visit_duration=120,
        description=f"{name}是北京著名景点",
        category="历史文化",
        rating=4.8,
        source_url=f"https://ditu.amap.com/search?query={name}",
        ticket_price=ticket_price,
    )


def _make_weather(
    date: str = "2026-06-01",
    day_weather: str = "晴",
    day_temp: int = 28,
) -> WeatherInfo:
    return WeatherInfo(
        date=date,
        day_weather=day_weather,
        night_weather="多云",
        day_temp=day_temp,
        night_temp=18,
        wind_direction="南风",
        wind_power="3级",
    )


def _make_hotel(name: str = "北京国际大酒店", estimated_cost: int = 400) -> Hotel:
    return Hotel(
        name=name,
        address="北京市东城区建国门大街",
        location=Location(longitude=116.42, latitude=39.90),
        price_range="300-500元/晚",
        rating="4.6",
        distance="距离核心景点约2公里",
        type="舒适型酒店",
        source_url="https://ditu.amap.com/search?query=北京国际大酒店",
        estimated_cost=estimated_cost,
    )


def _make_attraction_worker(attractions: list[Attraction] | None = None) -> WorkerFn:
    """Create a mock attraction worker."""
    if attractions is None:
        attractions = [_make_attraction("故宫", 60), _make_attraction("天坛", 35),
                       _make_attraction("颐和园", 30), _make_attraction("长城", 80),
                       _make_attraction("天安门", 0), _make_attraction("南锣鼓巷", 0)]

    def worker(state: PlannerState) -> dict:
        return {"attractions": [a.model_dump() for a in attractions]}
    return worker


def _make_weather_worker(weather: list[WeatherInfo] | None = None) -> WorkerFn:
    """Create a mock weather worker."""
    if weather is None:
        weather = [
            _make_weather("2026-06-01", "晴", 28),
            _make_weather("2026-06-02", "多云", 26),
            _make_weather("2026-06-03", "晴", 30),
        ]

    def worker(state: PlannerState) -> dict:
        return {"weather_info": [w.model_dump() for w in weather]}
    return worker


def _make_hotel_worker(hotel: Hotel | None = None) -> WorkerFn:
    """Create a mock hotel worker."""
    if hotel is None:
        hotel = _make_hotel()

    def worker(state: PlannerState) -> dict:
        return {"hotel": hotel.model_dump()}
    return worker


def _make_flight_worker(items: list[dict] | None = None) -> WorkerFn:
    """Create a mock flight worker returning flight_plan."""
    if items is None:
        items = [{
            "id": "offer-1",
            "price": 1200.0,
            "currency": "CNY",
            "outbound_segments": [{
                "departure_airport": "PEK",
                "arrival_airport": "SHA",
                "departure_time": "2026-06-01T08:00:00",
                "arrival_time": "2026-06-01T10:30:00",
                "carrier": "CA",
                "flight_number": "CA1234",
            }],
            "return_segments": [],
            "booking_url": "https://flights.example.com/book/offer-1",
            "source_url": "https://flights.example.com/search",
        }]

    def worker(state: PlannerState) -> dict:
        return {"items": items}
    return worker


def _make_visa_worker(requirements: list[dict] | None = None) -> WorkerFn:
    """Create a mock visa worker returning visa_summary."""
    if requirements is None:
        requirements = [{
            "visa_required": True,
            "visa_type": "tourist",
            "documents": ["护照", "签证申请表"],
            "processing_time": "5个工作日",
            "source_url": "https://visa.example.com/jp",
        }]

    def worker(state: PlannerState) -> dict:
        return {"requirements": requirements}
    return worker


def _build_planner(**workers: WorkerFn) -> PlannerAgent:
    """Build a PlannerAgent with provided workers."""
    return PlannerAgent(workers=workers)


def _plan_default(planner: PlannerAgent, request: TripRequest | None = None) -> PlannerState:
    """Run planner in default mode and return state."""
    if request is None:
        request = _make_request()
    return planner.plan(request, mode=PlannerMode.DEFAULT)


# ===========================================================================
# TestSynthesisIntegration — full pipeline with all workers
# ===========================================================================

class TestSynthesisIntegration:
    """Test _synthesize produces a complete TripPlan from worker results."""

    def _build_full_planner(self) -> PlannerAgent:
        return _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
        )

    def test_produces_trip_plan(self):
        planner = self._build_full_planner()
        result = _plan_default(planner)
        assert result.get("trip_plan") is not None

    def test_trip_plan_is_model(self):
        planner = self._build_full_planner()
        result = _plan_default(planner)
        assert isinstance(result["trip_plan"], TripPlan)

    def test_days_count_matches_travel_days(self):
        planner = self._build_full_planner()
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert len(plan.days) == 3

    def test_weather_info_preserved(self):
        planner = self._build_full_planner()
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert len(plan.weather_info) == 3

    def test_hotel_assigned_to_each_day(self):
        planner = self._build_full_planner()
        result = _plan_default(planner)
        plan = result["trip_plan"]
        for day in plan.days:
            assert day.hotel is not None
            assert day.hotel.name == "北京国际大酒店"

    def test_attractions_distributed_across_days(self):
        planner = self._build_full_planner()
        result = _plan_default(planner)
        plan = result["trip_plan"]
        for day in plan.days:
            assert len(day.attractions) > 0

    def test_meals_included(self):
        planner = self._build_full_planner()
        result = _plan_default(planner)
        plan = result["trip_plan"]
        for day in plan.days:
            assert len(day.meals) == 3

    def test_budget_computed(self):
        planner = self._build_full_planner()
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert plan.budget is not None
        assert plan.budget.total > 0

    def test_source_links_populated(self):
        planner = self._build_full_planner()
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert len(plan.source_links) > 0

    def test_source_links_contain_attraction_urls(self):
        planner = self._build_full_planner()
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert any("故宫" in url for url in plan.source_links)

    def test_source_links_contain_hotel_url(self):
        planner = self._build_full_planner()
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert any("酒店" in url or "ditu.amap" in url for url in plan.source_links)


# ===========================================================================
# TestFlightVisa — flight_plan & visa_summary passthrough
# ===========================================================================

class TestFlightVisa:
    """flight_plan and visa_summary must appear in TripPlan output."""

    def test_flight_plan_present_when_worker_provides(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
            flight=_make_flight_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert plan.flight_plan is not None
        assert "items" in plan.flight_plan

    def test_visa_summary_present_when_worker_provides(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
            visa=_make_visa_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert plan.visa_summary is not None
        assert "requirements" in plan.visa_summary

    def test_flight_plan_none_without_worker(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert plan.flight_plan is None

    def test_visa_summary_none_without_worker(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert plan.visa_summary is None

    def test_flight_source_links_collected(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
            flight=_make_flight_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert any("flights.example.com" in url for url in plan.source_links)

    def test_visa_source_links_collected(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
            visa=_make_visa_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert any("visa.example.com" in url for url in plan.source_links)


# ===========================================================================
# TestConflictDetection — weather, hotel, flight conflicts
# ===========================================================================

class TestConflictDetection:
    """Detect and report conflicts in synthesised plan."""

    def test_rainy_day_conflict_detected(self):
        weather = [
            _make_weather("2026-06-01", "大雨", 22),
            _make_weather("2026-06-02", "晴", 28),
            _make_weather("2026-06-03", "晴", 30),
        ]
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(weather),
            hotel=_make_hotel_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert len(plan.conflicts) >= 1
        assert any("大雨" in c for c in plan.conflicts)

    def test_no_conflict_on_sunny_day(self):
        weather = [
            _make_weather("2026-06-01", "晴", 28),
            _make_weather("2026-06-02", "多云", 26),
            _make_weather("2026-06-03", "晴", 30),
        ]
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(weather),
            hotel=_make_hotel_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        # No weather conflicts
        weather_conflicts = [c for c in plan.conflicts if "天气" in c or "雨" in c or "室内" in c]
        assert len(weather_conflicts) == 0

    def test_hotel_tier_mismatch_conflict(self):
        hotel = _make_hotel()
        hotel.type = "豪华型酒店"  # mismatch with request "舒适型酒店"
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(hotel),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert any("住宿偏好" in c for c in plan.conflicts)

    def test_flight_date_mismatch_conflict(self):
        items = [{
            "id": "offer-1",
            "price": 1200.0,
            "currency": "CNY",
            "outbound_segments": [{
                "departure_airport": "PEK",
                "arrival_airport": "SHA",
                "departure_time": "2026-06-05T08:00:00",  # Wrong date
                "arrival_time": "2026-06-05T10:30:00",
                "carrier": "CA",
                "flight_number": "CA1234",
            }],
            "return_segments": [],
        }]
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
            flight=_make_flight_worker(items),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert any("航班" in c for c in plan.conflicts)

    def test_conflicts_in_overall_suggestions(self):
        weather = [
            _make_weather("2026-06-01", "暴雨", 18),
            _make_weather("2026-06-02", "晴", 28),
            _make_weather("2026-06-03", "晴", 30),
        ]
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(weather),
            hotel=_make_hotel_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert "冲突" in plan.overall_suggestions or "降水" in plan.overall_suggestions


# ===========================================================================
# TestWeatherAwareDays — weather info in day descriptions
# ===========================================================================

class TestWeatherAwareDays:
    """Day descriptions integrate weather information."""

    def test_sunny_day_shows_temp(self):
        weather = [_make_weather("2026-06-01", "晴", 28)]
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(weather + [
                _make_weather("2026-06-02"), _make_weather("2026-06-03")
            ]),
            hotel=_make_hotel_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert "28°C" in plan.days[0].description or "晴" in plan.days[0].description

    def test_rainy_day_suggests_indoor(self):
        weather = [
            _make_weather("2026-06-01", "大雨", 22),
            _make_weather("2026-06-02", "晴", 28),
            _make_weather("2026-06-03", "晴", 30),
        ]
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(weather),
            hotel=_make_hotel_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert "室内" in plan.days[0].description or "雨具" in plan.days[0].description

    def test_day_description_includes_attraction_names(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert "故宫" in plan.days[0].description


# ===========================================================================
# TestBudget — budget calculation correctness
# ===========================================================================

class TestBudget:
    """Budget computation from assembled day plans."""

    def test_total_is_sum_of_parts(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        b = plan.budget
        assert b.total == b.total_attractions + b.total_hotels + b.total_meals + b.total_transportation

    def test_hotel_cost_multiplied_by_days(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(_make_hotel(estimated_cost=500)),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert plan.budget.total_hotels == 500 * 3

    def test_transportation_per_day(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert plan.budget.total_transportation == 60 * 3

    def test_meals_per_day(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        # 3 meals/day at 30+60+90 = 180/day * 3 = 540
        assert plan.budget.total_meals == 540


# ===========================================================================
# TestSourceLinks — link traceability
# ===========================================================================

class TestSourceLinks:
    """Source links collected from all worker outputs."""

    def test_no_duplicate_links(self):
        # Use attractions with same source_url
        attractions = [
            _make_attraction("故宫", 60),
            _make_attraction("故宫", 60),  # duplicate
        ]
        planner = _build_planner(
            attraction=_make_attraction_worker(attractions),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert len(plan.source_links) == len(set(plan.source_links))

    def test_empty_when_no_urls(self):
        # Attractions with no source_url
        attr = _make_attraction()
        attr.source_url = None
        hotel = _make_hotel()
        hotel.source_url = None
        planner = _build_planner(
            attraction=_make_attraction_worker([attr]),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(hotel),
        )
        result = _plan_default(planner)
        plan = result["trip_plan"]
        assert len(plan.source_links) == 0


# ===========================================================================
# TestBackwardCompat — plan_trip() still works
# ===========================================================================

class TestBackwardCompat:
    """plan_trip() backward-compatible API returns TripPlan."""

    def test_plan_trip_returns_trip_plan(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
        )
        plan = planner.plan_trip(_make_request())
        assert isinstance(plan, TripPlan)

    def test_plan_trip_has_new_fields(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
        )
        plan = planner.plan_trip(_make_request())
        assert hasattr(plan, "source_links")
        assert hasattr(plan, "flight_plan")
        assert hasattr(plan, "visa_summary")
        assert hasattr(plan, "conflicts")

    def test_plan_trip_serializable(self):
        planner = _build_planner(
            attraction=_make_attraction_worker(),
            weather=_make_weather_worker(),
            hotel=_make_hotel_worker(),
        )
        plan = planner.plan_trip(_make_request())
        data = plan.model_dump()
        TripPlan(**data)  # round-trip


# ===========================================================================
# TestHelperFunctions — unit tests for individual helpers
# ===========================================================================

class TestHelperFunctions:
    """Granular tests for synthesis helper functions."""

    def test_extract_attractions_from_dicts(self):
        state: PlannerState = {"attractions": [_make_attraction().model_dump()]}
        result = _extract_attractions(state)
        assert len(result) == 1
        assert isinstance(result[0], Attraction)

    def test_extract_attractions_from_models(self):
        state: PlannerState = {"attractions": [_make_attraction()]}
        result = _extract_attractions(state)
        assert len(result) == 1

    def test_extract_weather_empty(self):
        state: PlannerState = {}
        result = _extract_weather(state)
        assert result == []

    def test_extract_hotel_none(self):
        state: PlannerState = {}
        result = _extract_hotel(state)
        assert result is None

    def test_extract_hotel_from_dict(self):
        state: PlannerState = {"hotel": _make_hotel().model_dump()}
        result = _extract_hotel(state)
        assert isinstance(result, Hotel)

    def test_detect_weather_conflict_rain(self):
        w = _make_weather(day_weather="大雨")
        result = _detect_weather_conflict(0, w)
        assert result is not None
        assert "大雨" in result

    def test_detect_weather_conflict_sunny(self):
        w = _make_weather(day_weather="晴")
        result = _detect_weather_conflict(0, w)
        assert result is None

    def test_detect_hotel_conflict_match(self):
        hotel = _make_hotel()
        hotel.type = "舒适型酒店"
        request = _make_request(accommodation="舒适型酒店")
        result = _detect_hotel_conflict(hotel, request)
        assert result is None

    def test_detect_hotel_conflict_mismatch(self):
        hotel = _make_hotel()
        hotel.type = "豪华型"
        request = _make_request(accommodation="经济型")
        result = _detect_hotel_conflict(hotel, request)
        assert result is not None

    def test_collect_source_links_deduplicates(self):
        a1 = _make_attraction()
        a1.source_url = "https://example.com/a"
        a2 = _make_attraction()
        a2.source_url = "https://example.com/a"  # same
        links = _collect_source_links([a1, a2], None, None, None)
        assert len(links) == 1

    def test_compute_budget_no_hotel(self):
        days = [
            DayPlan(
                date="2026-06-01", day_index=0, description="d1",
                transportation="公共交通", accommodation="无",
                attractions=[_make_attraction(ticket_price=60)],
                meals=[Meal(type="lunch", name="午餐", estimated_cost=50)],
            )
        ]
        budget = _compute_budget(days, None, 1)
        assert budget.total_hotels == 0
        assert budget.total_attractions == 60
        assert budget.total_meals == 50


# ===========================================================================
# TestEdgeCases — no workers, missing data
# ===========================================================================

class TestEdgeCases:
    """Edge cases: no workers, missing data, single day trip."""

    def test_no_workers_produces_plan(self):
        planner = PlannerAgent()
        result = _plan_default(planner)
        plan = result.get("trip_plan")
        # Even with no workers, synthesis should produce a plan (empty data)
        assert plan is not None

    def test_single_day_trip(self):
        planner = _build_planner(
            attraction=_make_attraction_worker([_make_attraction()]),
            weather=_make_weather_worker([_make_weather("2026-06-01")]),
            hotel=_make_hotel_worker(),
        )
        request = _make_request(
            start_date="2026-06-01",
            end_date="2026-06-01",
            travel_days=1,
        )
        result = planner.plan(request, mode=PlannerMode.DEFAULT)
        plan = result["trip_plan"]
        assert len(plan.days) == 1

    def test_invalid_request_returns_none(self):
        planner = PlannerAgent()
        state: PlannerState = {"request": {"invalid": True}}
        result = planner._synthesize(state)
        assert result["trip_plan"] is None
