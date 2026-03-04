from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class AppSettings(BaseModel):
    """Runtime settings for FastAPI application metadata and bind address."""

    name: str = "Project1 Travel Planner API"
    env: str = "dev"
    host: str = "127.0.0.1"
    port: int = 8010


class PlannerSettings(BaseModel):
    """Settings for planner graph bootstrap behavior."""

    graph_name: str = "planner_bootstrap_graph"
    default_message: str = "planner graph bootstrapped"


class Settings(BaseModel):
    """Root settings model loaded from YAML with sane defaults."""

    app: AppSettings = Field(default_factory=AppSettings)
    planner: PlannerSettings = Field(default_factory=PlannerSettings)

    @classmethod
    def from_yaml(cls, path: Path) -> "Settings":
        """Build settings from a YAML file path; fallback to defaults when absent."""
        if not path.exists():
            return cls()

        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls.model_validate(data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache application settings from backend/config/settings.yaml."""
    settings_path = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"
    return Settings.from_yaml(settings_path)
