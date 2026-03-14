"""F2 performance/cost baseline runner for ``/api/trip/plan``.

This script runs representative trip-planning requests and exports:
1. JSON baseline metrics (latency/token/external API calls)
2. Markdown summary report
3. JSONL trace records for each run

Usage:
    cd backend
    python scripts/perf_baseline.py --iterations 3
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import httpx
from fastapi.testclient import TestClient

from app.agents.planner import reset_planner_agent
from app.agents.memory.summary_memory import estimate_tokens
from app.api.main import app
from app.providers.registry import reset_provider_registry
from app.rag.retriever import reset_rag_retriever

LOCAL_HOSTS = {"testserver", "localhost", "127.0.0.1"}


@dataclass(frozen=True)
class Scenario:
    """A representative baseline scenario."""

    key: str
    label: str
    payload: dict[str, Any]


SCENARIOS: list[Scenario] = [
    Scenario(
        key="domestic",
        label="国内行程（北京）",
        payload={
            "city": "北京",
            "start_date": "2026-06-01",
            "end_date": "2026-06-03",
            "travel_days": 3,
            "transportation": "公共交通",
            "accommodation": "舒适型酒店",
            "preferences": ["美食", "历史文化"],
            "free_text_input": "",
        },
    ),
    Scenario(
        key="cross_border",
        label="跨国行程（东京）",
        payload={
            "city": "东京",
            "start_date": "2026-06-01",
            "end_date": "2026-06-03",
            "travel_days": 3,
            "transportation": "公共交通",
            "accommodation": "舒适型酒店",
            "preferences": ["美食", "历史文化"],
            "free_text_input": "",
        },
    ),
    Scenario(
        key="rag_enhanced",
        label="RAG 景点增强（京都）",
        payload={
            "city": "京都",
            "start_date": "2026-06-01",
            "end_date": "2026-06-03",
            "travel_days": 3,
            "transportation": "公共交通",
            "accommodation": "舒适型酒店",
            "preferences": ["景点增强", "历史文化"],
            "free_text_input": "请结合Wikivoyage增强景点",
        },
    ),
]


class ExternalCallTracer:
    """Capture outbound non-local ``httpx`` calls during a baseline run."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    @contextmanager
    def patch_httpx(self) -> Iterator[None]:
        """Patch ``httpx.Client.request`` and collect external-call traces."""
        original_request = httpx.Client.request
        tracer = self

        def wrapped_request(client: httpx.Client, method: str, url: Any, *args: Any, **kwargs: Any) -> Any:
            url_text = str(url)
            host = (urlparse(url_text).hostname or "").lower()
            should_trace = host not in LOCAL_HOSTS and host != ""
            start = time.perf_counter()
            try:
                response = original_request(client, method, url, *args, **kwargs)
                if should_trace:
                    tracer.events.append(
                        {
                            "timestamp": datetime.now().isoformat(),
                            "method": method.upper(),
                            "url": url_text,
                            "host": host,
                            "status_code": response.status_code,
                            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                        }
                    )
                return response
            except Exception as exc:  # pragma: no cover - defensive path
                if should_trace:
                    tracer.events.append(
                        {
                            "timestamp": datetime.now().isoformat(),
                            "method": method.upper(),
                            "url": url_text,
                            "host": host,
                            "status_code": None,
                            "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                            "error": str(exc),
                        }
                    )
                raise

        httpx.Client.request = wrapped_request  # type: ignore[assignment]
        try:
            yield
        finally:
            httpx.Client.request = original_request  # type: ignore[assignment]

    def events_since(self, index: int) -> list[dict[str, Any]]:
        """Return trace events produced after a given event index."""
        return self.events[index:]


def _percentile(values: list[float], p: int) -> float:
    """Compute a percentile using inclusive interpolation."""
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 2)
    quantiles = statistics.quantiles(values, n=100, method="inclusive")
    return round(quantiles[p - 1], 2)


def _to_markdown(summary: dict[str, Any], trace_file: Path, json_file: Path) -> str:
    """Render markdown report from baseline summary."""
    lines: list[str] = []
    lines.append("# F2 Performance & Cost Baseline")
    lines.append("")
    lines.append(f"- Generated at: `{summary['generated_at']}`")
    lines.append(f"- Iterations per scenario: `{summary['iterations_per_scenario']}`")
    lines.append("- Scope: `/api/trip/plan` representative requests")
    lines.append("")
    lines.append("## Scenario Metrics")
    lines.append("")
    lines.append("| Scenario | Avg Latency (ms) | p50 (ms) | p95 (ms) | Avg Input Tokens | Avg Output Tokens | Avg Total Tokens | Avg External API Calls | Max External API Calls |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for item in summary["scenario_metrics"]:
        lines.append(
            "| {label} | {lat_avg:.2f} | {lat_p50:.2f} | {lat_p95:.2f} | "
            "{in_tok:.2f} | {out_tok:.2f} | {total_tok:.2f} | {ext_avg:.2f} | {ext_max} |".format(
                label=item["label"],
                lat_avg=item["latency_ms_avg"],
                lat_p50=item["latency_ms_p50"],
                lat_p95=item["latency_ms_p95"],
                in_tok=item["input_tokens_avg"],
                out_tok=item["output_tokens_avg"],
                total_tok=item["total_tokens_avg"],
                ext_avg=item["external_api_calls_avg"],
                ext_max=item["external_api_calls_max"],
            )
        )
    lines.append("")
    lines.append("## Overall Baseline")
    lines.append("")
    overall = summary["overall"]
    lines.append(f"- Total requests: `{overall['total_requests']}`")
    lines.append(f"- Success rate: `{overall['success_rate']:.2%}`")
    lines.append(f"- Latency avg / p95: `{overall['latency_ms_avg']:.2f}` / `{overall['latency_ms_p95']:.2f}` ms")
    lines.append(
        f"- Tokens avg (input/output/total): "
        f"`{overall['input_tokens_avg']:.2f}` / `{overall['output_tokens_avg']:.2f}` / `{overall['total_tokens_avg']:.2f}`"
    )
    lines.append(
        f"- External API calls avg / max: "
        f"`{overall['external_api_calls_avg']:.2f}` / `{overall['external_api_calls_max']}`"
    )
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- JSON baseline: `{json_file.as_posix()}`")
    lines.append(f"- Trace records: `{trace_file.as_posix()}`")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Token values are estimated via `estimate_tokens()` for observability baseline.")
    lines.append("- External API calls count only non-local outbound `httpx` requests.")
    return "\n".join(lines) + "\n"


def _aggregate_summary(
    *,
    runs: list[dict[str, Any]],
    generated_at: str,
    iterations_per_scenario: int,
) -> dict[str, Any]:
    """Aggregate per-run records into scenario-level and overall metrics."""
    scenario_metrics: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        scoped = [r for r in runs if r["scenario"] == scenario.key]
        latencies = [float(r["latency_ms"]) for r in scoped]
        in_tokens = [float(r["input_tokens_est"]) for r in scoped]
        out_tokens = [float(r["output_tokens_est"]) for r in scoped]
        total_tokens = [float(r["total_tokens_est"]) for r in scoped]
        ext_calls = [int(r["external_api_calls"]) for r in scoped]

        scenario_metrics.append(
            {
                "scenario": scenario.key,
                "label": scenario.label,
                "requests": len(scoped),
                "success_rate": (sum(1 for r in scoped if r["success"]) / len(scoped)) if scoped else 0.0,
                "latency_ms_avg": round(statistics.fmean(latencies), 2) if latencies else 0.0,
                "latency_ms_p50": _percentile(latencies, 50),
                "latency_ms_p95": _percentile(latencies, 95),
                "input_tokens_avg": round(statistics.fmean(in_tokens), 2) if in_tokens else 0.0,
                "output_tokens_avg": round(statistics.fmean(out_tokens), 2) if out_tokens else 0.0,
                "total_tokens_avg": round(statistics.fmean(total_tokens), 2) if total_tokens else 0.0,
                "external_api_calls_avg": round(statistics.fmean(ext_calls), 2) if ext_calls else 0.0,
                "external_api_calls_max": max(ext_calls) if ext_calls else 0,
            }
        )

    all_latencies = [float(r["latency_ms"]) for r in runs]
    all_in_tokens = [float(r["input_tokens_est"]) for r in runs]
    all_out_tokens = [float(r["output_tokens_est"]) for r in runs]
    all_total_tokens = [float(r["total_tokens_est"]) for r in runs]
    all_ext_calls = [int(r["external_api_calls"]) for r in runs]
    success_total = sum(1 for r in runs if r["success"])

    return {
        "generated_at": generated_at,
        "iterations_per_scenario": iterations_per_scenario,
        "scenario_metrics": scenario_metrics,
        "overall": {
            "total_requests": len(runs),
            "success_rate": (success_total / len(runs)) if runs else 0.0,
            "latency_ms_avg": round(statistics.fmean(all_latencies), 2) if all_latencies else 0.0,
            "latency_ms_p95": _percentile(all_latencies, 95),
            "input_tokens_avg": round(statistics.fmean(all_in_tokens), 2) if all_in_tokens else 0.0,
            "output_tokens_avg": round(statistics.fmean(all_out_tokens), 2) if all_out_tokens else 0.0,
            "total_tokens_avg": round(statistics.fmean(all_total_tokens), 2) if all_total_tokens else 0.0,
            "external_api_calls_avg": round(statistics.fmean(all_ext_calls), 2) if all_ext_calls else 0.0,
            "external_api_calls_max": max(all_ext_calls) if all_ext_calls else 0,
        },
    }


def run_baseline(
    *,
    iterations: int = 3,
    output_dir: Path | None = None,
    date_override: str | None = None,
) -> dict[str, Path]:
    """Run baseline scenarios and write JSON, markdown, and trace artifacts.

    Args:
        iterations: Number of requests per scenario.
        output_dir: Directory for report artifacts.
        date_override: Optional YYYYMMDD string for deterministic JSON filename.

    Returns:
        Mapping with artifact paths.
    """
    if iterations < 1:
        raise ValueError("iterations must be >= 1")

    root = Path(__file__).resolve().parents[1]
    reports_root = output_dir or (root / "reports" / "perf")
    traces_root = reports_root / "traces"
    traces_root.mkdir(parents=True, exist_ok=True)

    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_stamp = date_override or datetime.now().strftime("%Y%m%d")

    json_path = reports_root / f"f2_baseline_{date_stamp}.json"
    markdown_path = reports_root / "F2_PERF_BASELINE.md"
    trace_path = traces_root / f"f2_trace_{run_stamp}.jsonl"

    # Reset singletons to reduce previous-run leakage.
    reset_planner_agent()
    reset_provider_registry()
    reset_rag_retriever()

    tracer = ExternalCallTracer()
    run_records: list[dict[str, Any]] = []

    with TestClient(app) as client, tracer.patch_httpx():
        for scenario in SCENARIOS:
            for iteration in range(1, iterations + 1):
                started_at = datetime.now().isoformat()
                trace_start = len(tracer.events)
                started = time.perf_counter()

                response = client.post("/api/trip/plan", json=scenario.payload)

                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                events = tracer.events_since(trace_start)
                hosts = sorted({str(e.get("host", "")) for e in events if e.get("host")})
                input_tokens = estimate_tokens(
                    json.dumps(scenario.payload, ensure_ascii=False, sort_keys=True)
                )
                output_tokens = estimate_tokens(response.text)

                success = response.status_code == 200
                if success:
                    try:
                        body = response.json()
                        success = bool(body.get("success") is True)
                    except Exception:
                        success = False

                run_records.append(
                    {
                        "timestamp": started_at,
                        "scenario": scenario.key,
                        "scenario_label": scenario.label,
                        "iteration": iteration,
                        "status_code": response.status_code,
                        "success": success,
                        "latency_ms": latency_ms,
                        "input_tokens_est": input_tokens,
                        "output_tokens_est": output_tokens,
                        "total_tokens_est": input_tokens + output_tokens,
                        "external_api_calls": len(events),
                        "external_hosts": hosts,
                        "external_events": events,
                    }
                )

    summary = _aggregate_summary(
        runs=run_records,
        generated_at=datetime.now().isoformat(),
        iterations_per_scenario=iterations,
    )

    payload = {
        "task": "F2_performance_and_cost_baseline",
        "scenarios": [
            {"key": scenario.key, "label": scenario.label, "payload": scenario.payload}
            for scenario in SCENARIOS
        ],
        "summary": summary,
        "runs": run_records,
    }

    with json_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    with trace_path.open("w", encoding="utf-8") as f:
        for row in run_records:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    markdown_content = _to_markdown(summary, trace_path, json_path)
    with markdown_path.open("w", encoding="utf-8") as f:
        f.write(markdown_content)

    return {"json": json_path, "markdown": markdown_path, "trace": trace_path}


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate F2 performance/cost baseline artifacts.")
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Requests per scenario (default: 3).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Artifacts output directory (default: backend/reports/perf).",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Override JSON filename date (YYYYMMDD).",
    )
    return parser


def main() -> int:
    args = _build_arg_parser().parse_args()
    artifacts = run_baseline(
        iterations=args.iterations,
        output_dir=args.output_dir,
        date_override=args.date,
    )
    print("F2 baseline generated:")
    print(f"- JSON: {artifacts['json']}")
    print(f"- Markdown: {artifacts['markdown']}")
    print(f"- Trace: {artifacts['trace']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
