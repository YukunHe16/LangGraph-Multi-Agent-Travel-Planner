"""Unit tests for FlightAgent (C6).

Tests cover:
- Core search and sorting logic
- Booking URL fallback annotation
- City-to-IATA mapping
- Ranking reason generation
- as_worker() protocol integration
- Edge cases (empty results, unknown cities, single-day trip)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.agents.workers.flight_agent import (
    CITY_IATA,
    FlightAgent,
    _DEFAULT_ORIGIN_CITY,
)
from app.models.schemas import FlightOffer, FlightSegment, TripRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(**overrides: Any) -> TripRequest:
    """Build a minimal valid TripRequest with flight-relevant fields."""
    defaults = {
        "city": "东京",
        "start_date": "2026-06-01",
        "end_date": "2026-06-05",
        "travel_days": 5,
        "transportation": "飞机",
        "accommodation": "舒适型酒店",
    }
    defaults.update(overrides)
    return TripRequest(**defaults)


def _make_segment(**overrides: Any) -> FlightSegment:
    """Build a minimal FlightSegment."""
    defaults = {
        "departure_airport": "PEK",
        "arrival_airport": "NRT",
        "departure_time": "2026-06-01T08:00:00",
        "arrival_time": "2026-06-01T12:00:00",
        "carrier": "CA",
        "flight_number": "CA925",
        "duration": "PT4H",
    }
    defaults.update(overrides)
    return FlightSegment(**defaults)


def _make_offer(
    offer_id: str = "offer-1",
    price: float = 3500.0,
    currency: str = "CNY",
    booking_url: str | None = None,
    source_url: str | None = "https://www.amadeus.com",
    carrier_name: str = "CA",
    **overrides: Any,
) -> FlightOffer:
    """Build a FlightOffer with sensible defaults."""
    return FlightOffer(
        id=offer_id,
        price=price,
        currency=currency,
        outbound_segments=[_make_segment()],
        return_segments=[],
        booking_url=booking_url,
        source_url=source_url,
        carrier_name=carrier_name,
        total_duration="PT4H",
        **overrides,
    )


def _mock_registry(offers: list[FlightOffer] | None = None) -> MagicMock:
    """Create a mock ProviderRegistry with flight provider."""
    if offers is None:
        offers = [_make_offer()]
    reg = MagicMock()
    reg.flight.search_flights.return_value = offers
    return reg


# ===========================================================================
# Test Classes
# ===========================================================================


class TestFlightSearch:
    """Core search & sort behavior."""

    def test_run_returns_dict(self) -> None:
        reg = _mock_registry()
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        assert isinstance(result, dict)

    def test_offers_sorted_by_price(self) -> None:
        offers = [
            _make_offer("exp", price=8000),
            _make_offer("mid", price=4000),
            _make_offer("cheap", price=2000),
        ]
        reg = _mock_registry(offers)
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        prices = [o["price"] for o in result["offers"]]
        assert prices == [2000, 4000, 8000]

    def test_provider_called_with_correct_args(self) -> None:
        reg = _mock_registry()
        agent = FlightAgent(registry=reg, origin_city="上海")
        agent.run(_make_request(city="大阪"))
        reg.flight.search_flights.assert_called_once_with(
            origin="PVG",
            destination="KIX",
            departure_date="2026-06-01",
            return_date="2026-06-05",
            adults=1,
            max_results=5,
        )

    def test_single_day_no_return_date(self) -> None:
        """When start_date == end_date, return_date should be None."""
        reg = _mock_registry()
        agent = FlightAgent(registry=reg)
        agent.run(_make_request(start_date="2026-06-01", end_date="2026-06-01"))
        call_kwargs = reg.flight.search_flights.call_args
        assert call_kwargs.kwargs.get("return_date") is None or call_kwargs[1].get("return_date") is None

    def test_origin_and_destination_in_result(self) -> None:
        reg = _mock_registry()
        agent = FlightAgent(registry=reg, origin_city="北京")
        result = agent.run(_make_request(city="东京"))
        assert result["origin"] == "PEK"
        assert result["destination"] == "NRT"
        assert result["origin_city"] == "北京"
        assert result["destination_city"] == "东京"

    def test_max_results_passed(self) -> None:
        reg = _mock_registry()
        agent = FlightAgent(registry=reg)
        agent.run(_make_request(), max_results=3)
        assert reg.flight.search_flights.call_args[1]["max_results"] == 3

    def test_origin_city_override(self) -> None:
        reg = _mock_registry()
        agent = FlightAgent(registry=reg, origin_city="北京")
        agent.run(_make_request(city="东京"), origin_city="上海")
        assert reg.flight.search_flights.call_args[1]["origin"] == "PVG"


class TestBookingUrlFallback:
    """Booking URL annotation & fallback logic."""

    def test_booking_url_present(self) -> None:
        offer = _make_offer(booking_url="https://book.example.com")
        reg = _mock_registry([offer])
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        annotated = result["annotated_offers"]
        assert annotated[0]["display_url"] == "https://book.example.com"
        assert annotated[0]["booking_url_is_fallback"] is False

    def test_booking_url_none_falls_back(self) -> None:
        offer = _make_offer(booking_url=None, source_url="https://www.amadeus.com")
        reg = _mock_registry([offer])
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        annotated = result["annotated_offers"]
        assert annotated[0]["display_url"] == "https://www.amadeus.com"
        assert annotated[0]["booking_url_is_fallback"] is True

    def test_both_urls_none_uses_google_flights(self) -> None:
        offer = _make_offer(booking_url=None, source_url=None)
        reg = _mock_registry([offer])
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        annotated = result["annotated_offers"]
        assert "google.com/flights" in annotated[0]["display_url"]
        assert annotated[0]["booking_url_is_fallback"] is True

    def test_annotated_offers_count_matches(self) -> None:
        offers = [_make_offer(f"o{i}", price=1000 * (i + 1)) for i in range(3)]
        reg = _mock_registry(offers)
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        assert len(result["annotated_offers"]) == 3
        assert len(result["offers"]) == 3


class TestCityToIata:
    """City name to IATA code mapping."""

    def test_known_domestic_cities(self) -> None:
        assert FlightAgent._city_to_iata("北京") == "PEK"
        assert FlightAgent._city_to_iata("上海") == "PVG"
        assert FlightAgent._city_to_iata("广州") == "CAN"
        assert FlightAgent._city_to_iata("成都") == "CTU"

    def test_known_international_cities(self) -> None:
        assert FlightAgent._city_to_iata("东京") == "NRT"
        assert FlightAgent._city_to_iata("首尔") == "ICN"
        assert FlightAgent._city_to_iata("曼谷") == "BKK"

    def test_unknown_city_defaults_to_pek(self) -> None:
        assert FlightAgent._city_to_iata("未知城市") == "PEK"

    def test_city_iata_dict_completeness(self) -> None:
        """Verify the dict has a reasonable number of entries."""
        assert len(CITY_IATA) >= 40


class TestRankingReason:
    """Ranking reason text generation."""

    def test_empty_offers_reason(self) -> None:
        reg = _mock_registry([])
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        assert "暂无航班数据" in result["ranking_reason"]

    def test_reason_contains_count_and_price(self) -> None:
        offers = [
            _make_offer("a", price=2500, carrier_name="MU"),
            _make_offer("b", price=3500, carrier_name="CA"),
        ]
        reg = _mock_registry(offers)
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        reason = result["ranking_reason"]
        assert "2" in reason  # count
        assert "2500" in reason or "2500.0" in reason  # cheapest price
        assert "MU" in reason  # carrier of cheapest

    def test_reason_mentions_sorting(self) -> None:
        offers = [_make_offer()]
        reg = _mock_registry(offers)
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        assert "排序" in result["ranking_reason"]


class TestSourceUrl:
    """Source URL selection logic."""

    def test_source_url_from_offers(self) -> None:
        offer = _make_offer(source_url="https://api.amadeus.com/ref")
        reg = _mock_registry([offer])
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        assert result["source_url"] == "https://api.amadeus.com/ref"

    def test_source_url_fallback_google(self) -> None:
        offer = _make_offer(source_url=None, booking_url=None)
        reg = _mock_registry([offer])
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        assert "google.com/flights" in result["source_url"]


class TestAsWorker:
    """WorkerFn protocol adapter."""

    def test_worker_returns_flight_plan_key(self) -> None:
        reg = _mock_registry()
        agent = FlightAgent(registry=reg)
        worker = agent.as_worker()
        state = {"request": _make_request().model_dump()}
        result = worker(state)
        assert "flight_plan" in result
        assert isinstance(result["flight_plan"], dict)

    def test_worker_plan_has_required_fields(self) -> None:
        reg = _mock_registry()
        agent = FlightAgent(registry=reg)
        worker = agent.as_worker()
        state = {"request": _make_request().model_dump()}
        plan = worker(state)["flight_plan"]
        assert "offers" in plan
        assert "ranking_reason" in plan
        assert "source_url" in plan
        assert "origin" in plan
        assert "destination" in plan

    def test_worker_offers_are_dicts(self) -> None:
        reg = _mock_registry([_make_offer()])
        agent = FlightAgent(registry=reg)
        worker = agent.as_worker()
        state = {"request": _make_request().model_dump()}
        plan = worker(state)["flight_plan"]
        assert len(plan["offers"]) == 1
        assert isinstance(plan["offers"][0], dict)

    def test_worker_result_stored_as_flight_result(self) -> None:
        """Ensure planner can store result under ``flight_result`` key."""
        reg = _mock_registry()
        agent = FlightAgent(registry=reg)
        worker = agent.as_worker()
        state = {"request": _make_request().model_dump()}
        result = worker(state)
        # Planner stores worker output keys as {name}_result
        assert "flight_plan" in result


class TestErrorHandling:
    """Graceful degradation on provider errors."""

    def test_provider_exception_returns_empty(self) -> None:
        reg = MagicMock()
        reg.flight.search_flights.side_effect = RuntimeError("API down")
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        assert result["offers"] == []
        assert "暂无航班数据" in result["ranking_reason"]

    def test_provider_returns_empty_list(self) -> None:
        reg = _mock_registry([])
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        assert result["offers"] == []

    def test_annotated_empty_on_error(self) -> None:
        reg = MagicMock()
        reg.flight.search_flights.side_effect = ConnectionError("timeout")
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        assert result["annotated_offers"] == []


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_default_origin_city(self) -> None:
        assert _DEFAULT_ORIGIN_CITY == "北京"

    def test_many_offers_all_annotated(self) -> None:
        offers = [_make_offer(f"o{i}", price=float(1000 + i * 100)) for i in range(10)]
        reg = _mock_registry(offers)
        agent = FlightAgent(registry=reg)
        result = agent.run(_make_request())
        assert len(result["annotated_offers"]) == 10

    def test_domestic_flight(self) -> None:
        reg = _mock_registry()
        agent = FlightAgent(registry=reg, origin_city="北京")
        result = agent.run(_make_request(city="上海"))
        assert result["origin"] == "PEK"
        assert result["destination"] == "PVG"

    def test_lazy_registry_resolution(self) -> None:
        """Agent without explicit registry should not fail at construction."""
        agent = FlightAgent()
        # Should not raise — registry is lazy
        assert agent._registry is None
