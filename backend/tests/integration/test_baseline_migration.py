"""Integration test for Phase A2 baseline migration."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import app
from app.prompts import (
    ATTRACTION_AGENT_PROMPT,
    HOTEL_AGENT_PROMPT,
    PLANNER_AGENT_PROMPT,
    WEATHER_AGENT_PROMPT,
)


def test_frontend_baseline_files_migrated() -> None:
    project_root = Path(__file__).resolve().parents[3]
    expected_files = [
        project_root / "frontend" / "package.json",
        project_root / "frontend" / "src" / "main.ts",
        project_root / "frontend" / "src" / "views" / "Home.vue",
        project_root / "frontend" / "src" / "views" / "Result.vue",
        project_root / "frontend" / "src" / "services" / "api.ts",
    ]
    for path in expected_files:
        assert path.exists(), f"missing migrated frontend file: {path}"


def test_prompt_constants_are_migrated() -> None:
    assert "景点搜索专家" in ATTRACTION_AGENT_PROMPT
    assert "天气查询专家" in WEATHER_AGENT_PROMPT
    assert "酒店推荐专家" in HOTEL_AGENT_PROMPT
    # C9: PlannerAgent role upgraded to 行程规划总指挥
    assert "行程规划总指挥" in PLANNER_AGENT_PROMPT


def test_trip_plan_route_works_without_hello_agents_runtime() -> None:
    client = TestClient(app)
    payload = {
        "city": "北京",
        "start_date": "2026-06-01",
        "end_date": "2026-06-03",
        "travel_days": 3,
        "transportation": "公共交通",
        "accommodation": "舒适型酒店",
        "preferences": ["历史文化", "美食"],
        "free_text_input": "",
    }

    response = client.post("/api/trip/plan", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert data["data"]["city"] == "北京"
    assert len(data["data"]["days"]) == 3
    assert len(data["data"]["weather_info"]) == 3


def test_backend_has_no_hello_agents_imports() -> None:
    backend_root = Path(__file__).resolve().parents[2] / "app"
    python_files = list(backend_root.rglob("*.py"))
    assert python_files
    for path in python_files:
        content = path.read_text(encoding="utf-8")
        assert "hello_agents" not in content, f"found hello_agents dependency in {path}"
