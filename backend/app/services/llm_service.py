"""LLM service abstraction for LangChain migration baseline.

A2 keeps runtime independent from hello-agents. Actual model invocation will be
expanded in later tasks; this module provides a stable entry point.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import get_settings


@dataclass
class LLMService:
    """Minimal LLM service metadata holder used during migration stage."""

    provider: str
    model: str

    def generate(self, prompt: str) -> str:
        """Return a deterministic placeholder response for baseline stage."""
        _ = prompt
        return "LLM service placeholder response"


_llm_service: LLMService | None = None


def get_llm_service() -> LLMService:
    """Get singleton LLM service."""
    global _llm_service
    if _llm_service is None:
        settings = get_settings()
        _llm_service = LLMService(
            provider=settings.providers.llm_provider,
            model=settings.providers.llm_model,
        )
    return _llm_service
