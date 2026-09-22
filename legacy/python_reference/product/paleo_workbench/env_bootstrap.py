"""Ensure geo-viz-engine is importable without a manual PYTHONPATH (ISS-ENV-01).

Preferred setup (editable installs from the repo root)::

    python -m pip install -e .
    python -m pip install -r requirements-geoviz.txt

When packages are not installed, this module prepends the submodule package
roots from a source checkout so ``import geoviz`` works for the workbench
entry point and other ``paleo_workbench`` imports.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

_BOOTSTRAPPED = False
_LOCAL_ENV_LOADED = False
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Package roots only — same as pyproject.toml pytest.pythonpath.
# The bare geo-viz-engine root is inserted separately (and skipped when it
# contains committed cpython-*.so files that would shadow built extensions).
_GEOVIZ_RELATIVE_PATHS = (
    "geo-viz-engine/packages/geoviz_common",
    "geo-viz-engine/packages/geoviz_paleo_map",
    "geo-viz-engine/packages/geoviz_plots",
    "geo-viz-engine/packages/geoviz_seismic",
    "geo-viz-engine/packages/geoviz_well_log",
    "geo-viz-engine/packages/geoviz_cross_well",
    "geo-viz-engine/packages/geoviz_well_tie",
    "geo-viz-engine/packages/geoviz_well_seismic_3d",
    "geo-viz-engine/packages/geoviz_map",
)


_GEOVIZ_PACKAGES = (
    "geoviz_common",
    "geoviz_paleo_map",
    "geoviz_plots",
    "geoviz_seismic",
    "geoviz_well_log",
    "geoviz_cross_well",
    "geoviz_well_tie",
    "geoviz_well_seismic_3d",
    "geoviz_map",
)


def _find_candidate_repo_roots() -> list[Path]:
    """Gather candidate roots that may contain geo-viz-engine."""
    candidates: list[Path] = []

    # 1. Explicit environment variables
    for env_var in ("PALEO_REPO_ROOT", "GEOVIZ_ROOT"):
        val = os.environ.get(env_var, "").strip()
        if val:
            p = Path(val).resolve()
            if p not in candidates:
                candidates.append(p)

    # 2. Ancestors of this file (__file__)
    here = Path(__file__).resolve()
    for p in (here.parent, *here.parents):
        if p not in candidates:
            candidates.append(p)

    # 3. Ancestors of current working directory
    try:
        cwd = Path.cwd().resolve()
        for p in (cwd, *cwd.parents):
            if p not in candidates:
                candidates.append(p)
    except OSError:
        pass

    # 4. Git worktree gitdir resolution
    for base in candidates[:]:
        git_file = base / ".git"
        if git_file.is_file():
            try:
                content = git_file.read_text(encoding="utf-8").strip()
                if content.startswith("gitdir:"):
                    gitdir_str = content.split(":", 1)[1].strip()
                    gitdir = (base / gitdir_str).resolve()
                    bare_root = gitdir.parent.parent
                    parent_of_bare = bare_root.parent
                    for sibling in (bare_root, parent_of_bare):
                        if sibling.is_dir() and sibling not in candidates:
                            candidates.append(sibling)
                        if sibling.is_dir():
                            for child in sibling.iterdir():
                                if child.is_dir() and child not in candidates:
                                    candidates.append(child)
            except OSError:
                pass

    return candidates


def _repo_root() -> Path | None:
    """Locate the monorepo root that contains ``geo-viz-engine/geoviz``."""
    seen: set[Path] = set()
    for root in _find_candidate_repo_roots():
        if root in seen:
            continue
        seen.add(root)
        candidate = root / "geo-viz-engine" / "geoviz" / "__init__.py"
        if candidate.is_file():
            return root
    return None


def check_geoviz_subpackages() -> dict[str, bool]:
    """Check import status of all known geoviz subpackages."""
    status: dict[str, bool] = {}
    for pkg in _GEOVIZ_PACKAGES:
        try:
            __import__(pkg)
            status[pkg] = True
        except ImportError:
            status[pkg] = False
    return status


def _engine_root_has_native_so(engine_root: Path) -> bool:
    """True when the engine checkout root has a committed native binary."""
    return any(engine_root.glob("*.so")) or any(engine_root.glob("*.pyd"))


def _geoviz_importable() -> bool:
    try:
        import geoviz  # noqa: F401

        return True
    except ImportError:
        return False


def load_local_env() -> bool:
    """Load the repository-local ignored ``.env`` file once, if it exists.

    Shell/desktop-launcher environment variables always win. The parser only
    accepts ``KEY=value`` lines, avoiding a runtime dependency and never
    executing shell syntax from a local configuration file.
    """
    global _LOCAL_ENV_LOADED
    if _LOCAL_ENV_LOADED:
        return False
    _LOCAL_ENV_LOADED = True

    root = _repo_root()
    path = root / ".env" if root is not None else None
    if path is None or not path.is_file():
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False

    loaded = False
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not _ENV_KEY_RE.fullmatch(key) or key in os.environ:
            continue
        os.environ[key] = _dotenv_value(raw_value)
        loaded = True
    return loaded


def _dotenv_value(value: str) -> str:
    """Decode the small, non-executing subset of dotenv values we accept."""
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text.split(" #", 1)[0].rstrip()


def ensure_geoviz_on_path() -> bool:
    """Make ``import geoviz`` (and monorepo geoviz_* packages) succeed from a source checkout.

    Always prepends checkout package roots when the monorepo layout is found, so
    newly added packages (e.g. geoviz_well_seismic_3d) are importable even if a
    partial ``geoviz`` install already exists on ``sys.path``.

    Returns True if geoviz is importable after the call. Returns False only when
    neither install nor checkout layout is available.
    """
    global _BOOTSTRAPPED

    root = _repo_root()
    if root is not None:
        engine_root = root / "geo-viz-engine"
        if engine_root.is_dir() and not _engine_root_has_native_so(engine_root):
            text = str(engine_root)
            if text not in sys.path:
                sys.path.insert(0, text)
        for rel in _GEOVIZ_RELATIVE_PATHS:
            path = root / rel
            if not path.is_dir():
                continue
            text = str(path)
            if text not in sys.path:
                sys.path.insert(0, text)

    ok = _geoviz_importable()
    if ok:
        _BOOTSTRAPPED = True
    return ok


def geoviz_bootstrap_status() -> dict[str, object]:
    """Diagnostic snapshot for docs / CLI health checks."""
    root = _repo_root()
    sub_status = check_geoviz_subpackages()
    return {
        "importable": _geoviz_importable(),
        "bootstrapped": _BOOTSTRAPPED,
        "repo_root": str(root) if root else None,
        "preferred_install": "python -m pip install -r requirements-geoviz.txt",
        "subpackages": sub_status,
        "missing_subpackages": [pkg for pkg, ok in sub_status.items() if not ok],
    }
