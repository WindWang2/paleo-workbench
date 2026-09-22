"""Workflow-file and submodule-filename integrity guards.

#827: ``qgis-renderer.yml`` shipped an invalid YAML block for its whole life
(a dedented comment terminated the ``run:`` block scalar), so the dedicated
QGIS fail-closed gate never started once. Parsing every workflow file in the
test suite makes that class of rot loud locally, without depending on CI.

#856: the packaging #441 device (README/docs block notices, a dead KNOWN
allowlist of JSON-wrapped literals, workaround comments) went stale after the
upstream geo-viz-engine rename. These tests pin the *current* contract: the
pinned submodule trees contain no Windows-invalid filenames, so the guard
can never again silently mask a real offender behind an unmachable allowlist.
"""

from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

INVALID_CHARS = set('<>:"|?*')
RESERVED_NAMES = (
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def _windows_invalid_parts(relative: pathlib.Path) -> list[str]:
    return [
        part
        for part in relative.parts
        if any(c in INVALID_CHARS or ord(c) < 32 for c in part)
        or part.split(".")[0].upper() in RESERVED_NAMES
    ]


def test_all_workflow_files_parse_as_yaml() -> None:
    """Every workflow file must be loadable — GitHub refuses anything else."""
    files = sorted(WORKFLOW_DIR.glob("*.yml"))
    assert files, "no workflow files found; test layout is wrong"
    parsed = {}
    for path in files:
        parsed[path.name] = yaml.safe_load(path.read_text(encoding="utf-8"))  # raises on invalid YAML
    for name, doc in parsed.items():
        assert isinstance(doc, dict), f"{name} must be a mapping"
        assert "jobs" in doc and doc["jobs"], f"{name} has no jobs"
    # The QGIS gate (#827's exact casualty) keeps its fail-closed shape.
    qgis = parsed["qgis-renderer.yml"]
    build = qgis["jobs"]["build"]
    step_names = [str(step.get("name", "")) for step in build["steps"]]
    assert any("Import smoke" in name for name in step_names)
    assert any("Vendor integrity" in name for name in step_names)
    assert build.get("timeout-minutes") == 120


@pytest.mark.parametrize("submodule", ["geo-viz-engine", "well-log-engine"])
def test_submodule_tree_has_no_windows_invalid_filenames(submodule: str) -> None:
    """Local twin of the CI guard (#441/#856): pin must stay checkout-clean."""
    root = REPO_ROOT / submodule
    if not root.is_dir() or not any(root.iterdir()):
        pytest.skip(f"{submodule} submodule not checked out in this environment")
    offenders = []
    for path in root.rglob("*"):
        bad = _windows_invalid_parts(path.relative_to(REPO_ROOT))
        if bad:
            offenders.append((str(path), bad))
    assert not offenders, f"Windows-invalid filenames in {submodule}: {offenders[:10]}"


def test_ci_windows_filename_guard_has_no_dead_allowlist() -> None:
    """#856: the guard must not carry allowlist entries that can never match.

    The retired KNOWN set contained JSON-wrapped literals
    (``{"filename": "ui-ref-screenshot.png"}``) compared against path
    components — a comparison that is false for every possible file, i.e.
    dead code providing false confidence.
    """
    ci = (WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8")
    guard = ci[ci.index("Guard against Windows-invalid submodule filenames"):]
    guard = guard[: guard.index("Setup Python")]
    assert "KNOWN" not in guard, "guard allowlist reintroduced; match real paths or drop it"
    assert "ui-ref" not in guard, "stale #441 offender referenced in the guard"


def test_slow_tests_guard_covers_skip_phrases_and_baseline() -> None:
    """#896 lineage, updated for the Python retirement (2026-09-22): the
    product slow family (real-data e2e smoke, SEGY axis contracts, fence
    probe, interpolation perf) retired to legacy/python_reference/tests; the
    remaining slow family is the geoviz realdata smoke + perf benches. The
    fail-closed skip-phrase guard and a presence baseline (>= 1) stay.
    """
    import re

    slow_yml = (WORKFLOW_DIR / "slow-tests.yml").read_text(encoding="utf-8")
    ci_yml = (WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8")

    # — Presence baseline on both workflows (retirement-aware) —
    for name, text in (("slow-tests.yml", slow_yml), ("ci.yml", ci_yml)):
        assert "baseline 1" in text, f"{name} retirement baseline missing"
        assert "-ge 1" in text, f"{name} -ge 1 guard missing"

    # — Guard keeps covering the skip phrases the workflow greps for —
    m = re.search(r'SLOW_SKIP_RE\s*=\s*r"([^"]+)"', slow_yml)
    assert m, "slow-tests.yml SLOW_SKIP_RE not found"
    compiled = re.compile(m.group(1))
    for phrase in ("representative data file is absent",
                   "demo SEGY not available",
                   "no demo SEGY"):
        assert compiled.search(phrase), f"SLOW_SKIP_RE does not match {phrase!r}"


def test_slow_family_collect_count_meets_baseline() -> None:
    """#896 lineage, retirement-aware: slow 家族实采数 ≥1（geoviz 家族仍在）。"""
    import subprocess
    import sys as _sys

    result = subprocess.run(
        [_sys.executable, "-m", "pytest", "--collect-only", "-q", "-m", "slow", "tests/"],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    combined = result.stdout + result.stderr
    # Allow one known collection error path (e.g. missing map_edit_core) to not
    # mask the baseline check — ignore the error line and parse collected count.
    import re as _re

    match = _re.search(r"(\d+) tests collected", combined)
    # If collection fully failed (0 collected), surface the error loudly.
    assert match, f"could not parse collected count from:\n{combined[:4000]}"
    count = int(match.group(1))
    assert count >= 1, f"slow family shrank to {count} (< 1); the geoviz slow family must stay collectible"


def test_ci_3d_opengl_leg_retired() -> None:
    """Python-retirement (2026-09-22): the test-3d-opengl leg was removed with
    the retired product's opengl family (docs/development/python-retirement/).
    The merge gate must no longer depend on it."""
    import yaml

    wf = yaml.safe_load((WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8"))
    assert "test-3d-opengl" not in wf["jobs"], "retired 3D leg must stay removed"
    gate = wf["jobs"]["merge-gate"]
    assert "test-3d-opengl" not in gate["needs"]


def test_ci_main_leg_does_not_run_opengl_family() -> None:
    """The offscreen main legs must keep deselecting the opengl marker (they
    cannot provide a GL context), so the 3D leg is the only coverage."""
    import yaml

    wf = yaml.safe_load((WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8"))
    test_job = wf["jobs"]["test"]
    run_steps = [
        step.get("run", "") for step in test_job["steps"] if isinstance(step, dict)
    ]
    pytest_runs = [r for r in run_steps if "pytest" in r]
    assert pytest_runs, "main test job must run pytest"
    for run in pytest_runs:
        assert "-m opengl" not in run and "-m=opengl" not in run, (
            "main offscreen leg must not select the opengl family"
        )
