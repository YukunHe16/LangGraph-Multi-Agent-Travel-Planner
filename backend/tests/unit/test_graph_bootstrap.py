from fastapi.testclient import TestClient

from app.agents.planner.planner_graph import build_planner_graph
from app.api.main import app
from app.config.settings import get_settings


def test_graph_bootstrap_default_message() -> None:
    graph = build_planner_graph()
    result = graph.invoke({"user_input": ""})

    assert result["message"] == get_settings().planner.default_message


def test_graph_bootstrap_user_message() -> None:
    graph = build_planner_graph()
    result = graph.invoke({"user_input": "hello graph"})

    assert result["message"] == "hello graph"


def test_health_endpoint() -> None:
    client = TestClient(app)
    resp = client.get("/api/health")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"


def test_graph_bootstrap_endpoint() -> None:
    client = TestClient(app)
    resp = client.post("/api/graph/bootstrap", json={"user_input": "from-api"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["result"]["message"] == "from-api"
