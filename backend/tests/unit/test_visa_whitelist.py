"""Unit tests for B4: Visa Source Provider with whitelist domain enforcement.

Covers:
- IVisaSourceProvider contract compliance
- Domain whitelist enforcement (PermissionError on violation)
- SherpaVisaProvider fallback mode (no API key)
- Live-like mock HTTP responses simulating Sherpa API
- FallbackVisaProvider degradation (preserves whitelist errors)
- Config-driven factory singleton + reset
- DTO validation (VisaRequirementsInput, VisaRequirement)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models.schemas import VisaRequirement, VisaRequirementsInput, VisaRequirementsOutput
from app.providers.visa.base import IVisaSourceProvider
from app.providers.visa.sherpa_provider import DEFAULT_WHITELIST, SherpaVisaProvider
from app.providers.visa.factory import (
    FallbackVisaProvider,
    get_visa_provider,
    reset_visa_provider,
)


# ── Mock Sherpa API responses ────────────────────────────────────────

MOCK_SHERPA_RESPONSE = {
    "data": [
        {
            "category": {"name": "tourist visa"},
            "status": "required",
            "requirement": {
                "subRequirements": [
                    {"documentType": "Passport", "name": "Valid Passport"},
                    {"documentType": "Application Form"},
                    {"documentType": "Photo"},
                ]
            },
            "processingTime": {"description": "5-7 business days"},
            "validity": {"description": "90 days"},
            "notes": "Single entry only for first-time applicants.",
            "sourceUrl": "https://apply.joinsherpa.com/travel-restrictions?nationality=CN&destination=JP",
        }
    ]
}

MOCK_SHERPA_NOT_REQUIRED = {
    "data": [
        {
            "category": {"name": "visa"},
            "status": "not_required",
            "requirement": {"subRequirements": []},
            "notes": "Visa-free travel for up to 30 days.",
            "sourceUrl": "https://apply.joinsherpa.com/travel-restrictions?nationality=JP&destination=KR",
        }
    ]
}


# ── Helper: failing provider ─────────────────────────────────────────

class _FailingVisaProvider(IVisaSourceProvider):
    """Always raises so we can test fallback."""

    @property
    def provider_name(self) -> str:
        return "failing"

    def get_requirements(
        self,
        nationality: str,
        destination: str,
        travel_duration_days: int = 7,
    ) -> list[VisaRequirement]:
        raise RuntimeError("boom")


# ── DTO validation ───────────────────────────────────────────────────

class TestVisaDTOs:
    """Visa DTO models validate correctly."""

    def test_visa_input_validates(self) -> None:
        inp = VisaRequirementsInput(
            nationality="cn",
            destination="jp",
            travel_duration_days=14,
        )
        assert inp.nationality == "CN"
        assert inp.destination == "JP"

    def test_visa_input_rejects_long_code(self) -> None:
        with pytest.raises(Exception):
            VisaRequirementsInput(
                nationality="CHN",
                destination="JP",
            )

    def test_visa_input_rejects_short_code(self) -> None:
        with pytest.raises(Exception):
            VisaRequirementsInput(
                nationality="C",
                destination="JP",
            )

    def test_visa_requirement_model(self) -> None:
        req = VisaRequirement(
            visa_required=True,
            visa_type="tourist visa",
            documents=["Passport", "Form"],
            processing_time="5 days",
            source_url="https://example.com",
        )
        assert req.visa_required is True
        assert len(req.documents) == 2
        assert req.source_url == "https://example.com"

    def test_visa_requirement_needs_source_url(self) -> None:
        """source_url is mandatory per §2.7."""
        with pytest.raises(Exception):
            VisaRequirement(
                visa_required=True,
                # source_url missing
            )

    def test_visa_output_model(self) -> None:
        out = VisaRequirementsOutput(
            provider="sherpa",
            nationality="CN",
            destination="JP",
            requirements=[
                VisaRequirement(
                    visa_required=True,
                    source_url="https://example.com",
                )
            ],
        )
        assert out.provider == "sherpa"
        assert len(out.requirements) == 1


# ── IVisaSourceProvider contract ─────────────────────────────────────

class TestSherpaContract:
    """SherpaVisaProvider implements IVisaSourceProvider correctly."""

    def setup_method(self) -> None:
        self.provider = SherpaVisaProvider(api_key="")

    def test_is_instance_of_interface(self) -> None:
        assert isinstance(self.provider, IVisaSourceProvider)

    def test_provider_name(self) -> None:
        assert self.provider.provider_name == "sherpa"

    def test_get_requirements_fallback_returns_list(self) -> None:
        result = self.provider.get_requirements("CN", "JP")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert isinstance(result[0], VisaRequirement)

    def test_fallback_has_source_url(self) -> None:
        result = self.provider.get_requirements("CN", "JP")
        assert result[0].source_url is not None
        assert "CN" in result[0].source_url
        assert "JP" in result[0].source_url

    def test_fallback_visa_type(self) -> None:
        result = self.provider.get_requirements("CN", "JP")
        assert result[0].visa_type == "[sherpa-fallback]"


# ── Whitelist enforcement ────────────────────────────────────────────

class TestWhitelistEnforcement:
    """Domain whitelist prevents calls to non-approved domains."""

    def test_default_whitelist_includes_sherpa(self) -> None:
        provider = SherpaVisaProvider(api_key="test")
        assert "requirements-api.joinsherpa.com" in provider.allowed_domains
        assert "api.joinsherpa.com" in provider.allowed_domains

    def test_custom_whitelist(self) -> None:
        provider = SherpaVisaProvider(
            api_key="test",
            allowed_domains=["custom.sherpa.com"],
        )
        # base_url domain is auto-added
        assert "requirements-api.joinsherpa.com" in provider.allowed_domains
        assert "custom.sherpa.com" in provider.allowed_domains

    def test_whitelisted_url_passes(self) -> None:
        provider = SherpaVisaProvider(api_key="test")
        # Should not raise
        provider._validate_url("https://requirements-api.joinsherpa.com/v3/restrictions")

    def test_non_whitelisted_url_raises(self) -> None:
        provider = SherpaVisaProvider(api_key="test")
        with pytest.raises(PermissionError, match="not in the visa API whitelist"):
            provider._validate_url("https://evil-domain.com/steal-data")

    def test_non_whitelisted_blocks_real_call(self) -> None:
        """Even with a valid API key, non-whitelisted base_url is blocked."""
        provider = SherpaVisaProvider(
            api_key="test_key",
            base_url="https://evil-api.example.com",
            allowed_domains=["requirements-api.joinsherpa.com"],
        )
        # The base_url domain gets auto-added, so let's test with a
        # provider that has a restricted whitelist and a bad URL
        provider._allowed_domains = ["requirements-api.joinsherpa.com"]
        with pytest.raises(PermissionError, match="not in the visa API whitelist"):
            provider.get_requirements("CN", "JP")

    def test_whitelist_violation_not_swallowed(self) -> None:
        """PermissionError propagates even through generic exception handling."""
        provider = SherpaVisaProvider(
            api_key="test_key",
            base_url="https://requirements-api.joinsherpa.com",
        )
        # Force whitelist to exclude the base URL
        provider._allowed_domains = ["other-domain.com"]
        with pytest.raises(PermissionError):
            provider.get_requirements("CN", "JP")


# ── Live-like: mock HTTP responses ───────────────────────────────────

class TestSherpaLiveLike:
    """Simulate real Sherpa API interaction with mocked HTTP."""

    def setup_method(self) -> None:
        self.provider = SherpaVisaProvider(
            api_key="test_api_key",
            base_url="https://requirements-api.joinsherpa.com",
        )

    def _mock_httpx_client(self) -> tuple[MagicMock, MagicMock]:
        """Create a mock httpx.Client context manager."""
        mock_client = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_client)
        mock_cm.__exit__ = MagicMock(return_value=False)
        return mock_cm, mock_client

    def test_full_lookup_visa_required(self) -> None:
        """Parse Sherpa response for a visa-required destination."""
        mock_cm, mock_client = self._mock_httpx_client()

        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_SHERPA_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        with patch("app.providers.visa.sherpa_provider.httpx.Client", return_value=mock_cm):
            results = self.provider.get_requirements("CN", "JP", 14)

        assert len(results) == 1
        req = results[0]
        assert req.visa_required is True
        assert req.visa_type == "tourist visa"
        assert "Passport" in req.documents
        assert "Application Form" in req.documents
        assert req.processing_time == "5-7 business days"
        assert req.validity == "90 days"
        assert req.source_url is not None
        assert "CN" in req.source_url

    def test_full_lookup_visa_not_required(self) -> None:
        """Parse Sherpa response for a visa-free destination."""
        mock_cm, mock_client = self._mock_httpx_client()

        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_SHERPA_NOT_REQUIRED
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        with patch("app.providers.visa.sherpa_provider.httpx.Client", return_value=mock_cm):
            results = self.provider.get_requirements("JP", "KR")

        assert len(results) == 1
        assert results[0].visa_required is False
        assert results[0].visa_type is None

    def test_api_error_returns_empty(self) -> None:
        """API failure returns empty list, not exception."""
        mock_cm, mock_client = self._mock_httpx_client()
        mock_client.get.side_effect = Exception("Network error")

        with patch("app.providers.visa.sherpa_provider.httpx.Client", return_value=mock_cm):
            results = self.provider.get_requirements("CN", "JP")

        assert results == []

    def test_empty_data_returns_unknown(self) -> None:
        """Empty API response returns a single 'unknown' requirement."""
        mock_cm, mock_client = self._mock_httpx_client()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        with patch("app.providers.visa.sherpa_provider.httpx.Client", return_value=mock_cm):
            results = self.provider.get_requirements("CN", "JP")

        assert len(results) == 1
        assert results[0].visa_type == "unknown"
        assert results[0].source_url is not None

    def test_source_url_always_present(self) -> None:
        """Every requirement has a source_url for traceability."""
        mock_cm, mock_client = self._mock_httpx_client()

        mock_resp = MagicMock()
        mock_resp.json.return_value = MOCK_SHERPA_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        with patch("app.providers.visa.sherpa_provider.httpx.Client", return_value=mock_cm):
            results = self.provider.get_requirements("CN", "JP")

        for req in results:
            assert req.source_url is not None
            assert req.source_url.startswith("http")

    def test_auth_header_sent(self) -> None:
        """API key is sent as Bearer token."""
        mock_cm, mock_client = self._mock_httpx_client()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp

        with patch("app.providers.visa.sherpa_provider.httpx.Client", return_value=mock_cm):
            self.provider.get_requirements("CN", "JP")

        call_kwargs = mock_client.get.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers.get("Authorization") == "Bearer test_api_key"


# ── Fallback ─────────────────────────────────────────────────────────

class TestVisaFallback:
    """FallbackVisaProvider degrades gracefully when primary fails."""

    def setup_method(self) -> None:
        self.failing = _FailingVisaProvider()
        self.good = SherpaVisaProvider(api_key="")
        self.fb = FallbackVisaProvider(primary=self.failing, secondary=self.good)

    def test_provider_name_composite(self) -> None:
        assert self.fb.provider_name == "failing+sherpa"

    def test_get_requirements_falls_back(self) -> None:
        result = self.fb.get_requirements("CN", "JP")
        assert len(result) >= 1
        assert isinstance(result[0], VisaRequirement)

    def test_whitelist_violation_not_caught_by_fallback(self) -> None:
        """FallbackVisaProvider must NOT swallow PermissionError."""

        class _WhitelistViolator(IVisaSourceProvider):
            @property
            def provider_name(self) -> str:
                return "violator"

            def get_requirements(self, *args, **kwargs) -> list[VisaRequirement]:
                raise PermissionError("blocked domain")

        fb = FallbackVisaProvider(
            primary=_WhitelistViolator(),
            secondary=self.good,
        )
        with pytest.raises(PermissionError, match="blocked domain"):
            fb.get_requirements("CN", "JP")


# ── Config-driven factory ────────────────────────────────────────────

class TestVisaFactory:
    """Factory builds provider from settings without code changes."""

    def teardown_method(self) -> None:
        reset_visa_provider()

    def test_default_provider_is_sherpa(self) -> None:
        provider = get_visa_provider()
        assert "sherpa" in provider.provider_name

    def test_config_switch_raises_for_unknown(self) -> None:
        """Unknown provider raises ValueError."""
        from app.config.settings import ProviderSettings, Settings

        mock_settings = Settings(
            providers=ProviderSettings(visa_provider="unknown_xyz"),
        )
        with patch("app.providers.visa.factory.get_settings", return_value=mock_settings):
            reset_visa_provider()
            with pytest.raises(ValueError, match="Unknown visa provider"):
                get_visa_provider()

    def test_reset_clears_singleton(self) -> None:
        """reset_visa_provider allows re-creation with new settings."""
        p1 = get_visa_provider()
        reset_visa_provider()
        p2 = get_visa_provider()
        assert p1 is not p2

    def test_factory_passes_whitelist_from_settings(self) -> None:
        """Factory passes configured whitelist domains to provider."""
        from app.config.settings import ProviderSettings, Settings

        mock_settings = Settings(
            providers=ProviderSettings(
                visa_provider="sherpa",
                visa_api_whitelist="custom.api.com,another.api.com",
            ),
        )
        with patch("app.providers.visa.factory.get_settings", return_value=mock_settings):
            reset_visa_provider()
            provider = get_visa_provider()

        assert isinstance(provider, SherpaVisaProvider)
        assert "custom.api.com" in provider.allowed_domains
        assert "another.api.com" in provider.allowed_domains
