"""Visa source provider factory with automatic fallback wrapper.

Usage::

    provider = get_visa_provider()
    reqs = provider.get_requirements("CN", "JP", 7)

When ``settings.providers.visa_provider`` is ``"sherpa"`` (default), a
``SherpaVisaProvider`` is returned.

The ``FallbackVisaProvider`` wraps a *primary* and *secondary* provider:
if the primary call raises (excluding whitelist violations) or returns empty,
the secondary is tried.
"""

from __future__ import annotations

import logging

from app.config.settings import get_settings
from app.models.schemas import VisaRequirement
from app.providers.visa.base import IVisaSourceProvider
from app.providers.visa.sherpa_provider import SherpaVisaProvider

logger = logging.getLogger(__name__)

# ── Registry ─────────────────────────────────────────────────────────
_PROVIDER_MAP: dict[str, type[IVisaSourceProvider]] = {
    "sherpa": SherpaVisaProvider,
}


# ── Fallback wrapper ─────────────────────────────────────────────────
class FallbackVisaProvider(IVisaSourceProvider):
    """Transparent fallback: try *primary*, on failure try *secondary*.

    **Important:** ``PermissionError`` (whitelist violations) are NEVER
    swallowed — they propagate immediately.
    """

    def __init__(self, primary: IVisaSourceProvider, secondary: IVisaSourceProvider) -> None:
        self._primary = primary
        self._secondary = secondary

    @property
    def provider_name(self) -> str:  # noqa: D401
        return f"{self._primary.provider_name}+{self._secondary.provider_name}"

    def get_requirements(
        self,
        nationality: str,
        destination: str,
        travel_duration_days: int = 7,
    ) -> list[VisaRequirement]:
        """Try primary; fall back to secondary on non-security exception or empty."""
        try:
            result = self._primary.get_requirements(
                nationality, destination, travel_duration_days
            )
            if result:
                return result
        except PermissionError:
            # Whitelist violations are security errors — never swallow
            raise
        except Exception:
            logger.warning(
                "Visa provider '%s' get_requirements failed, falling back to '%s'",
                self._primary.provider_name,
                self._secondary.provider_name,
            )
        return self._secondary.get_requirements(
            nationality, destination, travel_duration_days
        )


# ── Factory ──────────────────────────────────────────────────────────
def _build_provider(name: str) -> IVisaSourceProvider:
    """Instantiate a visa provider by name using current settings."""
    settings = get_settings()
    if name == "sherpa":
        # Parse whitelist from comma-separated config string
        whitelist_raw = settings.providers.visa_api_whitelist
        allowed: list[str] | None = None
        if whitelist_raw:
            allowed = [d.strip() for d in whitelist_raw.split(",") if d.strip()]
        return SherpaVisaProvider(
            api_key=settings.providers.sherpa_api_key,
            base_url=settings.providers.sherpa_base_url,
            allowed_domains=allowed,
        )
    raise ValueError(f"Unknown visa provider: {name!r}. Available: {list(_PROVIDER_MAP)}")


_visa_provider: IVisaSourceProvider | None = None


def get_visa_provider() -> IVisaSourceProvider:
    """Return a singleton ``IVisaSourceProvider`` driven by ``settings.yaml``.

    If ``visa_provider_fallback`` is configured, the returned instance wraps
    primary+secondary in a ``FallbackVisaProvider``.
    """
    global _visa_provider
    if _visa_provider is not None:
        return _visa_provider

    settings = get_settings()
    primary_name = settings.providers.visa_provider
    fallback_name = settings.providers.visa_provider_fallback

    primary = _build_provider(primary_name)

    if fallback_name and fallback_name != primary_name:
        secondary = _build_provider(fallback_name)
        _visa_provider = FallbackVisaProvider(primary, secondary)
    else:
        _visa_provider = primary

    return _visa_provider


def reset_visa_provider() -> None:
    """Reset the singleton (useful in tests)."""
    global _visa_provider
    _visa_provider = None
