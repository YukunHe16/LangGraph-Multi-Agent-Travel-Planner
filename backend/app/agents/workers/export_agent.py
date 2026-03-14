"""ExportAgent — unified export gateway for calendar/pdf/image targets."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta
from html import escape
from typing import TYPE_CHECKING, Callable

from app.config.settings import get_settings
from app.models.schemas import (
    CalendarEventInput,
    CalendarExportOutput,
    ExportArtifact,
    ExportTarget,
    TripPlan,
)

if TYPE_CHECKING:
    from app.providers.calendar.base import ICalendarProvider
    from app.providers.registry import ProviderRegistry

_DEFAULT_START_HOUR = 9
_DEFAULT_TRANSIT_BUFFER_MINUTES = 30
_FALLBACK_PROVIDER_NAME = "export_gateway"


class ExportAgent:
    """Export a generated ``TripPlan`` to calendar, PDF, or image."""

    def __init__(
        self,
        registry: "ProviderRegistry | None" = None,
        calendar_provider: "ICalendarProvider | None" = None,
    ) -> None:
        self._registry = registry
        self._calendar_provider = calendar_provider

    @property
    def _calendar(self) -> "ICalendarProvider":
        """Lazy-resolve the calendar provider."""
        if self._calendar_provider is not None:
            return self._calendar_provider
        if self._registry is None:
            from app.providers.registry import get_provider_registry

            self._registry = get_provider_registry()
        self._calendar_provider = self._registry.calendar
        return self._calendar_provider

    def run(
        self,
        trip_plan: TripPlan,
        *,
        target: ExportTarget = "google_calendar",
        timezone: str | None = None,
        reminder_minutes: int | None = None,
    ) -> CalendarExportOutput:
        """Export a trip plan via a unified target selector."""
        if target == "pdf":
            return self._run_pdf_export(trip_plan)
        if target == "image":
            return self._run_image_export(trip_plan)

        settings = get_settings()
        tz = timezone or settings.providers.google_calendar_timezone
        reminder = reminder_minutes or settings.providers.google_calendar_reminder_minutes

        events = self._build_calendar_events(trip_plan, timezone=tz, reminder_minutes=reminder)
        created = self._calendar.create_events(events)
        warnings: list[str] = []
        if events and not created:
            warnings.append("Google Calendar provider returned no created events.")

        return CalendarExportOutput(
            provider=self._calendar.provider_name,
            target="google_calendar",
            calendar_id=self._calendar.calendar_id,
            event_count=len(created),
            events=created,
            warnings=warnings,
        )

    def _run_pdf_export(self, trip_plan: TripPlan) -> CalendarExportOutput:
        """Build a lightweight PDF artifact and wrap it in unified output."""
        summary = self._build_text_summary(trip_plan)
        artifact = ExportArtifact(
            kind="file",
            filename=f"trip_plan_{trip_plan.city}_export.pdf",
            mime_type="application/pdf",
            content_base64=base64.b64encode(self._build_minimal_pdf(summary)).decode("ascii"),
        )
        return CalendarExportOutput(
            provider=_FALLBACK_PROVIDER_NAME,
            target="pdf",
            calendar_id="n/a",
            event_count=0,
            events=[],
            artifacts=[artifact],
        )

    def _run_image_export(self, trip_plan: TripPlan) -> CalendarExportOutput:
        """Build an SVG itinerary poster as the image export artifact."""
        svg_payload = self._build_svg_summary(trip_plan).encode("utf-8")
        artifact = ExportArtifact(
            kind="file",
            filename=f"trip_plan_{trip_plan.city}_export.svg",
            mime_type="image/svg+xml",
            content_base64=base64.b64encode(svg_payload).decode("ascii"),
        )
        return CalendarExportOutput(
            provider=_FALLBACK_PROVIDER_NAME,
            target="image",
            calendar_id="n/a",
            event_count=0,
            events=[],
            artifacts=[artifact],
        )

    def _build_calendar_events(
        self,
        trip_plan: TripPlan,
        *,
        timezone: str,
        reminder_minutes: int,
    ) -> list[CalendarEventInput]:
        """Map a trip plan into sequential calendar events."""
        events: list[CalendarEventInput] = []

        for day in trip_plan.days:
            cursor = datetime.fromisoformat(f"{day.date}T{_DEFAULT_START_HOUR:02d}:00:00")
            if not day.attractions:
                end_at = cursor + timedelta(hours=9)
                events.append(
                    CalendarEventInput(
                        summary=f"第{day.day_index + 1}天 · 行程概览",
                        description=day.description,
                        start_at=cursor.isoformat(),
                        end_at=end_at.isoformat(),
                        timezone=timezone,
                        location=day.hotel.address if day.hotel else day.accommodation,
                        reminder_minutes=[reminder_minutes],
                        source_url=day.hotel.source_url if day.hotel else None,
                    )
                )
                continue

            for attraction in day.attractions:
                duration = max(30, int(attraction.visit_duration or 0))
                end_at = cursor + timedelta(minutes=duration)
                description = self._build_event_description(day.description, attraction.description, attraction)
                events.append(
                    CalendarEventInput(
                        summary=f"第{day.day_index + 1}天 · {attraction.name}",
                        description=description,
                        start_at=cursor.isoformat(),
                        end_at=end_at.isoformat(),
                        timezone=timezone,
                        location=attraction.address,
                        latitude=attraction.location.latitude,
                        longitude=attraction.location.longitude,
                        reminder_minutes=[reminder_minutes],
                        source_url=attraction.source_url,
                    )
                )
                cursor = end_at + timedelta(minutes=_DEFAULT_TRANSIT_BUFFER_MINUTES)

        return events

    @staticmethod
    def _build_event_description(
        day_description: str,
        attraction_description: str,
        attraction: object,
    ) -> str:
        """Build a compact event description with traceability metadata."""
        lines = [day_description.strip(), attraction_description.strip()]
        location = getattr(attraction, "location", None)
        if location is not None:
            lines.append(f"坐标: {location.latitude}, {location.longitude}")
        source_url = getattr(attraction, "source_url", None)
        if source_url:
            lines.append(f"来源: {source_url}")
        return "\n".join([line for line in lines if line])

    @staticmethod
    def _build_text_summary(trip_plan: TripPlan) -> str:
        """Create plain-text itinerary lines reused by file exports."""
        lines = [f"Trip Plan: {trip_plan.city}", f"Dates: {trip_plan.start_date} -> {trip_plan.end_date}"]
        for day in trip_plan.days:
            lines.append(f"Day {day.day_index + 1}: {day.description}")
            for attraction in day.attractions[:3]:
                lines.append(f"- {attraction.name} ({max(30, int(attraction.visit_duration or 0))} min)")
        return "\n".join(lines)

    @staticmethod
    def _build_minimal_pdf(summary_text: str) -> bytes:
        """Generate a small single-page PDF without external dependencies."""
        display_text = summary_text.splitlines()[0] if summary_text else "Trip Plan Export"
        ascii_text = display_text.encode("ascii", errors="ignore").decode("ascii").strip() or "Trip Plan Export"
        escaped = ascii_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 14 Tf 72 760 Td ({escaped}) Tj ET".encode("ascii")

        objects = [
            b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
            b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
            b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
            b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
            (
                b"5 0 obj << /Length "
                + str(len(stream)).encode("ascii")
                + b" >> stream\n"
                + stream
                + b"\nendstream endobj\n"
            ),
        ]

        output = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for obj in objects:
            offsets.append(len(output))
            output.extend(obj)
        xref_start = len(output)
        output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
        output.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(
            (
                "trailer << /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".format(
                    size=len(offsets), xref=xref_start
                )
            ).encode("ascii")
        )
        return bytes(output)

    @staticmethod
    def _build_svg_summary(trip_plan: TripPlan) -> str:
        """Render a deterministic SVG summary used for image export."""
        itinerary = []
        for day in trip_plan.days:
            itinerary.append(f"Day {day.day_index + 1}: {day.description}")
            for attraction in day.attractions[:2]:
                itinerary.append(f"  - {attraction.name}")
        body = " | ".join(itinerary[:8]) or "No itinerary details available."
        title = f"{trip_plan.city} Trip Plan"
        return (
            "<svg xmlns='http://www.w3.org/2000/svg' width='1200' height='630'>"
            "<defs><linearGradient id='g' x1='0%' y1='0%' x2='100%' y2='100%'>"
            "<stop offset='0%' stop-color='#0f766e'/>"
            "<stop offset='100%' stop-color='#164e63'/>"
            "</linearGradient></defs>"
            "<rect width='100%' height='100%' fill='url(#g)'/>"
            f"<text x='56' y='120' fill='white' font-size='52' font-family='Helvetica'>{escape(title)}</text>"
            f"<text x='56' y='190' fill='#d1fae5' font-size='28' font-family='Helvetica'>{escape(trip_plan.start_date)} to {escape(trip_plan.end_date)}</text>"
            f"<text x='56' y='270' fill='white' font-size='24' font-family='Helvetica'>{escape(body)}</text>"
            "</svg>"
        )

    @staticmethod
    def _normalize_target(value: str | None) -> ExportTarget | None:
        """Map raw target text into the internal target literal."""
        if not value:
            return None
        candidate = value.strip().lower()
        alias_map: dict[str, ExportTarget] = {
            "calendar": "google_calendar",
            "google_calendar": "google_calendar",
            "google calendar": "google_calendar",
            "gcal": "google_calendar",
            "pdf": "pdf",
            "image": "image",
            "img": "image",
            "png": "image",
            "jpg": "image",
            "jpeg": "image",
            "svg": "image",
        }
        return alias_map.get(candidate)

    @classmethod
    def _detect_target_from_text(cls, text: str | None) -> ExportTarget | None:
        """Infer export target from user free text when no explicit target exists."""
        if not text:
            return None
        normalized = text.lower()
        if "pdf" in normalized:
            return "pdf"
        if any(token in normalized for token in ("image", "img", "png", "jpg", "jpeg", "svg", "图片", "图像")):
            return "image"
        if any(token in normalized for token in ("calendar", "日历")):
            return "google_calendar"
        return None

    def _resolve_target_from_state(self, state: dict) -> ExportTarget:
        """Resolve export target with explicit value first, then text inference."""
        explicit = self._normalize_target(str(state.get("export_target", "")))
        if explicit is not None:
            return explicit

        request = state.get("request") or {}
        request_text = request.get("free_text_input") if isinstance(request, dict) else None
        inferred = self._detect_target_from_text(state.get("user_delta")) or self._detect_target_from_text(request_text)
        return inferred or "google_calendar"

    def as_worker(self) -> Callable[..., dict]:
        """Return a ``WorkerFn``-compatible export callable for PlannerAgent."""

        def _worker(state: dict) -> dict:
            target = self._resolve_target_from_state(state)
            previous_plan = state.get("previous_plan")
            if not previous_plan:
                return CalendarExportOutput(
                    provider=self._calendar.provider_name if target == "google_calendar" else _FALLBACK_PROVIDER_NAME,
                    target=target,
                    calendar_id=self._calendar.calendar_id if target == "google_calendar" else "n/a",
                    event_count=0,
                    events=[],
                    warnings=["No previous_plan supplied for export."],
                ).model_dump()

            trip_plan = previous_plan if isinstance(previous_plan, TripPlan) else TripPlan(**previous_plan)
            result = self.run(trip_plan, target=target)
            return result.model_dump()

        return _worker
