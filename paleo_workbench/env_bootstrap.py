"""Ensure geo-viz-engine is importable without a manual PYTHONPATH (ISS-ENV-01).

Preferred setup (editable installs from the repo root)::

    python -m pip install -e .
    python -m pip install -r requirements-geoviz.txt

When packages are not installed, this module prepends the submodule package
roots from a source checkout so ``import geoviz`` works for the workbench
entry point and other ``paleo_workbench`` imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BOOTSTRAPPED = False

# Same layout as pyproject.toml [tool.pytest.ini_options].pythonpath
_GEOVIZ_RELATIVE_PATHS = (
    "geo-viz-engine",
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


def _repo_root() -> Path | None:
    """Locate the monorepo root that contains ``geo-viz-engine/geoviz``."""
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        candidate = parent / "geo-viz-engine" / "geoviz" / "__init__.py"
        if candidate.is_file():
            return parent
    return None


def _geoviz_importable() -> bool:
    try:
        import geoviz  # noqa: F401

        return True
    except ImportError:
        return False


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
    return {
        "importable": _geoviz_importable(),
        "bootstrapped": _BOOTSTRAPPED,
        "repo_root": str(root) if root else None,
        "preferred_install": "python -m pip install -r requirements-geoviz.txt",
    }
