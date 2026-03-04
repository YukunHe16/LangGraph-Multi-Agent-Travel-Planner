"""Unit tests for A4: verify .github/skills structure and spec-sync pipeline."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SKILLS_DIR = PROJECT_ROOT / ".github" / "skills"


def test_all_required_skill_files_exist() -> None:
    """Every expected skill must have a SKILL.md file."""
    required_skills = [
        "checkpoint",
        "dev-workflow",
        "implement",
        "progress-tracker",
        "skill-creator",
        "spec-sync",
        "testing-stage",
    ]
    for skill_name in required_skills:
        skill_file = SKILLS_DIR / skill_name / "SKILL.md"
        assert skill_file.exists(), f"Missing SKILL.md for skill: {skill_name}"
        content = skill_file.read_text(encoding="utf-8")
        assert len(content) > 100, f"SKILL.md for {skill_name} appears empty or too short"


def test_sync_spec_script_exists_and_runnable() -> None:
    """sync_spec.py must exist and be syntactically valid Python."""
    script = SKILLS_DIR / "spec-sync" / "sync_spec.py"
    assert script.exists(), "sync_spec.py not found"
    result = subprocess.run(
        [sys.executable, "-c", f"import ast; ast.parse(open('{script}').read())"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"sync_spec.py has syntax errors: {result.stderr}"


def test_sync_spec_generates_chapter_files() -> None:
    """Running sync_spec.py --force must produce spec chapter files and SPEC_INDEX.md."""
    script = SKILLS_DIR / "spec-sync" / "sync_spec.py"
    result = subprocess.run(
        [sys.executable, str(script), "--force"],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    assert result.returncode == 0, f"sync_spec.py failed: {result.stderr}"

    specs_dir = SKILLS_DIR / "spec-sync" / "specs"
    assert specs_dir.is_dir(), "specs/ directory not created"

    chapter_files = sorted(specs_dir.glob("*.md"))
    assert len(chapter_files) >= 6, f"Expected >= 6 chapter files, got {len(chapter_files)}"

    index_file = SKILLS_DIR / "spec-sync" / "SPEC_INDEX.md"
    assert index_file.exists(), "SPEC_INDEX.md not generated"
    index_content = index_file.read_text(encoding="utf-8")
    assert "Chapter Overview" in index_content or "章节" in index_content.lower() or "06-schedule" in index_content


def test_dev_spec_exists_and_has_schedule() -> None:
    """DEV_SPEC.md must exist and contain the project schedule section."""
    dev_spec = PROJECT_ROOT / "DEV_SPEC.md"
    assert dev_spec.exists(), "DEV_SPEC.md not found in project root"
    content = dev_spec.read_text(encoding="utf-8")
    assert "## 6. 项目排期" in content, "DEV_SPEC.md missing schedule section"
    assert "Phase A" in content, "DEV_SPEC.md missing Phase A"


def test_spec_hash_file_exists() -> None:
    """After sync, .spec_hash must exist for change detection."""
    hash_file = SKILLS_DIR / "spec-sync" / ".spec_hash"
    assert hash_file.exists(), ".spec_hash not found"
    content = hash_file.read_text(encoding="utf-8").strip()
    assert len(content) == 64, f"Expected SHA-256 hash (64 chars), got {len(content)} chars"
