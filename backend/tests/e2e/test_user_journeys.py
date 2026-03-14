"""E2E tests for E3: core user journeys through ``/api/trip/plan``."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi.testclient import TestClient

from app.api.main import app


def _base_payload(city: str) -> dict[str, Any]:
    """Build a minimal request payload used by all journeys."""
    return {
        "city": city,
        "start_date": "2026-06-01",
        "end_date": "2026-06-03",
        "travel_days": 3,
        "transportation": "公共交通",
        "accommodation": "舒适型酒店",
        "preferences": ["美食", "历史文化"],
        "free_text_input": "",
    }


def _post_plan(client: TestClient, payload: dict[str, Any]) -> dict[str, Any]:
    """Call ``/api/trip/plan`` and return parsed JSON body."""
    response = client.post("/api/trip/plan", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert isinstance(body.get("data"), dict)
    return body["data"]


def _extract_visa_summary(plan: dict[str, Any]) -> dict[str, Any]:
    """Handle both flat and nested ``visa_summary`` payload shapes."""
    raw = plan.get("visa_summary")
    if not isinstance(raw, dict):
        return {}
    nested = raw.get("visa_summary")
    if isinstance(nested, dict):
        return nested
    return raw


def _collect_attraction_source_urls(plan: dict[str, Any]) -> Iterable[str]:
    """Yield all attraction ``source_url`` values from the trip plan."""
    for day in plan.get("days", []):
        if not isinstance(day, dict):
            continue
        for attraction in day.get("attractions", []):
            if not isinstance(attraction, dict):
                continue
            url = attraction.get("source_url")
            if isinstance(url, str) and url:
                yield url


def test_e2e_domestic_journey() -> None:
    """Domestic flow: returns valid itinerary and domestic visa status."""
    client = TestClient(app)
    plan = _post_plan(client, _base_payload("北京"))

    assert plan["city"] == "北京"
    assert len(plan["days"]) == 3
    assert len(plan["weather_info"]) == 3

    visa = _extract_visa_summary(plan)
    assert visa.get("is_domestic") is True
    assert visa.get("destination_country") == "CN"
    assert visa.get("visa_required") is False


def test_e2e_cross_border_journey() -> None:
    """Cross-border flow: should switch to non-domestic visa logic."""
    client = TestClient(app)
    plan = _post_plan(client, _base_payload("东京"))

    assert plan["city"] == "东京"
    assert len(plan["days"]) == 3
    assert len(plan.get("source_links", [])) >= 1

    visa = _extract_visa_summary(plan)
    assert visa.get("is_domestic") is False
    assert visa.get("destination_country") == "JP"
    assert isinstance(visa.get("source_url"), str) and visa["source_url"]


def test_e2e_rag_enhanced_journey() -> None:
    """RAG enhancement flow: itinerary should contain Wikivoyage provenance."""
    client = TestClient(app)
    payload = _base_payload("京都")
    payload["preferences"] = ["景点增强", "历史文化"]
    payload["free_text_input"] = "请结合Wikivoyage增强景点"
    plan = _post_plan(client, payload)

    assert plan["city"] == "京都"
    assert len(plan["days"]) == 3

    source_links = [url for url in plan.get("source_links", []) if isinstance(url, str)]
    attraction_links = list(_collect_attraction_source_urls(plan))
    all_links = source_links + attraction_links

    assert all_links, "RAG enhanced flow should return at least one source link"
    assert any("wikivoyage.org" in url for url in all_links)
