# Prompt Reference

This project uses centralized prompt templates in:

- `backend/app/prompts/trip_prompts.py`

## Prompt Registry

Registered prompt keys (`ALL_AGENT_PROMPTS`):

- `attraction`
- `weather`
- `hotel`
- `flight`
- `visa`
- `planner`

## Mandatory 8-Field Structure

Every agent prompt follows the same required sections:

1. `## 1. Role & Mission`
2. `## 2. Context & Input Schema`
3. `## 3. Hard Constraints`
4. `## 4. Tool Usage Policy`
5. `## 5. Reasoning Policy`
6. `## 6. Output Schema`
7. `## 7. Failure Policy`
8. `## 8. Examples`

Validation source:
- `REQUIRED_PROMPT_SECTIONS` in `trip_prompts.py`
- `backend/tests/unit/test_prompt_regression.py`

## Planner-Only Extra Sections

`PlannerAgent` adds orchestration-specific sections:

- `Routing Policy`
- `Tool Decision Matrix`
- `Delta Update Policy`
- `Merge Policy`
- `Conflict Policy`
- `Citation & Link Policy`
- `Memory Policy`
- `Output Contract`

Validation source:
- `PLANNER_EXTRA_SECTIONS` in `trip_prompts.py`
- `backend/tests/unit/test_prompt_regression.py`

## Runtime Relationships

- `PlannerAgent` prompt: `PLANNER_AGENT_PROMPT`
- Worker prompts:
  - `ATTRACTION_AGENT_PROMPT`
  - `WEATHER_AGENT_PROMPT`
  - `HOTEL_AGENT_PROMPT`
  - `FLIGHT_AGENT_PROMPT`
  - `VISA_AGENT_PROMPT`

The `ExportAgent` currently operates by worker logic and export gateway contracts, not by a dedicated prompt constant in the registry.

## How to Update Prompts Safely

1. Edit `backend/app/prompts/trip_prompts.py`.
2. Preserve all required section markers.
3. Keep JSON output examples aligned with Pydantic schemas in `backend/app/models/schemas.py`.
4. Run regression tests:

```bash
cd backend
source ../.venv/bin/activate
pytest -q tests/unit/test_prompt_regression.py
```

5. If prompt output contract changes, update:
- planner/worker synthesis logic
- schema tests
- API docs (if response shape changed)

## Prompt Design Constraints (from Spec)

- Do not hardcode API/tool results in prompts.
- Output must remain structured and parseable.
- Recommendation links must be traceable (`source_url` / `source_links`).
- Planner output must include `flight_plan`, `visa_summary`, `source_links`, and `conflicts`.

