"""Integration test for F2 baseline script artifact generation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_perf_baseline_script_generates_observability_artifacts(tmp_path: Path) -> None:
    """Script should emit JSON + markdown + trace artifacts with key metrics."""
    backend_root = Path(__file__).resolve().parents[2]
    script_path = backend_root / "scripts" / "perf_baseline.py"
    date_stamp = "20260313"

    subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--iterations",
            "1",
            "--output-dir",
            str(tmp_path),
            "--date",
            date_stamp,
        ],
        cwd=backend_root,
        check=True,
    )

    json_path = tmp_path / f"f2_baseline_{date_stamp}.json"
    markdown_path = tmp_path / "F2_PERF_BASELINE.md"
    traces_dir = tmp_path / "traces"

    assert json_path.exists(), "Baseline JSON artifact should exist"
    assert markdown_path.exists(), "Baseline markdown report should exist"
    assert traces_dir.exists(), "Trace directory should exist"

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    summary = payload["summary"]
    overall = summary["overall"]

    assert payload["task"] == "F2_performance_and_cost_baseline"
    assert len(payload["scenarios"]) == 3
    assert len(summary["scenario_metrics"]) == 3
    assert overall["total_requests"] == 3

    for row in summary["scenario_metrics"]:
        assert "latency_ms_avg" in row
        assert "total_tokens_avg" in row
        assert "external_api_calls_avg" in row

    traces = list(traces_dir.glob("*.jsonl"))
    assert len(traces) == 1
    lines = [line for line in traces[0].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3

