from __future__ import annotations

from fastapi import FastAPI
from pydantic import BaseModel

from app.agents.planner.planner_graph import build_planner_graph
from app.config.settings import get_settings

settings = get_settings()
app = FastAPI(title=settings.app.name)


class GraphBootstrapRequest(BaseModel):
    """Request payload for graph bootstrap endpoint."""

    user_input: str = ""


@app.get("/api/health")
def health() -> dict[str, str]:
    """Health endpoint for backend startup verification."""
    return {
        "status": "ok",
        "app": settings.app.name,
        "env": settings.app.env,
    }


@app.post("/api/graph/bootstrap")
def graph_bootstrap(payload: GraphBootstrapRequest) -> dict[str, dict[str, str]]:
    """Run minimal planner graph invoke flow and return resulting message."""
    graph = build_planner_graph()
    result = graph.invoke({"user_input": payload.user_input})
    return {"result": result}
