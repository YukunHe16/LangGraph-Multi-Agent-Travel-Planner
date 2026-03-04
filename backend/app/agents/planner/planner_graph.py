from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.config.settings import get_settings


class PlannerState(TypedDict, total=False):
    """Minimal state contract for the bootstrap planner graph."""

    user_input: str
    message: str


def _bootstrap_node(state: PlannerState) -> PlannerState:
    """Return user message or configured default for graph bootstrap validation."""
    settings = get_settings()
    user_input = (state.get("user_input") or "").strip()
    message = user_input or settings.planner.default_message
    return {"message": message}


def build_planner_graph():
    """Build and compile the minimal LangGraph used by A1 bootstrap tests."""
    graph_builder = StateGraph(PlannerState)
    graph_builder.add_node("bootstrap", _bootstrap_node)
    graph_builder.add_edge(START, "bootstrap")
    graph_builder.add_edge("bootstrap", END)
    return graph_builder.compile()
