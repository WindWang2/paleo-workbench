"""Native ABI gate (#1181): on-disk extension builds and sys.path entries must
match the running interpreter, or fail loudly instead of degrading into silent skips.

Background: the repo pins requires-python >=3.12,<3.13, but a developer host
can accumulate cp313-built .so files (multi-interpreter drift, gitignored build
outputs, or stale editable .pth files pointing to another branch/tree). Every
native consumer then falls into its pure-Python fallback and ~90 contract/perf
tests skip — a green suite with ~1.7% fake coverage. CI rebuilds in place so
CI stays honest; this gate makes a mismatched LOCAL tree red with an informative
rebuild/cleanup pointer.
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

_TAG_RE = re.compile(r"\.(cpython-\d+[a-z]*|cp\d+[a-z]*)[.-]")
_EXT_PATTERNS = ("*.so", "*.pyd", "*.dylib")


def _normalize_abi_tag(tag: str) -> str:
    """Normalize Windows 'cp312' and POSIX 'cpython-312' tags for comparison."""
    if tag.startswith("cpython-"):
        return tag
    if tag.startswith("cp"):
        return "cpython-" + tag[2:]
    return tag


def _format_path(path: Path) -> str:
    """Format path relative to REPO_ROOT if inside, else absolute."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _get_sys_path_dirs() -> list[Path]:
    """Return all unique, existing directory Paths currently on sys.path."""
    dirs: list[Path] = []
    seen: set[Path] = set()
    for entry in sys.path:
        p = Path.cwd() if not entry else Path(entry)
        try:
            p = p.resolve()
        except (OSError, RuntimeError):
            continue
        if p.is_dir() and p not in seen:
            seen.add(p)
            dirs.append(p)
    return dirs


def test_native_builds_match_running_interpreter():
    """Any built .so/.pyd for a native module must carry the running ABI tag.

    Checks both in-tree directories relative to REPO_ROOT and any directory
    present on sys.path.
    """
    running = sys.implementation.cache_tag  # e.g. cpython-312
    missing_dirs = [
        m for m, rels in _NATIVE_MODULES.items()
        if not any((REPO_ROOT / r).is_dir() for r in rels)
    ]
    if missing_dirs:
        pytest.skip(f"native sources absent for {missing_dirs}")

    seen_dirs: set[Path] = set()
    search_dirs: list[Path] = []
    for module, rels in _NATIVE_MODULES.items():
        for rel in rels:
            d = (REPO_ROOT / rel).resolve()
            if d.is_dir() and d not in seen_dirs:
                seen_dirs.add(d)
                search_dirs.append(d)
    for p in _get_sys_path_dirs():
        if p not in seen_dirs:
            seen_dirs.add(p)
            search_dirs.append(p)

    mismatches: list[str] = []
    for d in search_dirs:
        for module in _NATIVE_MODULES:
            for pat in (f"{module}*.so", f"{module}*.pyd"):
                for so in d.glob(pat):
                    if so.name.endswith(".abi3.so") or so.name.endswith(".abi3.pyd"):
                        continue
                    m = _TAG_RE.search(so.name)
                    raw_tag = m.group(1) if m else "<untagged>"
                    tag = _normalize_abi_tag(raw_tag) if m else "<untagged>"
                    if tag != running:
                        mismatches.append(
                            f"{_format_path(so)}: built for {raw_tag}, running {running}"
                        )

    assert not mismatches, (
        "native extension ABI drift (#1181) — rebuild for this interpreter, "
        "e.g. /home/kevin/.conda/envs/paleo312/bin/python setup.py build_ext --inplace "
        "in each native/* dir (or pip install -e native/<mod>):\n"
        + "\n".join(mismatches)
    )


def test_sys_path_clean_of_foreign_abi():
    """Fail closed if any foreign-ABI shared library exists on sys.path.

    Scans all directories in sys.path (e.g. site-packages, editable .pth targets,
    PYTHONPATH entries) for binaries built against a different CPython ABI.
    """
    running = sys.implementation.cache_tag  # e.g. cpython-312
    mismatches: list[str] = []
    for d in _get_sys_path_dirs():
        for pat in _EXT_PATTERNS:
            for f in sorted(d.glob(pat)):
                if f.name.endswith(".abi3.so") or f.name.endswith(".abi3.pyd"):
                    continue
                m = _TAG_RE.search(f.name)
                if m:
                    raw_tag = m.group(1)
                    tag = _normalize_abi_tag(raw_tag)
                    if tag != running:
                        mismatches.append(
                            f"{_format_path(f)}: built for {raw_tag}, running {running} "
                            f"(found in sys.path directory {d})"
                        )

    assert not mismatches, (
        "foreign-ABI shared libraries detected on sys.path (#1181) — "
        "check for stale editable .pth files, PYTHONPATH overrides, or old build artifacts:\n"
        + "\n".join(mismatches)
    )


def test_geoviz_packages_resolve_to_active_worktree():
    """Verify that geoviz and all 9 subpackages load from the active worktree, not main."""
    import geoviz
    import geoviz_common
    import geoviz_cross_well
    import geoviz_map
    import geoviz_paleo_map
    import geoviz_plots
    import geoviz_seismic
    import geoviz_well_log
    import geoviz_well_seismic_3d
    import geoviz_well_tie

    subpkgs = [
        geoviz,
        geoviz_common,
        geoviz_cross_well,
        geoviz_map,
        geoviz_paleo_map,
        geoviz_plots,
        geoviz_seismic,
        geoviz_well_log,
        geoviz_well_seismic_3d,
        geoviz_well_tie,
    ]
    repo_root_str = str(REPO_ROOT.resolve())
    for mod in subpkgs:
        mod_file = getattr(mod, "__file__", "")
        assert mod_file.startswith(repo_root_str), (
            f"{mod.__name__} resolved outside active repo root ({mod_file} not in {repo_root_str})"
        )


