# Release Checklist (F4)

Target release: `v0.1.0`

Checklist owner: Project1 release workflow  
Last updated: 2026-03-13

## Scope Gate

- [x] `DEV_SPEC.md` phase progress is synchronized before release
- [x] Changelog is present and updated (`CHANGELOG.md`)
- [x] Core user flows have automated test coverage (unit/integration/e2e)
- [x] Performance/cost observability baseline artifacts exist
- [x] API and Prompt docs are available for onboarding

## Evidence

1. Spec sync and progress:
   - `DEV_SPEC.md` current state at F4 execution: Phase F `3/4`, total `29/30`
2. Changelog:
   - `CHANGELOG.md` created with `v0.1.0` release notes
3. Quality/test evidence:
   - Full coverage baseline already completed in F1
   - Prompt regression test command:
     - `cd backend && source ../.venv/bin/activate && pytest -q tests/unit/test_prompt_regression.py`
4. Observability evidence:
   - `backend/reports/perf/F2_PERF_BASELINE.md`
   - `backend/reports/perf/f2_baseline_20260313.json`
   - `backend/reports/perf/traces/f2_trace_20260313_215907.jsonl`
5. Docs evidence:
   - `README.md`
   - `docs/API_REFERENCE.md`
   - `docs/PROMPT_REFERENCE.md`
   - `docs/NEW_ENV_REPRO.md`

## Release Tag Policy

- Canonical release tag format: `vMAJOR.MINOR.PATCH`
- Current release tag for F4 completion: `v0.1.0`
- Tag should be created on the final F4 checkpoint commit.

## Approval

- [x] Checklist reviewed
- [x] Ready for release-tag creation on F4 final commit

