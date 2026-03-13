from __future__ import annotations

import os
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


class MemorySettings(BaseModel):
    """Short-term conversation memory configuration (§3.6)."""

    enabled: bool = True
    max_tokens: int = 3000
    summary_trigger_tokens: int = 2600
    summary_max_tokens: int = 700
    k_recent_turns: int = 8
    summary_model: str = ""


class Settings(BaseModel):
    """Root settings model loaded from YAML with sane defaults."""

    app: AppSettings = Field(default_factory=AppSettings)
    planner: PlannerSettings = Field(default_factory=PlannerSettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
    rag: RAGSettings = Field(default_factory=RAGSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)

    @classmethod
    def from_yaml(cls, path: Path) -> "Settings":
        """Build settings from a YAML file path; fallback to defaults when absent."""
        if not path.exists():
            return cls()

        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        return cls.model_validate(data)


def _load_dotenv() -> None:
    """Load .env file from backend/ root into os.environ (best-effort)."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    with env_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            os.environ.setdefault(key, value)


def _overlay_env(settings: Settings) -> Settings:
    """Overlay environment variables onto settings (API keys only)."""
    env_map = {
        "AMAP_API_KEY": "amap_api_key",
        "UNSPLASH_ACCESS_KEY": "unsplash_access_key",
        "GOOGLE_MAPS_API_KEY": "google_maps_api_key",
        "GOOGLE_PLACES_API_KEY": "google_places_api_key",
        "AMADEUS_CLIENT_ID": "amadeus_client_id",
        "AMADEUS_CLIENT_SECRET": "amadeus_client_secret",
        "SHERPA_API_KEY": "sherpa_api_key",
    }
    for env_var, attr in env_map.items():
        val = os.environ.get(env_var, "")
        if val and not getattr(settings.providers, attr, ""):
            setattr(settings.providers, attr, val)
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache application settings from backend/config/settings.yaml.

    Also loads ``backend/.env`` into ``os.environ`` and overlays API keys
    onto provider settings when they are not already set in the YAML.
    """
    _load_dotenv()
    settings_path = Path(__file__).resolve().parents[2] / "config" / "settings.yaml"
    settings = Settings.from_yaml(settings_path)
    return _overlay_env(settings)
