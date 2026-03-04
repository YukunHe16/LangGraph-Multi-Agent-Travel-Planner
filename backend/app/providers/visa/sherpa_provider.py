"""Sherpa implementation of IVisaSourceProvider.

Uses the Sherpa ``Requirements API`` to look up visa requirements.
Enforces a **domain whitelist** — only requests to configured allowed
domains are permitted.  Any attempt to call a non-whitelisted domain
raises ``PermissionError``.

When credentials are empty the provider returns harmless fallback data
so the rest of the pipeline can continue.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from app.models.schemas import VisaRequirement
from app.providers.visa.base import IVisaSourceProvider

logger = logging.getLogger(__name__)

# ── Default whitelist ────────────────────────────────────────────────
DEFAULT_WHITELIST: list[str] = [
    "api.joinsherpa.com",
    "requirements-api.joinsherpa.com",
]


class SherpaVisaProvider(IVisaSourceProvider):
    """Visa provider backed by the Sherpa Requirements API.

    Enforces domain whitelisting: every outbound HTTP request is validated
    against ``allowed_domains`` before execution.  If the resolved URL
    host is not in the whitelist, a ``PermissionError`` is raised.
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "https://requirements-api.joinsherpa.com",
        allowed_domains: list[str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._allowed_domains: list[str] = allowed_domains or list(DEFAULT_WHITELIST)
        # Ensure the configured base_url domain is in the whitelist
        base_host = urlparse(self._base_url).hostname or ""
        if base_host and base_host not in self._allowed_domains:
            self._allowed_domains.append(base_host)

    @property
    def provider_name(self) -> str:  # noqa: D401
        return "sherpa"

    @property
    def allowed_domains(self) -> list[str]:
        """Return the current domain whitelist (read-only copy)."""
        return list(self._allowed_domains)

    # ------------------------------------------------------------------
    # Whitelist enforcement
    # ------------------------------------------------------------------
    def _validate_url(self, url: str) -> None:
        """Raise ``PermissionError`` if *url* host is not whitelisted."""
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host not in self._allowed_domains:
            raise PermissionError(
                f"Domain '{host}' is not in the visa API whitelist. "
                f"Allowed: {self._allowed_domains}"
            )

    # ------------------------------------------------------------------
    # Requirements lookup
    # ------------------------------------------------------------------
    def get_requirements(
        self,
        nationality: str,
        destination: str,
        travel_duration_days: int = 7,
    ) -> list[VisaRequirement]:
        """Query Sherpa for visa requirements.

        Returns fallback data when API key is missing.
        """
        if not self._api_key:
            return self._fallback(nationality, destination)

        try:
            return self._do_lookup(nationality.upper(), destination.upper(), travel_duration_days)
        except PermissionError:
            # Re-raise whitelist violations — these are security errors
            raise
        except Exception:
            logger.exception("Sherpa get_requirements failed")
            return []

    def _do_lookup(
        self,
        nationality: str,
        destination: str,
        travel_duration_days: int,
    ) -> list[VisaRequirement]:
        """Execute the actual Sherpa API call."""
        url = f"{self._base_url}/v3/restrictions"
        self._validate_url(url)

        params: dict[str, str | int] = {
            "nationality": nationality,
            "destination": destination,
            "travelDuration": travel_duration_days,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }

        with httpx.Client(timeout=15) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        return self._parse_requirements(data, nationality, destination)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_requirements(
        raw: dict,
        nationality: str,
        destination: str,
    ) -> list[VisaRequirement]:
        """Convert raw Sherpa response to ``VisaRequirement`` models."""
        requirements: list[VisaRequirement] = []

        # Sherpa v3 returns data under "data" key with restriction entries
        entries = raw.get("data", [])
        if isinstance(entries, dict):
            entries = [entries]

        for entry in entries:
            category = entry.get("category", {})
            visa_type = category.get("name", "visa")

            # Extract requirement details
            requirement_data = entry.get("requirement", {})
            sub_requirements = requirement_data.get("subRequirements", [])
            documents = [
                sr.get("documentType", sr.get("name", "Unknown"))
                for sr in sub_requirements
                if sr.get("documentType") or sr.get("name")
            ]

            # Processing info
            processing_time = entry.get("processingTime", {}).get("description")
            validity = entry.get("validity", {}).get("description")
            notes = entry.get("notes")

            # Determine if visa is required
            status = entry.get("status", "").lower()
            visa_required = status not in ("not_required", "not required", "exempt")

            # Source URL — Sherpa docs or constructed deep link
            source_url = entry.get("sourceUrl") or (
                f"https://apply.joinsherpa.com/travel-restrictions"
                f"?nationality={nationality}&destination={destination}"
            )

            requirements.append(
                VisaRequirement(
                    visa_required=visa_required,
                    visa_type=visa_type if visa_required else None,
                    documents=documents,
                    processing_time=processing_time,
                    validity=validity,
                    notes=notes,
                    source_url=source_url,
                )
            )

        # If no entries parsed, return a single "unknown" requirement
        if not requirements:
            requirements.append(
                VisaRequirement(
                    visa_required=True,
                    visa_type="unknown",
                    documents=[],
                    processing_time=None,
                    validity=None,
                    notes="No data returned from Sherpa API; please check manually.",
                    source_url=(
                        f"https://apply.joinsherpa.com/travel-restrictions"
                        f"?nationality={nationality}&destination={destination}"
                    ),
                )
            )

        return requirements

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------
    @staticmethod
    def _fallback(nationality: str, destination: str) -> list[VisaRequirement]:
        """Return a single synthetic requirement when no API key is configured."""
        return [
            VisaRequirement(
                visa_required=True,
                visa_type="[sherpa-fallback]",
                documents=["Passport", "Application Form"],
                processing_time="See official source",
                validity="See official source",
                notes=(
                    "[Fallback] No Sherpa API key configured. "
                    "Please consult official visa resources."
                ),
                source_url=(
                    f"https://apply.joinsherpa.com/travel-restrictions"
                    f"?nationality={nationality.upper()}&destination={destination.upper()}"
                ),
            )
        ]
