"""Amadeus implementation of IFlightProvider.

Uses the Amadeus Self-Service ``Flight Offers Search`` API (v2).
Authentication is via OAuth2 client_credentials grant.

When credentials are empty the provider returns harmless fallback data so the
rest of the pipeline can continue.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.models.schemas import FlightOffer, FlightSegment
from app.providers.flight.base import IFlightProvider

logger = logging.getLogger(__name__)


class AmadeusFlightProvider(IFlightProvider):
    """Flight provider backed by the Amadeus Flight Offers Search API."""

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        base_url: str = "https://test.api.amadeus.com",
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None

    @property
    def provider_name(self) -> str:  # noqa: D401
        return "amadeus"

    # ------------------------------------------------------------------
    # OAuth2
    # ------------------------------------------------------------------
    def _authenticate(self) -> str:
        """Obtain or reuse an OAuth2 access token."""
        now = datetime.now(tz=timezone.utc)
        if self._access_token and self._token_expires_at and now < self._token_expires_at:
            return self._access_token

        url = f"{self._base_url}/v1/security/oauth2/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, data=data)
            resp.raise_for_status()

        body = resp.json()
        self._access_token = body["access_token"]
        expires_in = body.get("expires_in", 1799)
        self._token_expires_at = now + timedelta(seconds=expires_in - 60)
        return self._access_token

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None = None,
        adults: int = 1,
        max_results: int = 5,
    ) -> list[FlightOffer]:
        """Search Amadeus for flight offers.

        Returns fallback data when credentials are missing.
        """
        if not self._client_id or not self._client_secret:
            return self._fallback(origin, destination, departure_date, return_date)

        try:
            token = self._authenticate()
            return self._do_search(
                token, origin, destination, departure_date, return_date, adults, max_results
            )
        except Exception:
            logger.exception("Amadeus search_flights failed")
            return []

    def _do_search(
        self,
        token: str,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None,
        adults: int,
        max_results: int,
    ) -> list[FlightOffer]:
        """Execute the actual API call."""
        url = f"{self._base_url}/v2/shopping/flight-offers"
        params: dict[str, str | int] = {
            "originLocationCode": origin.upper(),
            "destinationLocationCode": destination.upper(),
            "departureDate": departure_date,
            "adults": adults,
            "max": max_results,
        }
        if return_date:
            params["returnDate"] = return_date

        headers = {"Authorization": f"Bearer {token}"}

        with httpx.Client(timeout=30) as client:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()

        data = resp.json()
        return self._parse_offers(data.get("data", []))

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_offers(raw_offers: list[dict]) -> list[FlightOffer]:
        """Convert raw Amadeus response data to ``FlightOffer`` models."""
        offers: list[FlightOffer] = []
        for raw in raw_offers:
            offer_id = raw.get("id", "")
            price_info = raw.get("price", {})
            price = float(price_info.get("grandTotal", price_info.get("total", "0")))
            currency = price_info.get("currency", "EUR")

            itineraries = raw.get("itineraries", [])
            outbound_segments: list[FlightSegment] = []
            return_segments: list[FlightSegment] = []

            for idx, itin in enumerate(itineraries):
                segments_raw = itin.get("segments", [])
                parsed = [
                    FlightSegment(
                        departure_airport=seg.get("departure", {}).get("iataCode", ""),
                        arrival_airport=seg.get("arrival", {}).get("iataCode", ""),
                        departure_time=seg.get("departure", {}).get("at", ""),
                        arrival_time=seg.get("arrival", {}).get("at", ""),
                        carrier=seg.get("carrierCode", ""),
                        flight_number=f"{seg.get('carrierCode', '')}{seg.get('number', '')}",
                        duration=seg.get("duration"),
                    )
                    for seg in segments_raw
                ]
                if idx == 0:
                    outbound_segments = parsed
                else:
                    return_segments = parsed

            # Build a search-results deep link (Amadeus has no direct booking URL)
            first_carrier = outbound_segments[0].carrier if outbound_segments else ""
            source_url = "https://www.amadeus.com"

            offers.append(
                FlightOffer(
                    id=offer_id,
                    price=price,
                    currency=currency,
                    outbound_segments=outbound_segments,
                    return_segments=return_segments,
                    booking_url=None,
                    source_url=source_url,
                    carrier_name=first_carrier,
                    total_duration=itineraries[0].get("duration") if itineraries else None,
                )
            )
        return offers

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------
    @staticmethod
    def _fallback(
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None,
    ) -> list[FlightOffer]:
        """Return a single synthetic offer when no API key is configured."""
        segments = [
            FlightSegment(
                departure_airport=origin.upper(),
                arrival_airport=destination.upper(),
                departure_time=f"{departure_date}T08:00:00",
                arrival_time=f"{departure_date}T12:00:00",
                carrier="XX",
                flight_number="XX0000",
                duration="PT4H",
            )
        ]
        ret_segments: list[FlightSegment] = []
        if return_date:
            ret_segments = [
                FlightSegment(
                    departure_airport=destination.upper(),
                    arrival_airport=origin.upper(),
                    departure_time=f"{return_date}T14:00:00",
                    arrival_time=f"{return_date}T18:00:00",
                    carrier="XX",
                    flight_number="XX0001",
                    duration="PT4H",
                )
            ]
        return [
            FlightOffer(
                id="amadeus-fallback",
                price=0.0,
                currency="CNY",
                outbound_segments=segments,
                return_segments=ret_segments,
                booking_url=None,
                source_url="https://www.amadeus.com",
                carrier_name="[amadeus-fallback]",
                total_duration="PT4H",
            )
        ]
