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


def test_slow_tests_guard_covers_all_three_skip_phrases_and_baseline_15() -> None:
    """#896: slow-tests.yml 必须同时覆盖三类 SEGY 缺失文案且基线为 15。

    三个 skip 产地:
    - tests/test_geoviz_real_data_smoke.py:     "representative data file is absent"
    - tests/test_seismic_timeslice_axis_contract.py: "demo SEGY not available" (2 × @slow)
    - tests/test_well_seismic_fence_probe.py:        "no demo SEGY" (1 × @slow)

    守卫用 SLOW_SKIP_RE 汇总三者，遗漏任一都会让数据树缺失时静默绿。
    基线 15 = 7 smoke + 5 perf + 2 axis + 1 fence，CI 与本地双侧一致。
    """
    import re

    slow_yml = (WORKFLOW_DIR / "slow-tests.yml").read_text(encoding="utf-8")
    ci_yml = (WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8")

    # — Baseline 15 on both workflows —
    for name, text in (("slow-tests.yml", slow_yml), ("ci.yml", ci_yml)):
        assert "baseline 15" in text.lower() or "baseline 15" in text, f"{name} baseline not bumped to 15"
        assert "-ge 15" in text, f"{name} -ge 15 guard missing"

    # — Guard covers all three phrases (mirror of yml's SLOW_SKIP_RE) —
    expected_phrases = [
        "representative data file is absent",
        "demo SEGY not available",
        "no demo SEGY",
    ]
    for phrase in expected_phrases:
        assert phrase in slow_yml, f"slow-tests.yml guard missing phrase: {phrase!r}"

    # Validate that slow-tests.yml's guard regex is well-formed and matches
    # each phrase (replicates the grep behaviour the CI python step uses).
    m = re.search(r'SLOW_SKIP_RE\s*=\s*r"([^"]+)"', slow_yml)
    assert m, "slow-tests.yml SLOW_SKIP_RE not found"
    pattern = m.group(1)
    compiled = re.compile(pattern)
    for phrase in expected_phrases:
        assert compiled.search(phrase), f"SLOW_SKIP_RE does not match {phrase!r}"

    # Source-of-truth: the three skip sites still emit those exact phrases.
    smoke = (REPO_ROOT / "tests/test_geoviz_real_data_smoke.py").read_text(encoding="utf-8")
    axis = (REPO_ROOT / "tests/test_seismic_timeslice_axis_contract.py").read_text(encoding="utf-8")
    fence = (REPO_ROOT / "tests/test_well_seismic_fence_probe.py").read_text(encoding="utf-8")
    assert "representative data file is absent" in smoke
    assert "demo SEGY not available" in axis
    assert '"no demo SEGY"' in fence or "'no demo SEGY'" in fence or "no demo SEGY" in fence


def test_slow_family_collect_count_meets_baseline_15() -> None:
    """#896: slow 家族实采数 ≥15（本地最小可测家族完整性）。"""
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
    assert count >= 15, f"slow family shrank to {count} (< 15); update baselines or restore tests"


def test_ci_3d_opengl_leg_contract() -> None:
    """#1058: the dedicated 3D OpenGL leg must exist and select the opengl
    family on a real X server (xcb), not the offscreen platform where every
    marked test skips unconditionally."""
    import yaml

    wf = yaml.safe_load((WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8"))
    job = wf["jobs"]["test-3d-opengl"]
    assert job["runs-on"] == "ubuntu-latest"
    env = job["env"]
    # Real GL context: xcb on Xvfb + software Mesa — NOT offscreen.
    assert env["QT_QPA_PLATFORM"] == "xcb"
    assert env["LIBGL_ALWAYS_SOFTWARE"] == "1"
    run_steps = [
        step.get("run", "") for step in job["steps"] if isinstance(step, dict)
    ]
    assert any("-m opengl" in run for run in run_steps), (
        "the 3D leg must select the opengl marker family"
    )
    # Observability leg by policy until GHA llvmpipe soak completes.
    assert job.get("continue-on-error") is True


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
