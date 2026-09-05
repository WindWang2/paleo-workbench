"""Native ABI gate (#1181): on-disk extension builds must match the running
interpreter, or fail loudly instead of degrading into silent skips.

Background: the repo pins requires-python >=3.12,<3.13, but a developer host
can accumulate cp313-built .so files (multi-interpreter drift, gitignored
build outputs). Every native consumer then falls into its pure-Python
fallback and ~90 contract/perf tests skip — a green suite with ~1.7% fake
coverage. CI rebuilds in place so CI stays honest; this gate makes a
mismatched LOCAL tree red with a rebuild pointer.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# module -> directory(s) holding its built extension, relative to repo root.
_NATIVE_MODULES: dict[str, tuple[str, ...]] = {
    "grid_render_core": ("native/grid_render_core",),
    "seismic_3d_core": ("native/seismic_3d_core",),
    "layer_model_core": ("native/layer_model_core",),
    "map_edit_core": ("native/map_edit_core", "native/map_edit_core/src"),
    "qgis_render_bridge": ("native/qgis_render_bridge",),
    "well_log_core": ("native/well_log_core",),
}

_TAG_RE = re.compile(r"\.(cpython-\d+)-")


def _built_files(module: str) -> list[Path]:
    found: list[Path] = []
    for rel in _NATIVE_MODULES[module]:
        d = REPO_ROOT / rel
        if d.is_dir():
            found.extend(sorted(d.glob(f"{module}*.so")))
    return found


def test_native_builds_match_running_interpreter():
    """Any on-disk .so for a native module must carry the running ABI tag.

    No .so on disk (pure source checkout) -> skip: nothing can shadow.
    A present but foreign-ABI build -> FAIL with a rebuild pointer, never a
    silent fallback + mass skip.
    """
    running = sys.implementation.cache_tag  # e.g. cpython-313
    missing_dirs = [
        m for m, rels in _NATIVE_MODULES.items()
        if not any((REPO_ROOT / r).is_dir() for r in rels)
    ]
    if missing_dirs:
        pytest.skip(f"native sources absent for {missing_dirs}")
    mismatches: list[str] = []
    for module in _NATIVE_MODULES:
        for so in _built_files(module):
            m = _TAG_RE.search(so.name)
            tag = m.group(1) if m else "<untagged>"
            if tag != running:
                mismatches.append(
                    f"{so.relative_to(REPO_ROOT)}: built for {tag}, "
                    f"running {running}"
                )
    assert not mismatches, (
        "native extension ABI drift (#1181) — rebuild for this interpreter, "
        "e.g. /opt/miniconda3/bin/python setup.py build_ext --inplace "
        "in each native/* dir (or pip install -e native/<mod>):\n"
        + "\n".join(mismatches)
    )
