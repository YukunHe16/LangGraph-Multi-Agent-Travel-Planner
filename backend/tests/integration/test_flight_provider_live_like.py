"""Integration tests for B3: Flight Provider abstraction & Amadeus implementation.

"Live-like" tests mock the HTTP layer to simulate real Amadeus API responses
without hitting the actual service.  Also covers:
- IFlightProvider contract compliance
- Config-driven provider selection
- FallbackFlightProvider automatic degradation
- Factory singleton + reset
- DTO validation (FlightSearchInput, FlightOffer)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models.schemas import FlightOffer, FlightSearchInput, FlightSegment
from app.providers.flight.amadeus_provider import AmadeusFlightProvider
from app.providers.flight.base import IFlightProvider
from app.providers.flight.factory import (
    FallbackFlightProvider,
    _build_provider,
    get_flight_provider,
    reset_flight_provider,
)


# ── Mock Amadeus API responses ───────────────────────────────────────

MOCK_TOKEN_RESPONSE = {
    "type": "amadeusOAuth2Token",
    "username": "test@test.com",
    "application_name": "test",
    "client_id": "test_client_id",
    "token_type": "Bearer",
    "access_token": "mock_access_token_12345",
    "expires_in": 1799,
    "state": "approved",
    "scope": "",
}

MOCK_FLIGHT_OFFERS_RESPONSE = {
    "meta": {"count": 2},
    "data": [
        {
            "type": "flight-offer",
            "id": "1",
            "source": "GDS",
            "instantTicketingRequired": False,
            "nonHomogeneous": False,
            "oneWay": False,
            "lastTicketingDate": "2026-06-01",
            "numberOfBookableSeats": 5,
            "itineraries": [
                {
                    "duration": "PT11H15M",
                    "segments": [
                        {
                            "departure": {"iataCode": "PEK", "at": "2026-06-01T08:00:00"},
                            "arrival": {"iataCode": "NRT", "at": "2026-06-01T12:15:00"},
                            "carrierCode": "CA",
                            "number": "925",
                            "duration": "PT3H15M",
                            "numberOfStops": 0,
                        }
                    ],
                },
                {
                    "duration": "PT3H30M",
                    "segments": [
                        {
                            "departure": {"iataCode": "NRT", "at": "2026-06-05T14:00:00"},
                            "arrival": {"iataCode": "PEK", "at": "2026-06-05T17:30:00"},
                            "carrierCode": "CA",
                            "number": "926",
                            "duration": "PT3H30M",
                            "numberOfStops": 0,
                        }
                    ],
                },
            ],
            "price": {
                "currency": "CNY",
                "total": "3500.00",
                "grandTotal": "3500.00",
            },
        },
        {
            "type": "flight-offer",
            "id": "2",
            "itineraries": [
                {
                    "duration": "PT4H",
                    "segments": [
                        {
                            "departure": {"iataCode": "PEK", "at": "2026-06-01T10:00:00"},
                            "arrival": {"iataCode": "NRT", "at": "2026-06-01T14:00:00"},
                            "carrierCode": "NH",
                            "number": "964",
                            "duration": "PT4H",
                            "numberOfStops": 0,
                        }
                    ],
                },
            ],
            "price": {
                "currency": "CNY",
                "total": "4200.00",
                "grandTotal": "4200.00",
            },
        },
    ],
}


# ── Helper: failing provider ─────────────────────────────────────────

class _FailingFlightProvider(IFlightProvider):
    """Always raises so we can test fallback."""

    @property
    def provider_name(self) -> str:
        return "failing"

    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None = None,
        adults: int = 1,
        max_results: int = 5,
    ) -> list[FlightOffer]:
        raise RuntimeError("boom")


# ── DTO validation ───────────────────────────────────────────────────

class TestFlightDTOs:
    """Flight DTO models validate correctly."""

    def test_flight_search_input_validates(self) -> None:
        inp = FlightSearchInput(
            origin="pek",
            destination="nrt",
            departure_date="2026-06-01",
            return_date="2026-06-05",
        )
        assert inp.origin == "PEK"
        assert inp.destination == "NRT"

    def test_flight_search_input_rejects_short_iata(self) -> None:
        with pytest.raises(Exception):
            FlightSearchInput(
                origin="PK",
                destination="NRT",
                departure_date="2026-06-01",
            )

    def test_flight_search_input_rejects_bad_date(self) -> None:
        with pytest.raises(Exception):
            FlightSearchInput(
                origin="PEK",
                destination="NRT",
                departure_date="not-a-date",
            )

    def test_flight_offer_model(self) -> None:
        offer = FlightOffer(
            id="test-1",
            price=3500.0,
            currency="CNY",
            outbound_segments=[
                FlightSegment(
                    departure_airport="PEK",
                    arrival_airport="NRT",
                    departure_time="2026-06-01T08:00:00",
                    arrival_time="2026-06-01T12:00:00",
                    carrier="CA",
                    flight_number="CA925",
                )
            ],
            source_url="https://www.amadeus.com",
        )
        assert offer.price == 3500.0
        assert len(offer.outbound_segments) == 1


# ── IFlightProvider contract ─────────────────────────────────────────

class TestAmadeusContract:
    """AmadeusFlightProvider implements IFlightProvider correctly."""

    def setup_method(self) -> None:
        self.provider = AmadeusFlightProvider(client_id="", client_secret="")

    def test_is_instance_of_interface(self) -> None:
        assert isinstance(self.provider, IFlightProvider)

    def test_provider_name(self) -> None:
        assert self.provider.provider_name == "amadeus"

    def test_search_flights_fallback_returns_list(self) -> None:
        result = self.provider.search_flights("PEK", "NRT", "2026-06-01")
        assert isinstance(result, list)
        assert len(result) >= 1
        assert isinstance(result[0], FlightOffer)

    def test_search_flights_fallback_id(self) -> None:
        result = self.provider.search_flights("PEK", "NRT", "2026-06-01")
        assert result[0].id == "amadeus-fallback"
        assert result[0].carrier_name == "[amadeus-fallback]"

    def test_search_flights_roundtrip_fallback(self) -> None:
        result = self.provider.search_flights(
            "PEK", "NRT", "2026-06-01", return_date="2026-06-05"
        )
        assert len(result[0].outbound_segments) == 1
        assert len(result[0].return_segments) == 1

    def test_search_flights_oneway_fallback(self) -> None:
        result = self.provider.search_flights("PEK", "NRT", "2026-06-01")
        assert len(result[0].return_segments) == 0


# ── Live-like: mock HTTP responses ───────────────────────────────────

class TestAmadeusLiveLike:
    """Simulate real Amadeus API interaction with mocked HTTP."""

    def setup_method(self) -> None:
        self.provider = AmadeusFlightProvider(
            client_id="test_id",
            client_secret="test_secret",
            base_url="https://test.api.amadeus.com",
        )

    def _mock_httpx_client(self) -> MagicMock:
        """Create a mock httpx.Client context manager."""
        mock_client = MagicMock()
        mock_cm = MagicMock()
        mock_cm.__enter__ = MagicMock(return_value=mock_client)
        mock_cm.__exit__ = MagicMock(return_value=False)
        return mock_cm, mock_client

    def test_full_search_flow(self) -> None:
        """Token acquisition + flight search with parsed response."""
        mock_cm, mock_client = self._mock_httpx_client()

        # First call: token, Second call: flight search
        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = MOCK_TOKEN_RESPONSE
        mock_token_resp.raise_for_status = MagicMock()

        mock_search_resp = MagicMock()
        mock_search_resp.json.return_value = MOCK_FLIGHT_OFFERS_RESPONSE
        mock_search_resp.raise_for_status = MagicMock()

        mock_client.post.return_value = mock_token_resp
        mock_client.get.return_value = mock_search_resp

        with patch("app.providers.flight.amadeus_provider.httpx.Client", return_value=mock_cm):
            results = self.provider.search_flights(
                "PEK", "NRT", "2026-06-01", return_date="2026-06-05"
            )

        assert len(results) == 2

        # First offer: round-trip CA
        offer1 = results[0]
        assert offer1.id == "1"
        assert offer1.price == 3500.0
        assert offer1.currency == "CNY"
        assert len(offer1.outbound_segments) == 1
        assert offer1.outbound_segments[0].carrier == "CA"
        assert offer1.outbound_segments[0].flight_number == "CA925"
        assert offer1.outbound_segments[0].departure_airport == "PEK"
        assert offer1.outbound_segments[0].arrival_airport == "NRT"
        assert len(offer1.return_segments) == 1
        assert offer1.return_segments[0].flight_number == "CA926"

        # Second offer: one-way NH
        offer2 = results[1]
        assert offer2.id == "2"
        assert offer2.price == 4200.0
        assert len(offer2.outbound_segments) == 1
        assert offer2.outbound_segments[0].carrier == "NH"
        assert len(offer2.return_segments) == 0

    def test_search_returns_empty_on_api_error(self) -> None:
        """API failure returns empty list, not exception."""
        mock_cm, mock_client = self._mock_httpx_client()

        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = MOCK_TOKEN_RESPONSE
        mock_token_resp.raise_for_status = MagicMock()

        mock_client.post.return_value = mock_token_resp
        mock_client.get.side_effect = Exception("Network error")

        with patch("app.providers.flight.amadeus_provider.httpx.Client", return_value=mock_cm):
            results = self.provider.search_flights("PEK", "NRT", "2026-06-01")

        assert results == []

    def test_token_caching(self) -> None:
        """Token is reused across multiple searches (not re-acquired)."""
        mock_cm, mock_client = self._mock_httpx_client()

        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = MOCK_TOKEN_RESPONSE
        mock_token_resp.raise_for_status = MagicMock()

        mock_search_resp = MagicMock()
        mock_search_resp.json.return_value = {"data": []}
        mock_search_resp.raise_for_status = MagicMock()

        mock_client.post.return_value = mock_token_resp
        mock_client.get.return_value = mock_search_resp

        with patch("app.providers.flight.amadeus_provider.httpx.Client", return_value=mock_cm):
            self.provider.search_flights("PEK", "NRT", "2026-06-01")
            self.provider.search_flights("PEK", "HND", "2026-06-02")

        # post is called only once (for token) across two searches
        assert mock_client.post.call_count == 1

    def test_source_url_present(self) -> None:
        """Every offer has a source_url for traceability."""
        mock_cm, mock_client = self._mock_httpx_client()

        mock_token_resp = MagicMock()
        mock_token_resp.json.return_value = MOCK_TOKEN_RESPONSE
        mock_token_resp.raise_for_status = MagicMock()

        mock_search_resp = MagicMock()
        mock_search_resp.json.return_value = MOCK_FLIGHT_OFFERS_RESPONSE
        mock_search_resp.raise_for_status = MagicMock()

        mock_client.post.return_value = mock_token_resp
        mock_client.get.return_value = mock_search_resp

        with patch("app.providers.flight.amadeus_provider.httpx.Client", return_value=mock_cm):
            results = self.provider.search_flights("PEK", "NRT", "2026-06-01")

        for offer in results:
            assert offer.source_url is not None


# ── Fallback ─────────────────────────────────────────────────────────

class TestFlightFallback:
    """FallbackFlightProvider degrades gracefully when primary fails."""

    def setup_method(self) -> None:
        self.failing = _FailingFlightProvider()
        self.good = AmadeusFlightProvider(client_id="", client_secret="")
        self.fb = FallbackFlightProvider(primary=self.failing, secondary=self.good)

    def test_provider_name_composite(self) -> None:
        assert self.fb.provider_name == "failing+amadeus"

    def test_search_flights_falls_back(self) -> None:
        result = self.fb.search_flights("PEK", "NRT", "2026-06-01")
        assert len(result) >= 1
        assert isinstance(result[0], FlightOffer)


# ── Config-driven factory ────────────────────────────────────────────

class TestFlightFactory:
    """Factory builds provider from settings without code changes."""

    def teardown_method(self) -> None:
        reset_flight_provider()

    def test_default_provider_is_amadeus(self) -> None:
        provider = get_flight_provider()
        assert "amadeus" in provider.provider_name

    def test_config_switch_raises_for_unknown(self) -> None:
        """Unknown provider raises ValueError."""
        from app.config.settings import ProviderSettings, Settings

        mock_settings = Settings(
            providers=ProviderSettings(flight_provider="unknown_xyz"),
        )
        with patch("app.providers.flight.factory.get_settings", return_value=mock_settings):
            reset_flight_provider()
            with pytest.raises(ValueError, match="Unknown flight provider"):
                get_flight_provider()

    def test_reset_clears_singleton(self) -> None:
        """reset_flight_provider allows re-creation with new settings."""
        p1 = get_flight_provider()
        reset_flight_provider()
        p2 = get_flight_provider()
        assert p1 is not p2
