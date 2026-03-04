from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.agents.planner.planner_graph import build_planner_graph
from app.api.routes import map as map_routes
from app.api.routes import poi, trip
from app.config.settings import get_settings

settings = get_settings()
app = FastAPI(title=settings.app.name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.app.get_cors_origins_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trip.router, prefix="/api")
app.include_router(poi.router, prefix="/api")
app.include_router(map_routes.router, prefix="/api")


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


@app.get("/")
def root() -> dict[str, str]:
    """Root endpoint with runtime metadata."""
    return {
        "name": settings.app.name,
        "status": "running",
        "docs": "/docs",
    }


@app.post("/api/graph/bootstrap")
def graph_bootstrap(payload: GraphBootstrapRequest) -> dict[str, dict[str, str]]:
    """Run minimal planner graph invoke flow and return resulting message."""
    graph = build_planner_graph()
    result = graph.invoke({"user_input": payload.user_input})
    return {"result": result}
