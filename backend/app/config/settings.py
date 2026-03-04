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
    cors_origins: str = (
        "http://localhost:5173,http://localhost:3000,"
        "http://127.0.0.1:5173,http://127.0.0.1:3000"
    )

    def get_cors_origins_list(self) -> list[str]:
        """Return CORS origins parsed from comma-separated settings."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


class PlannerSettings(BaseModel):
    """Settings for planner graph bootstrap behavior."""

    graph_name: str = "planner_bootstrap_graph"
    default_message: str = "planner graph bootstrapped"


class ProviderSettings(BaseModel):
    """Provider and key settings for migrated baseline services."""

    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    amap_api_key: str = ""
    unsplash_access_key: str = ""
    map_provider: str = "amap"
    map_provider_fallback: str = ""
    google_maps_api_key: str = ""
    photo_provider: str = "unsplash"
    photo_provider_fallback: str = ""
    google_places_api_key: str = ""
    flight_provider: str = "amadeus"
    flight_provider_fallback: str = ""
    amadeus_base_url: str = "https://test.api.amadeus.com"
    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""
    visa_provider: str = "sherpa"
    visa_provider_fallback: str = ""
    sherpa_base_url: str = "https://requirements-api.joinsherpa.com"
    sherpa_api_key: str = ""
    visa_api_whitelist: str = "api.joinsherpa.com,requirements-api.joinsherpa.com"


class RAGSettings(BaseModel):
    """RAG knowledge base configuration."""

    enabled: bool = False
    source: str = "wikivoyage_cn_jp"
    integration_mode: str = "external_mcp_rag"
    mcp_rag_project_root: str = ""
    index_name: str = "wikivoyage_cn_jp_attractions"


class Settings(BaseModel):
    """Root settings model loaded from YAML with sane defaults."""

    app: AppSettings = Field(default_factory=AppSettings)
    planner: PlannerSettings = Field(default_factory=PlannerSettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
    rag: RAGSettings = Field(default_factory=RAGSettings)

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
