from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.schemas import (
    AttractionWorkerOutput,
    Hotel,
    HotelWorkerOutput,
    MapPOISearchInput,
    PlannerSynthesisInput,
    RouteRequest,
    TripRequest,
    WeatherWorkerOutput,
)


def test_trip_request_requires_iso_dates() -> None:
    with pytest.raises(ValidationError):
        TripRequest(
            city="北京",
            start_date="2026/06/01",
            end_date="2026-06-03",
            travel_days=3,
            transportation="公共交通",
            accommodation="舒适型酒店",
            preferences=["历史文化"],
        )


def test_route_request_rejects_unsupported_route_type() -> None:
    with pytest.raises(ValidationError):
        RouteRequest(
            origin_address="故宫",
            destination_address="颐和园",
            route_type="cycling",
        )


def test_map_poi_search_input_rejects_empty_keywords() -> None:
    with pytest.raises(ValidationError):
        MapPOISearchInput(keywords="", city="北京", citylimit=True)


def test_agent_intermediate_schemas_validate() -> None:
    request = TripRequest(
        city="北京",
        start_date="2026-06-01",
        end_date="2026-06-03",
        travel_days=3,
        transportation="公共交通",
        accommodation="舒适型酒店",
        preferences=["历史文化"],
    )

    hotel = Hotel(
        name="测试酒店",
        address="北京市东城区",
        price_range="300-500元/晚",
        rating="4.5",
        distance="2km",
        type="舒适型酒店",
        estimated_cost=400,
    )

    planner_input = PlannerSynthesisInput(request=request, hotel=hotel)
    assert planner_input.request.city == "北京"

    hotel_output = HotelWorkerOutput(hotel=hotel)
    assert hotel_output.hotel.name == "测试酒店"

    attraction_output = AttractionWorkerOutput(attractions=[])
    assert attraction_output.attractions == []

    weather_output = WeatherWorkerOutput(weather_info=[])
    assert weather_output.weather_info == []
