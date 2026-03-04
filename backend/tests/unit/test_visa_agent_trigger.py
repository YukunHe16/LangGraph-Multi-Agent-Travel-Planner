"""Unit tests for VisaAgent (C7) — cross-border trigger logic.

Tests verify the core acceptance criteria:
1. Cross-border trips trigger external visa provider query
2. Domestic trips do NOT trigger external query and return not_required
3. Results are explainable and carry source links

Also covers: city→country mapping, HK/MO/TW special handling,
as_worker() protocol, error handling, edge cases.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.agents.workers.visa_agent import (
    CITY_COUNTRY,
    VisaAgent,
    _DEFAULT_NATIONALITY,
    _DOMESTIC_SOURCE_URL,
)
from app.models.schemas import TripRequest, VisaRequirement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(**overrides: Any) -> TripRequest:
    """Build a minimal valid TripRequest."""
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


def _make_requirement(
    visa_required: bool = True,
    visa_type: str = "tourist",
    source_url: str = "https://apply.joinsherpa.com/test",
    **overrides: Any,
) -> VisaRequirement:
    """Build a VisaRequirement with sensible defaults."""
    return VisaRequirement(
        visa_required=visa_required,
        visa_type=visa_type,
        documents=["Passport", "Photo"],
        processing_time="5-10 working days",
        validity="90 days",
        source_url=source_url,
        **overrides,
    )


def _mock_registry(
    requirements: list[VisaRequirement] | None = None,
) -> MagicMock:
    """Create a mock ProviderRegistry with visa provider."""
    if requirements is None:
        requirements = [_make_requirement()]
    reg = MagicMock()
    reg.visa.get_requirements.return_value = requirements
    return reg


# ===========================================================================
# Test: Domestic trips (NO external call)
# ===========================================================================


class TestDomesticNoTrigger:
    """Domestic trips must NOT trigger external visa query."""

    def test_domestic_returns_not_required(self) -> None:
        """CN national → CN city → visa_required=False."""
        reg = _mock_registry()
        agent = VisaAgent(registry=reg, default_nationality="CN")
        result = agent.run(_make_request(city="北京"))
        assert result["visa_required"] is False
        assert result["is_domestic"] is True

    def test_domestic_does_not_call_provider(self) -> None:
        """Provider should NOT be called for domestic trips."""
        reg = _mock_registry()
        agent = VisaAgent(registry=reg, default_nationality="CN")
        agent.run(_make_request(city="上海"))
        reg.visa.get_requirements.assert_not_called()

    def test_domestic_has_empty_requirements(self) -> None:
        reg = _mock_registry()
        agent = VisaAgent(registry=reg, default_nationality="CN")
        result = agent.run(_make_request(city="成都"))
        assert result["requirements"] == []

    def test_domestic_explanation_mentions_no_visa(self) -> None:
        reg = _mock_registry()
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="杭州"))
        assert "无需签证" in result["explanation"]

    def test_domestic_has_source_url(self) -> None:
        reg = _mock_registry()
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="西安"))
        assert result["source_url"] == _DOMESTIC_SOURCE_URL

    def test_multiple_domestic_cities(self) -> None:
        """Verify several well-known Chinese cities are domestic."""
        reg = _mock_registry()
        agent = VisaAgent(registry=reg)
        for city in ["北京", "上海", "广州", "深圳", "成都", "三亚", "拉萨"]:
            result = agent.run(_make_request(city=city))
            assert result["is_domestic"] is True, f"{city} should be domestic"
            reg.visa.get_requirements.assert_not_called()


# ===========================================================================
# Test: Cross-border trips (TRIGGERS external call)
# ===========================================================================


class TestCrossBorderTrigger:
    """Cross-border trips MUST trigger external visa provider query."""

    def test_crossborder_triggers_provider(self) -> None:
        """CN national → JP city → provider.get_requirements called."""
        reg = _mock_registry()
        agent = VisaAgent(registry=reg, default_nationality="CN")
        agent.run(_make_request(city="东京"))
        reg.visa.get_requirements.assert_called_once()

    def test_crossborder_provider_args(self) -> None:
        """Provider called with correct nationality and destination."""
        reg = _mock_registry()
        agent = VisaAgent(registry=reg, default_nationality="CN")
        agent.run(_make_request(city="东京", travel_days=7))
        reg.visa.get_requirements.assert_called_once_with(
            nationality="CN",
            destination="JP",
            travel_duration_days=7,
        )

    def test_crossborder_returns_visa_required(self) -> None:
        req = _make_requirement(visa_required=True)
        reg = _mock_registry([req])
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="东京"))
        assert result["visa_required"] is True
        assert result["is_domestic"] is False

    def test_crossborder_not_required_case(self) -> None:
        """Some cross-border trips may return visa not required (e.g. visa-free)."""
        req = _make_requirement(visa_required=False, visa_type=None)
        reg = _mock_registry([req])
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="曼谷"))
        assert result["visa_required"] is False
        assert result["is_domestic"] is False

    def test_crossborder_has_requirements_list(self) -> None:
        reqs = [_make_requirement(), _make_requirement(visa_type="transit")]
        reg = _mock_registry(reqs)
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="巴黎"))
        assert len(result["requirements"]) == 2

    def test_crossborder_requirements_are_dicts(self) -> None:
        reg = _mock_registry([_make_requirement()])
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="伦敦"))
        assert isinstance(result["requirements"][0], dict)

    def test_nationality_override(self) -> None:
        """Override nationality from default CN to US."""
        reg = _mock_registry()
        agent = VisaAgent(registry=reg, default_nationality="CN")
        agent.run(_make_request(city="东京"), nationality="US")
        assert reg.visa.get_requirements.call_args[1]["nationality"] == "US"

    def test_international_cities(self) -> None:
        """Verify several international cities trigger cross-border."""
        reg = _mock_registry()
        agent = VisaAgent(registry=reg)
        for city in ["东京", "首尔", "曼谷", "巴黎", "纽约"]:
            result = agent.run(_make_request(city=city))
            assert result["is_domestic"] is False, f"{city} should be cross-border"


# ===========================================================================
# Test: HK/MO/TW special handling
# ===========================================================================


class TestSpecialRegions:
    """HK, MO, TW treated as cross-border for CN nationals."""

    def test_hong_kong_is_cross_border_for_cn(self) -> None:
        reg = _mock_registry()
        agent = VisaAgent(registry=reg, default_nationality="CN")
        result = agent.run(_make_request(city="香港"))
        assert result["is_domestic"] is False
        reg.visa.get_requirements.assert_called_once()

    def test_macau_is_cross_border_for_cn(self) -> None:
        reg = _mock_registry()
        agent = VisaAgent(registry=reg, default_nationality="CN")
        result = agent.run(_make_request(city="澳门"))
        assert result["is_domestic"] is False

    def test_taiwan_is_cross_border_for_cn(self) -> None:
        reg = _mock_registry()
        agent = VisaAgent(registry=reg, default_nationality="CN")
        result = agent.run(_make_request(city="台北"))
        assert result["is_domestic"] is False

    def test_hong_kong_domestic_for_hk_national(self) -> None:
        """HK national → HK city → domestic."""
        reg = _mock_registry()
        agent = VisaAgent(registry=reg, default_nationality="HK")
        result = agent.run(_make_request(city="香港"))
        assert result["is_domestic"] is True
        reg.visa.get_requirements.assert_not_called()


# ===========================================================================
# Test: Source URL traceability
# ===========================================================================


class TestSourceUrl:
    """All results must carry source_url."""

    def test_crossborder_source_from_provider(self) -> None:
        req = _make_requirement(source_url="https://sherpa.example.com/visa")
        reg = _mock_registry([req])
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="东京"))
        assert result["source_url"] == "https://sherpa.example.com/visa"

    def test_crossborder_fallback_source_url(self) -> None:
        """When provider returns no source_url, use default Sherpa link."""
        req = _make_requirement(source_url="")
        # source_url is required in VisaRequirement, use a mock instead
        reg = MagicMock()
        mock_req = MagicMock()
        mock_req.visa_required = True
        mock_req.source_url = ""
        mock_req.model_dump.return_value = {"visa_required": True}
        mock_req.documents = []
        mock_req.visa_type = "tourist"
        mock_req.processing_time = None
        reg.visa.get_requirements.return_value = [mock_req]
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="东京"))
        assert "joinsherpa.com" in result["source_url"]

    def test_domestic_has_source_url(self) -> None:
        reg = _mock_registry()
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="北京"))
        assert result["source_url"] is not None
        assert len(result["source_url"]) > 0


# ===========================================================================
# Test: Explanation
# ===========================================================================


class TestExplanation:
    """Results must be explainable."""

    def test_domestic_explanation(self) -> None:
        reg = _mock_registry()
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="上海"))
        assert "无需签证" in result["explanation"]
        assert "上海" in result["explanation"]

    def test_crossborder_required_explanation(self) -> None:
        req = _make_requirement(visa_required=True, visa_type="tourist")
        reg = _mock_registry([req])
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="东京"))
        assert "办理" in result["explanation"] or "需要" in result["explanation"]

    def test_crossborder_not_required_explanation(self) -> None:
        req = _make_requirement(visa_required=False)
        reg = _mock_registry([req])
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="曼谷"))
        assert "免签" in result["explanation"] or "无需" in result["explanation"]

    def test_empty_requirements_explanation(self) -> None:
        reg = _mock_registry([])
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="东京"))
        assert "暂无数据" in result["explanation"]


# ===========================================================================
# Test: City → Country mapping
# ===========================================================================


class TestCityCountryMapping:
    """City-to-country code mapping correctness."""

    def test_chinese_cities_map_to_cn(self) -> None:
        for city in ["北京", "上海", "广州", "成都", "拉萨"]:
            assert CITY_COUNTRY[city] == "CN"

    def test_japanese_cities_map_to_jp(self) -> None:
        for city in ["东京", "大阪", "京都"]:
            assert CITY_COUNTRY[city] == "JP"

    def test_unknown_city_returns_xx(self) -> None:
        assert VisaAgent._city_to_country("未知城市abc") == "XX"

    def test_unknown_city_treated_as_crossborder(self) -> None:
        """Unknown cities should trigger cross-border (safety)."""
        assert VisaAgent._is_domestic("CN", "XX") is False

    def test_mapping_has_enough_cities(self) -> None:
        assert len(CITY_COUNTRY) >= 50


# ===========================================================================
# Test: as_worker() protocol
# ===========================================================================


class TestAsWorker:
    """WorkerFn protocol adapter."""

    def test_worker_returns_visa_summary_key(self) -> None:
        reg = _mock_registry()
        agent = VisaAgent(registry=reg)
        worker = agent.as_worker()
        state = {"request": _make_request(city="东京").model_dump()}
        result = worker(state)
        assert "visa_summary" in result
        assert isinstance(result["visa_summary"], dict)

    def test_worker_summary_has_required_fields(self) -> None:
        reg = _mock_registry()
        agent = VisaAgent(registry=reg)
        worker = agent.as_worker()
        state = {"request": _make_request(city="东京").model_dump()}
        summary = worker(state)["visa_summary"]
        assert "visa_required" in summary
        assert "requirements" in summary
        assert "nationality" in summary
        assert "destination_country" in summary
        assert "is_domestic" in summary
        assert "source_url" in summary
        assert "explanation" in summary

    def test_worker_domestic_trip(self) -> None:
        reg = _mock_registry()
        agent = VisaAgent(registry=reg)
        worker = agent.as_worker()
        state = {"request": _make_request(city="北京").model_dump()}
        summary = worker(state)["visa_summary"]
        assert summary["is_domestic"] is True
        assert summary["visa_required"] is False
        reg.visa.get_requirements.assert_not_called()


# ===========================================================================
# Test: Error handling
# ===========================================================================


class TestErrorHandling:
    """Graceful degradation on provider errors."""

    def test_provider_exception_returns_empty(self) -> None:
        reg = MagicMock()
        reg.visa.get_requirements.side_effect = RuntimeError("API down")
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="东京"))
        assert result["visa_required"] is False
        assert result["requirements"] == []

    def test_provider_returns_empty_list(self) -> None:
        reg = _mock_registry([])
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="东京"))
        assert result["visa_required"] is False

    def test_domestic_never_errors(self) -> None:
        """Domestic path has no external dependency — always succeeds."""
        reg = MagicMock()
        reg.visa.get_requirements.side_effect = RuntimeError("Should not be called")
        agent = VisaAgent(registry=reg)
        result = agent.run(_make_request(city="北京"))
        assert result["visa_required"] is False
        assert result["is_domestic"] is True


# ===========================================================================
# Test: Edge cases
# ===========================================================================


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_default_nationality_is_cn(self) -> None:
        assert _DEFAULT_NATIONALITY == "CN"

    def test_lazy_registry_resolution(self) -> None:
        agent = VisaAgent()
        assert agent._registry is None

    def test_nationality_case_insensitive(self) -> None:
        reg = _mock_registry()
        agent = VisaAgent(registry=reg)
        agent.run(_make_request(city="东京"), nationality="cn")
        assert reg.visa.get_requirements.call_args[1]["nationality"] == "CN"

    def test_result_keys_complete(self) -> None:
        """All result dicts should have the same set of keys."""
        reg = _mock_registry()
        agent = VisaAgent(registry=reg)
        expected_keys = {
            "visa_required", "requirements", "nationality",
            "destination_country", "is_domestic", "source_url", "explanation",
        }
        # Cross-border
        cross = agent.run(_make_request(city="东京"))
        assert set(cross.keys()) == expected_keys
        # Domestic
        domestic = agent.run(_make_request(city="北京"))
        assert set(domestic.keys()) == expected_keys
