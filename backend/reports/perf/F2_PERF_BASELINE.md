# F2 Performance & Cost Baseline

- Generated at: `2026-03-13T21:59:07.890395`
- Iterations per scenario: `3`
- Scope: `/api/trip/plan` representative requests

## Scenario Metrics

| Scenario | Avg Latency (ms) | p50 (ms) | p95 (ms) | Avg Input Tokens | Avg Output Tokens | Avg Total Tokens | Avg External API Calls | Max External API Calls |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 国内行程（北京） | 98.85 | 20.01 | 233.58 | 51.00 | 2120.00 | 2171.00 | 5.00 | 5 |
| 跨国行程（东京） | 19.45 | 19.30 | 20.15 | 51.00 | 1715.00 | 1766.00 | 5.00 | 5 |
| RAG 景点增强（京都） | 19.31 | 19.14 | 19.72 | 66.00 | 1701.00 | 1767.00 | 5.00 | 5 |

## Overall Baseline

- Total requests: `9`
- Success rate: `100.00%`
- Latency avg / p95: `45.87` / `162.48` ms
- Tokens avg (input/output/total): `56.00` / `1845.33` / `1901.33`
- External API calls avg / max: `5.00` / `5`

## Artifacts

- JSON baseline: `/Users/yukun/Documents/Project1/backend/reports/perf/f2_baseline_20260313.json`
- Trace records: `/Users/yukun/Documents/Project1/backend/reports/perf/traces/f2_trace_20260313_215907.jsonl`

## Notes

- Token values are estimated via `estimate_tokens()` for observability baseline.
- External API calls count only non-local outbound `httpx` requests.
