"""tests for tools/migration/pwb_closure_matrix.py (cpp-close-12).

The generator aggregates the wave lines' capability-matrix.json files into
the implemented/merged/wired/verified closure matrix. These tests pin the
contract that matters for review honesty: absence is visible, the
monotonic column gates hold, and --check detects drift.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "migration" / "pwb_closure_matrix.py"

spec = importlib.util.spec_from_file_location("pwb_closure_matrix", SCRIPT)
pwb_closure_matrix = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["pwb_closure_matrix"] = pwb_closure_matrix
spec.loader.exec_module(pwb_closure_matrix)


def _write_line(root: Path, line_dir: str, payload: dict | None) -> None:
    directory = root / "docs" / "development" / "cpp-closure-wave" / line_dir
    directory.mkdir(parents=True)
    if payload is not None:
        (directory / "capability-matrix.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_missing_capability_file_is_reported_not_dropped(tmp_path: Path) -> None:
    _write_line(tmp_path, "01-catalog-project", None)
    lines = [pwb_closure_matrix.parse_line_dir(
        tmp_path / "docs" / "development" / "cpp-closure-wave"
        / "01-catalog-project")]
    assert len(lines[0]) == 1
    cap = lines[0][0]
    assert cap.name == "(未登记)"
    assert cap.problems == ["capability-matrix.json missing"]
    markdown = pwb_closure_matrix.render_markdown(lines, {})
    assert "未登记线" in markdown
    assert "01-catalog-project" in markdown


def test_monotonic_column_gates(tmp_path: Path) -> None:
    line_dir = tmp_path / "docs" / "development" / "cpp-closure-wave" / "09-line"
    _write_line(tmp_path, "09-line", {
        "line": "09",
        "title": "审核治理",
        "capabilities": [
            {
                "capability": "QC 报告",
                "python_source": "workflow/qc.py",
                "cpp_target": "libs/closure_review",
                "implemented": True, "merged": True, "wired": True,
                "verified": True, "evidence": ["platform.review_actions"],
            },
            {
                "capability": "倒置门",
                "implemented": False, "merged": False, "wired": True,
                "verified": False,
            },
            {
                "capability": "无证据 verified",
                "implemented": True, "merged": True, "wired": True,
                "verified": True,
            },
        ],
    })
    caps = pwb_closure_matrix.parse_line_dir(line_dir)
    assert caps[0].problems == []
    assert any("wired requires implemented" in p for p in caps[1].problems)
    assert any("verified requires evidence" in p for p in caps[2].problems)
    markdown = pwb_closure_matrix.render_markdown([caps], {})
    assert "结构问题" in markdown


def test_registered_gap_row_with_note_is_allowed(tmp_path: Path) -> None:
    line_dir = tmp_path / "docs" / "development" / "cpp-closure-wave" / "12-x"
    _write_line(tmp_path, "12-x", {
        "line": "12",
        "capabilities": [
            {
                "capability": "外部依赖收口",
                "implemented": False, "merged": False,
                "wired": False, "verified": False,
                "note": "依赖 06/09 合流后装配",
            },
            {
                "capability": "意外空行",
                "implemented": False, "merged": False,
                "wired": False, "verified": False,
            },
        ],
    })
    caps = pwb_closure_matrix.parse_line_dir(line_dir)
    assert caps[0].problems == []
    assert any("all four columns false" in p for p in caps[1].problems)


def test_full_flag_row_has_evidence_and_renders(tmp_path: Path) -> None:
    line_dir = tmp_path / "docs" / "development" / "cpp-closure-wave" / "12-x"
    _write_line(tmp_path, "12-x", {
        "line": "12",
        "title": "收口",
        "capabilities": [
            {
                "capability": "工程保存",
                "python_source": "ui/project_controller.py",
                "cpp_target": "apps/paleo_workbench_platform/"
                              "shell_project_actions.cpp",
                "implemented": True, "merged": True, "wired": True,
                "verified": True, "evidence": ["platform.shell_project_actions"],
            },
        ],
    })
    caps = pwb_closure_matrix.parse_line_dir(line_dir)
    assert caps[0].problems == []
    markdown = pwb_closure_matrix.render_markdown([caps], {})
    assert "| 12 | 工程保存 |" in markdown
    assert "platform.shell_project_actions" in markdown


def test_check_mode_detects_drift(tmp_path: Path, capsys) -> None:
    _write_line(tmp_path, "12-x", {
        "line": "12",
        "capabilities": [
            {"capability": "c", "implemented": True, "merged": False,
             "wired": False, "verified": False},
        ],
    })
    rc = pwb_closure_matrix.main([
        "--repo-root", str(tmp_path),
        "--markdown-out", "docs/development/cpp-closure-wave/"
                          "closure-matrix.md",
    ])
    assert rc == 0
    # Unchanged file passes --check.
    rc = pwb_closure_matrix.main([
        "--repo-root", str(tmp_path),
        "--markdown-out", "docs/development/cpp-closure-wave/"
                          "closure-matrix.md",
        "--check",
    ])
    assert rc == 0
    # Content drift fails --check.
    matrix = (tmp_path / "docs/development/cpp-closure-wave/"
              "closure-matrix.md")
    matrix.write_text(matrix.read_text(encoding="utf-8") + "drift\n",
                      encoding="utf-8")
    rc = pwb_closure_matrix.main([
        "--repo-root", str(tmp_path),
        "--markdown-out", "docs/development/cpp-closure-wave/"
                          "closure-matrix.md",
        "--check",
    ])
    assert rc == 1


def test_coordination_section_renders_when_present(
        tmp_path: Path, monkeypatch) -> None:
    _write_line(tmp_path, "12-x", {
        "line": "12",
        "capabilities": [
            {"capability": "c", "implemented": True, "merged": False,
             "wired": False, "verified": False},
        ],
    })
    coord = tmp_path / ".git" / "codex-coordination" / "cpp-close-wave"
    coord.mkdir(parents=True)
    (coord / "12-line.json").write_text(json.dumps({
        "line": "12", "branch": "codex/cpp-close-12-x",
        "pr_url": None, "head_sha": "06211541ae",
        "status": "implementation",
    }), encoding="utf-8")
    lines = [pwb_closure_matrix.parse_line_dir(
        tmp_path / "docs" / "development" / "cpp-closure-wave" / "12-x")]
    coordination = pwb_closure_matrix.collect_coordination(coord)
    markdown = pwb_closure_matrix.render_markdown(lines, coordination)
    assert "协调登记" in markdown
    assert "codex/cpp-close-12-x" in markdown
