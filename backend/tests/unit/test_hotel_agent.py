"""Unit tests for C4 HotelAgent — ProviderRegistry-based hotel search.

Covers:
- Hotel from real POI data
- Accommodation tier / budget mapping
- Fallback behaviour on POI failure
- source_url for Amap vs Google
- as_worker() WorkerFn protocol
- Lazy vs injected registry resolution
- Schema compliance
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from app.agents.workers.hotel_agent import (
    CITY_CENTER,
    HotelAgent,
    _ACCOMMODATION_TIERS,
    _DEFAULT_TIER,
)
from app.models.schemas import Hotel, Location, TripRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(**overrides) -> TripRequest:
    defaults = {
        "city": "北京",
        "start_date": "2026-03-10",
        "end_date": "2026-03-12",
        "travel_days": 3,
        "transportation": "公共交通",
        "accommodation": "舒适型酒店",
        "preferences": ["观光"],
    }
    defaults.update(overrides)
    return TripRequest(**defaults)


def _make_poi(name: str = "如家快捷酒店(天安门店)", address: str = "北京市东城区") -> SimpleNamespace:
    return SimpleNamespace(
        id="B001",
        name=name,
        type="酒店",
        address=address,
        location=Location(longitude=116.40, latitude=39.91),
        tel="010-12345678",
    )


def _make_registry(pois: list | None = None, *, provider_name: str = "amap") -> MagicMock:
    """Build a mock ProviderRegistry with map.search_poi and provider_name."""
    registry = MagicMock()
    registry.map.search_poi.return_value = pois if pois is not None else [_make_poi()]
    type(registry.map).provider_name = PropertyMock(return_value=provider_name)
    return registry


# ===========================================================================
# TestHotelFromPOI — real POI results
# ===========================================================================

class TestHotelFromPOI:
    """When map provider returns POIs, HotelAgent picks the first one."""

    def test_returns_hotel_model(self):
        agent = HotelAgent(registry=_make_registry())
        result = agent.run(_make_request())
        assert isinstance(result, Hotel)

    def test_name_from_poi(self):
        poi = _make_poi(name="北京国际大酒店")
        agent = HotelAgent(registry=_make_registry([poi]))
        result = agent.run(_make_request())
        assert result.name == "北京国际大酒店"

    def test_address_from_poi(self):
        poi = _make_poi(address="建国门大街1号")
        agent = HotelAgent(registry=_make_registry([poi]))
        result = agent.run(_make_request())
        assert result.address == "建国门大街1号"

    def test_location_from_poi(self):
        agent = HotelAgent(registry=_make_registry())
        result = agent.run(_make_request())
        assert result.location is not None
        assert result.location.longitude == pytest.approx(116.40)

    def test_has_source_url(self):
        agent = HotelAgent(registry=_make_registry())
        result = agent.run(_make_request())
        assert result.source_url is not None
        assert "amap" in result.source_url or "google" in result.source_url

    def test_has_estimated_cost(self):
        agent = HotelAgent(registry=_make_registry())
        result = agent.run(_make_request())
        assert result.estimated_cost > 0

    def test_calls_provider_with_city(self):
        reg = _make_registry()
        agent = HotelAgent(registry=reg)
        agent.run(_make_request(city="上海"))
        reg.map.search_poi.assert_called_once()
        call_kwargs = reg.map.search_poi.call_args
        assert call_kwargs[1]["city"] == "上海" or call_kwargs[0][1] == "上海"

    def test_picks_first_poi(self):
        poi1 = _make_poi(name="第一酒店")
        poi2 = _make_poi(name="第二酒店")
        agent = HotelAgent(registry=_make_registry([poi1, poi2]))
        result = agent.run(_make_request())
        assert result.name == "第一酒店"


# ===========================================================================
# TestAccommodationTier — budget / tier mapping
# ===========================================================================

class TestAccommodationTier:
    """Accommodation preference maps to correct keyword and price."""

    def test_economy_keyword(self):
        reg = _make_registry()
        agent = HotelAgent(registry=reg)
        agent.run(_make_request(accommodation="经济型"))
        call_args = reg.map.search_poi.call_args
        # keyword should be 快捷酒店
        keyword_arg = call_args[1].get("keywords") or call_args[0][0]
        assert "快捷" in keyword_arg

    def test_luxury_price_range(self):
        agent = HotelAgent(registry=_make_registry())
        result = agent.run(_make_request(accommodation="豪华型"))
        assert "800" in result.price_range or "1500" in result.price_range

    def test_default_tier_for_unknown(self):
        agent = HotelAgent(registry=_make_registry())
        result = agent.run(_make_request(accommodation="未知类型"))
        assert result.price_range == _DEFAULT_TIER["price_range"]

    def test_estimated_cost_varies_by_tier(self):
        reg = _make_registry()
        agent = HotelAgent(registry=reg)
        eco = agent.run(_make_request(accommodation="经济型"))
        lux = agent.run(_make_request(accommodation="豪华型"))
        assert lux.estimated_cost > eco.estimated_cost


# ===========================================================================
# TestFallback — no POIs or exception
# ===========================================================================

class TestFallback:
    """When POI search returns empty or raises, use deterministic fallback."""

    def test_empty_pois_uses_fallback(self):
        reg = _make_registry(pois=[])
        agent = HotelAgent(registry=reg)
        result = agent.run(_make_request())
        assert "推荐酒店" in result.name

    def test_exception_triggers_fallback(self):
        reg = _make_registry()
        reg.map.search_poi.side_effect = RuntimeError("API down")
        agent = HotelAgent(registry=reg)
        result = agent.run(_make_request())
        assert isinstance(result, Hotel)
        assert "推荐酒店" in result.name

    def test_fallback_uses_city_center(self):
        reg = _make_registry(pois=[])
        agent = HotelAgent(registry=reg)
        result = agent.run(_make_request(city="成都"))
        expected_lon, expected_lat = CITY_CENTER["成都"]
        assert result.location.longitude == pytest.approx(expected_lon)
        assert result.location.latitude == pytest.approx(expected_lat)

    def test_fallback_unknown_city(self):
        reg = _make_registry(pois=[])
        agent = HotelAgent(registry=reg)
        result = agent.run(_make_request(city="拉萨"))
        # Falls back to Beijing coordinates
        assert result.location.longitude == pytest.approx(116.397128)

    def test_fallback_source_url(self):
        reg = _make_registry(pois=[])
        agent = HotelAgent(registry=reg)
        result = agent.run(_make_request(city="杭州"))
        assert "杭州" in result.source_url
        assert "酒店" in result.source_url


# ===========================================================================
# TestSourceURL — Amap vs Google
# ===========================================================================

class TestSourceURL:
    """source_url varies based on active map provider."""

    def test_amap_url(self):
        reg = _make_registry(provider_name="amap")
        agent = HotelAgent(registry=reg)
        result = agent.run(_make_request())
        assert "ditu.amap.com" in result.source_url

    def test_google_url(self):
        reg = _make_registry(provider_name="google")
        agent = HotelAgent(registry=reg)
        result = agent.run(_make_request())
        assert "google.com/maps" in result.source_url


# ===========================================================================
# TestAsWorker — WorkerFn protocol
# ===========================================================================

class TestAsWorker:
    """as_worker() returns a callable conforming to WorkerFn protocol."""

    def test_returns_dict(self):
        agent = HotelAgent(registry=_make_registry())
        worker = agent.as_worker()
        result = worker({"request": _make_request().model_dump()})
        assert isinstance(result, dict)

    def test_has_hotel_key(self):
        agent = HotelAgent(registry=_make_registry())
        worker = agent.as_worker()
        result = worker({"request": _make_request().model_dump()})
        assert "hotel" in result

    def test_hotel_is_dict(self):
        agent = HotelAgent(registry=_make_registry())
        worker = agent.as_worker()
        result = worker({"request": _make_request().model_dump()})
        assert isinstance(result["hotel"], dict)

    def test_hotel_has_required_fields(self):
        agent = HotelAgent(registry=_make_registry())
        worker = agent.as_worker()
        result = worker({"request": _make_request().model_dump()})
        hotel = result["hotel"]
        for field in ("name", "address", "price_range", "source_url", "estimated_cost"):
            assert field in hotel, f"Missing field: {field}"


# ===========================================================================
# TestRegistryLazy — lazy vs injected resolution
# ===========================================================================

class TestRegistryLazy:
    """Registry is resolved lazily when not injected."""

    def test_lazy_resolution(self):
        agent = HotelAgent()  # no registry injected
        assert agent._registry is None  # not yet resolved

    def test_injected_not_lazily_resolved(self):
        reg = _make_registry()
        agent = HotelAgent(registry=reg)
        assert agent._registry is reg


# ===========================================================================
# TestSchemaCompliance — output validates against Hotel schema
# ===========================================================================

class TestSchemaCompliance:
    """Output round-trips through Hotel schema without error."""

    def test_all_fields_serializable(self):
        agent = HotelAgent(registry=_make_registry())
        result = agent.run(_make_request())
        data = result.model_dump()
        Hotel(**data)  # round-trip

    def test_fallback_serializable(self):
        reg = _make_registry(pois=[])
        agent = HotelAgent(registry=reg)
        result = agent.run(_make_request())
        data = result.model_dump()
        Hotel(**data)  # round-trip
