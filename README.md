# Project1 Travel Planner

Project1 is a LangGraph-based multi-agent travel planner with:
- FastAPI backend (`/api/trip/plan`, map/poi utilities, health endpoints)
- Vue 3 frontend (trip form + result pages)
- Pluggable provider architecture (map/photo/flight/visa/calendar)
- RAG-enhanced attraction flow (Wikivoyage bridge + fallback)
- Conversation memory (`recent_buffer + running_summary`)

## Repository Layout

```text
Project1/
├── DEV_SPEC.md
├── backend/
│   ├── app/
│   ├── config/settings.yaml
│   ├── scripts/
│   └── tests/
├── frontend/
└── docs/
```

## Quick Start

### 1) Prerequisites

- Python 3.10+
- Node.js 18+
- npm

### 2) Backend Setup

```bash
cd /path/to/Project1
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e backend[dev]
```

### 3) Frontend Setup

```bash
cd /path/to/Project1/frontend
npm install
```

### 4) Run Services

Backend:

```bash
cd /path/to/Project1/backend
source ../.venv/bin/activate
uvicorn app.api.main:app --host 127.0.0.1 --port 8010
```

Frontend:

```bash
cd /path/to/Project1/frontend
npm run dev
```

Frontend default URL: `http://127.0.0.1:5173`  
Backend default URL: `http://127.0.0.1:8010`

## Smoke Test

Health check:

```bash
curl -s http://127.0.0.1:8010/api/health
```

Trip plan request:

```bash
curl -s -X POST http://127.0.0.1:8010/api/trip/plan \
  -H "Content-Type: application/json" \
  -d '{
    "city":"北京",
    "start_date":"2026-06-01",
    "end_date":"2026-06-03",
    "travel_days":3,
    "transportation":"公共交通",
    "accommodation":"舒适型酒店",
    "preferences":["美食","历史文化"],
    "free_text_input":""
  }'
```

## Testing

Run all backend tests:

```bash
cd /path/to/Project1/backend
source ../.venv/bin/activate
pytest
```

Coverage baseline command:

```bash
pytest --cov=backend/app backend/tests/
```

F2 perf baseline generation:

```bash
python scripts/perf_baseline.py --iterations 3
```

## Configuration

Primary config file: `backend/config/settings.yaml`.

Important provider settings:
- `providers.map_provider` / `map_provider_fallback`
- `providers.photo_provider` / `photo_provider_fallback`
- `providers.flight_provider`
- `providers.visa_provider`
- `providers.calendar_provider`

RAG and memory switches:
- `rag.enabled`
- `rag.integration_mode`
- `memory.enabled`
- `memory.max_tokens`, `memory.summary_trigger_tokens`

Environment variables (optional overrides for API keys):
- `AMAP_API_KEY`
- `UNSPLASH_ACCESS_KEY`
- `GOOGLE_MAPS_API_KEY`
- `GOOGLE_PLACES_API_KEY`
- `AMADEUS_CLIENT_ID`
- `AMADEUS_CLIENT_SECRET`
- `SHERPA_API_KEY`
- `GOOGLE_CALENDAR_ACCESS_TOKEN`

## Documentation Index

- API reference: [`docs/API_REFERENCE.md`](docs/API_REFERENCE.md)
- Prompt reference: [`docs/PROMPT_REFERENCE.md`](docs/PROMPT_REFERENCE.md)
- New environment reproduction runbook: [`docs/NEW_ENV_REPRO.md`](docs/NEW_ENV_REPRO.md)
- Release checklist: [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md)
- Changelog: [`CHANGELOG.md`](CHANGELOG.md)
