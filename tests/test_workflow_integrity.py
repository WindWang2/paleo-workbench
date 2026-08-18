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
        parsed[path.name] = yaml.safe_load(path.read_text())  # raises on invalid YAML
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
    ci = (WORKFLOW_DIR / "ci.yml").read_text()
    guard = ci[ci.index("Guard against Windows-invalid submodule filenames"):]
    guard = guard[: guard.index("Setup Python")]
    assert "KNOWN" not in guard, "guard allowlist reintroduced; match real paths or drop it"
    assert "ui-ref" not in guard, "stale #441 offender referenced in the guard"
