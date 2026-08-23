"""Regression for #940 misc batch (6 sub-items).

Covers: opengl marker, importorskip, skipif(True) cleanup, perf-gate
workflow existence, CWD-anchored path, merge-policy doc alignment.
"""
from __future__ import annotations

from pathlib import Path

import pytest


def test_pyproject_registers_opengl_marker():
    """#940-1: pyproject must declare the unified ``opengl`` marker."""
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert "opengl:" in text and "#940-1" in text


def test_stratal_opengl_tests_are_marked():
    """#940-1: GL-dependent stratal tests must carry the ``opengl`` marker."""
    # Collect-only is enough — we assert the marker is present in collection.
    import subprocess, sys
    out = subprocess.check_output(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "opengl",
         "tests/test_stratal_adapter.py", "tests/test_stratal_page_entry.py"],
        text=True,
    )
    assert "test_stratal_adapter_end_to_end_with_demo_and_renderer" in out
    assert "test_stratal_generate_demo_produces_visible_slices" in out
    assert "test_stratal_clear_removes_all_slices" in out
    # Offscreen CI must skip them (QT_QPA_PLATFORM=offscreen is the default in CI).
    # We don't assert skip count here — just that they are selectable via the marker.


def test_map_edit_core_hardening_uses_importorskip():
    """#940-2: bare import must not make collection error when geoviz absent."""
    text = (Path(__file__).resolve().parents[1] / "tests/test_map_edit_core_hardening.py").read_text(encoding="utf-8")
    assert 'pytest.importorskip("geoviz"' in text
    assert 'map_edit_core' in text and "importorskip" in text
    # exact multiline form: pytest.importorskip(\n    "map_edit_core"
    assert 'importorskip(' in text and '"map_edit_core"' in text
    # No bare `import geoviz` or `import map_edit_core` at module top.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("import geoviz") or stripped.startswith("import map_edit_core"):
            pytest.fail(f"bare import breaks skipif: {line!r}")
        if stripped.startswith("from geoviz") or stripped.startswith("from map_edit_core"):
            pytest.fail(f"bare from-import breaks skipif: {line!r}")


def test_no_skipif_true_placeholder():
    """#940-3: no permanent ``skipif(True)`` placeholder may remain."""
    repo = Path(__file__).resolve().parents[1]
    for p in repo.rglob("tests/**/*.py"):
        txt = p.read_text(encoding="utf-8", errors="ignore")
        if "skipif(True" in txt:
            # Allow the explanatory comment that mentions the former placeholder
            if "#940-3" in txt and "former skipif(True)" in txt:
                continue
            pytest.fail(f"permanent skipif(True) in {p}")


def test_perf_gate_workflow_exists_and_has_schedule_and_bench_gates():
    """#940-4: perf-gate.yml must exist, be valid YAML, and gate benches."""
    import yaml  # type: ignore
    wf = Path(__file__).resolve().parents[1] / ".github/workflows/perf-gate.yml"
    assert wf.is_file(), "perf-gate.yml not created"
    data = yaml.safe_load(wf.read_text(encoding="utf-8"))
    assert "schedule" in str(data) or "schedule" in wf.read_text(encoding="utf-8")
    text = wf.read_text(encoding="utf-8")
    assert "bench_interpolation" in text
    assert "render_engine" in text or "render-engine" in text
    assert "933" in text and "934" in text, "thresholds must reference #933/#934"
    # Must not trigger on PR push (nightly + dispatch only)
    assert "pull_request" not in text, "perf gate must not run on PR (nightly only)"
    assert "workflow_dispatch" in text


def test_p3_s10_is_cwd_independent():
    """#940-5: workflow-integrity test must anchor reads to __file__."""
    text = (Path(__file__).resolve().parents[1] / "tests/test_p3_s10.py").read_text(encoding="utf-8")
    assert "Path(__file__)" in text
    # The old bare CWD-relative read would be `Path(".github/...` or `open(".github`
    assert 'Path(".github' not in text
    assert 'open(".github' not in text


def test_merge_policy_docs_align_with_workflow():
    """#940-6: docs must describe qgis-renderer workflow as executing qgis tests."""
    text = (Path(__file__).resolve().parents[1] / "docs/ci-merge-policy.md").read_text(encoding="utf-8")
    assert "qgis" in text.lower()
    # Updated doc must say the qgis workflow executes the tests (not "does not run")
    assert "qgis" in text and ("executed" in text.lower() or "collect" in text.lower())
    assert "#935" in text or "#437" in text
