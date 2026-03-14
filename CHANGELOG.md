# Changelog

All notable changes to this project are documented in this file.

## [v0.1.0] - 2026-03-13

### Added

- Multi-agent planner architecture (`PlannerAgent`) with worker orchestration:
  - `AttractionAgent`, `WeatherAgent`, `HotelAgent`, `FlightAgent`, `VisaAgent`, `ExportAgent`
- Pluggable provider layer and registry:
  - Map (Amap / Google)
  - Photo (Unsplash / Google Places)
  - Flight (Amadeus)
  - Visa (Sherpa with domain whitelist)
  - Calendar (Google Calendar export provider)
- RAG integration path for Wikivoyage ingestion/retrieval bridge.
- Conversation memory with summary compression and recent buffer strategy.
- Frontend support for nationality and Google Calendar export option.

### Changed

- Unified export gateway supporting calendar / pdf / image.
- Prompt system standardized to 8-field template with planner-specific orchestration policies.
- Styling updated to low-saturation visual language.

### Testing & Quality

- Full backend test baseline reached and documented in F1 (`>= 80%` target satisfied).
- E2E user journeys for domestic / cross-border / RAG-enhanced flows.
- F2 observability baseline artifacts for latency / token estimate / external API call count.

### Documentation

- Root project README.
- API reference and prompt reference.
- New environment reproduction runbook.

