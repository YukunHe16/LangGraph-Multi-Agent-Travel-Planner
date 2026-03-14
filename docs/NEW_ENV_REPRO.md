# New Environment Reproduction Runbook

Goal: a new teammate can bootstrap, run, and validate core flows independently.

## 1. Bootstrap

```bash
cd /path/to/Project1
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e backend[dev]

cd frontend
npm install
```

## 2. Start Backend

```bash
cd /path/to/Project1/backend
source ../.venv/bin/activate
uvicorn app.api.main:app --host 127.0.0.1 --port 8010
```

## 3. Verify Backend Health

```bash
curl -s http://127.0.0.1:8010/api/health
```

Expected fields:
- `status`
- `app`
- `env`

## 4. Verify Trip Planning API

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

Expected:
- HTTP 200
- `success=true`
- `data.days` is present

## 5. Start Frontend (Optional for full-stack check)

```bash
cd /path/to/Project1/frontend
npm run dev
```

Open `http://127.0.0.1:5173`, submit a sample trip form, and confirm result page renders itinerary.

## 6. Test Suite Verification

Backend full test:

```bash
cd /path/to/Project1/backend
source ../.venv/bin/activate
pytest
```

Prompt regression:

```bash
pytest -q tests/unit/test_prompt_regression.py
```

Perf baseline artifact generation:

```bash
python scripts/perf_baseline.py --iterations 3
```

Expected files:
- `backend/reports/perf/F2_PERF_BASELINE.md`
- `backend/reports/perf/f2_baseline_YYYYMMDD.json`
- `backend/reports/perf/traces/f2_trace_*.jsonl`

## 7. Troubleshooting

- `ModuleNotFoundError`: ensure virtualenv activated and `pip install -e backend[dev]` completed.
- Frontend cannot reach backend: verify backend is on `127.0.0.1:8010`.
- External API errors: most providers have fallback behavior when keys are absent, but fields may be simplified.
- RAG bridge import errors: retriever will degrade to stub fallback for local development.

