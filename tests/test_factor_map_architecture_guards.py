"""Architecture guards for the single-factor-map production path (Phase A).

These guards are **static (AST-based)**: they parse source files without importing them,
so they enforce the architecture boundary even where the runtime toolchain (PySide6 /
the C++ extensions) is unavailable — including in restricted CI runners.

They defend the rules from the native factor-map goal:

* Haiyou stays **algorithm-only**: no ``PyQt6`` and no Haiyou GUI/canvas may enter the
  host production code; the constrained-IDW adapter remains the *only* host entry point
  into the vendored algorithm.
* The renderer-facing contract (``factor_grid_result.py``) stays GUI-free so the native
  rasteriser can consume it without Qt.
* Production factor-map files do not pull in a matplotlib/Qt display canvas as their
  rendering surface (the display path is reserved for the native renderer).

Run as pytest in CI, or directly (``python3 tests/test_factor_map_architecture_guards.py``)
for environment-free verification.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOST_PKG = REPO_ROOT / "paleo_workbench"
VENDORED = HOST_PKG / "_vendored"

# The single host module permitted to import the vendored Haiyou algorithm.
HAIYOU_ADAPTER = Path("workflow/constrained_idw_adapter.py")

# Production factor-map modules whose import surface is guarded.
FACTOR_PRODUCTION_FILES = {
    Path("workflow/factor_interpolation.py"),
    Path("workflow/factor_grid_result.py"),
    Path("workflow/constrained_idw_adapter.py"),
    Path("workflow/constraints.py"),
    Path("workflow/contour_draft.py"),
    Path("workflow/factors.py"),
}

# Modules whose import means "GUI display canvas" — forbidden as a factor-map surface.
CANVAS_IMPORT_PREFIXES = (
    "matplotlib.pyplot",
    "matplotlib.figure",
    "matplotlib.backends",
    "PyQt6",
)


def _iter_host_py_files():
    """Yield ``(relpath, Path)`` for every ``.py`` under the host package, excluding the
    vendored algorithm tree and bytecode caches."""
    for p in HOST_PKG.rglob("*.py"):
        rel = p.relative_to(HOST_PKG)
        if rel.parts and rel.parts[0] == "_vendored":
            continue
        if "__pycache__" in p.parts:
            continue
        yield rel, p


def _imports(tree: ast.AST):
    """Yield ``(module_root, statement)`` for each top-level import in ``tree``."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield (alias.name.split(".")[0], alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod:
                yield (mod.split(".")[0], mod)


def _parse(rel: Path, p: Path) -> ast.AST:
    try:
        return ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
    except SyntaxError as err:  # pragma: no cover - surfaced as a test failure
        raise AssertionError(f"cannot parse {rel}: {err}") from err


# --- guards -------------------------------------------------------------------


def test_no_pyqt6_in_host_production_code():
    """``PyQt6`` must never be imported by host production code (the app is PySide6).

    The vendored tree is the only exception, and even there it should eventually be
    removed (see findings §3 caveat 1). Today the two guarded lazy imports live under
    ``_vendored/`` which this scan excludes.
    """
    violations = []
    for rel, p in _iter_host_py_files():
        for root, mod in _imports(_parse(rel, p)):
            if mod.startswith("PyQt6"):
                violations.append(f"{rel}: imports {mod}")
    assert not violations, "PyQt6 leaked into host production code:\n  " + "\n  ".join(
        violations
    )


def test_haiyou_algorithm_only_via_adapter():
    """The vendored Haiyou algorithm may be imported only from the constrained-IDW
    adapter. No other host module may reach into ``drawing.*`` / ``haiyou*``."""
    violations = []
    for rel, p in _iter_host_py_files():
        for root, mod in _imports(_parse(rel, p)):
            if mod.startswith("drawing") or mod.startswith("haiyou"):
                if rel != HAIYOU_ADAPTER:
                    violations.append(f"{rel}: imports {mod}")
    assert not violations, (
        "Haiyou algorithm imported outside the adapter (boundary break):\n  "
        + "\n  ".join(violations)
    )


def test_factor_production_files_have_no_gui_canvas_import():
    """Factor-map production files must not import a matplotlib/PyQt6 display canvas —
    the display surface is reserved for the native renderer."""
    missing = [rel for rel in FACTOR_PRODUCTION_FILES if not (HOST_PKG / rel).exists()]
    # Do not fail simply because a file was renamed; report and skip.
    present = [rel for rel in FACTOR_PRODUCTION_FILES if (HOST_PKG / rel).exists()]
    violations = []
    for rel in present:
        for root, mod in _imports(_parse(rel, HOST_PKG / rel)):
            if any(mod.startswith(pre) for pre in CANVAS_IMPORT_PREFIXES):
                violations.append(f"{rel}: imports {mod}")
    assert not violations, (
        "factor-map production file imports a GUI canvas:\n  " + "\n  ".join(violations)
    )
    # Surface renames so the guard set stays accurate.
    assert not missing, f"guard references missing files (update the set): {missing}"


def test_factor_grid_result_contract_is_gui_free():
    """The renderer-facing ``FactorGridResult`` contract must depend only on numpy +
    the standard library, so the native C++ rasteriser can consume it without Qt.
    This protects the data/style boundary: style lives on the layer, not the result."""
    contract = HOST_PKG / "workflow/factor_grid_result.py"
    tree = _parse(contract.relative_to(HOST_PKG), contract)
    allowed_roots = {"__future__", "math", "dataclasses", "typing", "numpy", "np"}
    violations = []
    for root, mod in _imports(tree):
        if root not in allowed_roots:
            violations.append(f"factor_grid_result.py: imports {mod}")
    assert not violations, (
        "FactorGridResult has a non-stdlib/numpy import (breaks GUI-free contract):\n  "
        + "\n  ".join(violations)
    )


if __name__ == "__main__":  # environment-free local verification
    guards = {
        "no_pyqt6_in_host": test_no_pyqt6_in_host_production_code,
        "haiyou_only_via_adapter": test_haiyou_algorithm_only_via_adapter,
        "factor_files_no_gui_canvas": test_factor_production_files_have_no_gui_canvas_import,
        "contract_is_gui_free": test_factor_grid_result_contract_is_gui_free,
    }
    failed = 0
    for name, fn in guards.items():
        try:
            fn()
            print(f"[PASS] {name}")
        except AssertionError as err:
            failed += 1
            print(f"[FAIL] {name}\n       {err}")
    print(f"\n{len(guards) - failed}/{len(guards)} guards passed")
    raise SystemExit(1 if failed else 0)
