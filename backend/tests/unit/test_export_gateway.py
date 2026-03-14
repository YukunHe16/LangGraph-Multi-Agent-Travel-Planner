"""Unit tests for D4 unified export gateway."""

from __future__ import annotations

import base64

from app.agents.workers.export_agent import ExportAgent
from app.models.schemas import (
    Attraction,
    CalendarEventInput,
    CalendarEventRecord,
    DayPlan,
    Location,
    TripPlan,
)
from app.providers.calendar.base import ICalendarProvider


def _make_trip_plan() -> TripPlan:
    """Create a deterministic plan fixture for export tests."""
    return TripPlan(
        city="东京",
        start_date="2026-05-01",
        end_date="2026-05-02",
        overall_suggestions="避开高峰时段出行。",
        days=[
            DayPlan(
                date="2026-05-01",
                day_index=0,
                description="浅草寺和晴空塔",
                transportation="公共交通",
                accommodation="舒适型酒店",
                attractions=[
                    Attraction(
                        name="浅草寺",
                        address="Tokyo",
                        location=Location(longitude=139.7967, latitude=35.7148),
                        visit_duration=120,
                        description="经典地标。",
                        source_url="https://en.wikivoyage.org/wiki/Tokyo/Asakusa",
                    )
                ],
            )
        ],
    )


class _StubCalendarProvider(ICalendarProvider):
    """In-memory provider for gateway unit tests."""

    def __init__(self) -> None:
        self.received: list[CalendarEventInput] = []

    @property
    def provider_name(self) -> str:
        return "stub_calendar"

    @property
    def calendar_id(self) -> str:
        return "stub"

    def create_events(
        self,
        events: list[CalendarEventInput],
        *,
        calendar_id: str | None = None,
    ) -> list[CalendarEventRecord]:
        self.received = events
        output: list[CalendarEventRecord] = []
        for index, event in enumerate(events, start=1):
            output.append(
                CalendarEventRecord(
                    event_id=f"evt-{index}",
                    summary=event.summary,
                    start_at=event.start_at,
                    end_at=event.end_at,
                    timezone=event.timezone,
                    location=event.location,
                )
            )
        return output


def test_export_gateway_calendar_target_keeps_existing_behavior() -> None:
    """Calendar target should still create calendar events."""
    provider = _StubCalendarProvider()
    agent = ExportAgent(calendar_provider=provider)

    result = agent.run(_make_trip_plan(), target="google_calendar", timezone="Asia/Tokyo", reminder_minutes=45)

    assert result.target == "google_calendar"
    assert result.provider == "stub_calendar"
    assert result.calendar_id == "stub"
    assert result.event_count == 1
    assert len(result.events) == 1
    assert result.events[0].event_id == "evt-1"
    assert provider.received[0].reminder_minutes == [45]


def test_export_gateway_pdf_target_returns_pdf_artifact() -> None:
    """PDF target should return a base64 PDF payload via the same gateway interface."""
    agent = ExportAgent(calendar_provider=_StubCalendarProvider())

    result = agent.run(_make_trip_plan(), target="pdf")

    assert result.target == "pdf"
    assert result.event_count == 0
    assert result.events == []
    assert len(result.artifacts) == 1
    assert result.artifacts[0].mime_type == "application/pdf"
    pdf_bytes = base64.b64decode(result.artifacts[0].content_base64 or "")
    assert pdf_bytes.startswith(b"%PDF-1.")


def test_export_gateway_image_target_returns_svg_artifact() -> None:
    """Image target should return an SVG payload through unified output."""
    agent = ExportAgent(calendar_provider=_StubCalendarProvider())

    result = agent.run(_make_trip_plan(), target="image")

    assert result.target == "image"
    assert result.event_count == 0
    assert len(result.artifacts) == 1
    assert result.artifacts[0].mime_type == "image/svg+xml"
    image_bytes = base64.b64decode(result.artifacts[0].content_base64 or "")
    assert b"<svg" in image_bytes


def test_export_gateway_worker_auto_detects_pdf_target_from_user_text() -> None:
    """Worker mode should infer PDF target from export request text."""
    agent = ExportAgent(calendar_provider=_StubCalendarProvider())
    worker = agent.as_worker()

    result = worker(
        {
            "request": {"free_text_input": "请导出 PDF 给我"},
            "user_delta": "导出PDF",
            "previous_plan": _make_trip_plan().model_dump(),
        }
    )

    assert result["target"] == "pdf"
    assert result["event_count"] == 0
    assert len(result["artifacts"]) == 1
