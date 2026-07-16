"""Independence of geoviz_* packages: declared deps, acyclic graph, core imports."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

import pytest

PACKAGES_ROOT = Path(__file__).resolve().parents[1] / "geo-viz-engine" / "packages"
CORE_FOR_WORKBENCH = (
    "geoviz_common",
    "geoviz_well_log",
    "geoviz_seismic",
    "geoviz_paleo_map",
    "geoviz_cross_well",
)
GEOVIZ_PUBLIC_FACADE = frozenset(
    {
        "ErrorCode",
        "GeoVizEngine",
        "GeoVizError",
        "PreparedPreview",
        "PreviewCapabilities",
        "PreviewKind",
        "PreviewOptions",
        "PreviewRegistry",
        "PreviewRequest",
        "PAYLOAD_SCHEMA_VERSION",
        "encode_prepared_preview",
        "decode_prepared_preview",
        # Documented compatibility exports used by existing workbench panels.
        "WellLogCanvas",
        "WellLogData",
        "CurveData",
        "build_qpainter_tracks",
        "load_las_preview",
        "export_svg",
        "export_pdf",
        "export_png",
        "SeismicView",
        "ProfileWidget",
        "SeismicLoader",
        "PaleoMapCanvas",
        "export_professional_figure",
        "CrossWellCanvas",
        "PlotWidget",
        "SurfaceWidget",
        "interpolate_idw",
        "interpolate_scipy",
        "extract_contour_lines",
        "extract_filled_contours",
        "FaciesData",
        "FaciesInterval",
        "IntervalItem",
        "LithologyInterval",
        "WellIntervals",
    }
)


def _workbench_geoviz_import_violations(root: Path) -> list[str]:
    violations = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "geoviz":
                    if any(item.name not in GEOVIZ_PUBLIC_FACADE for item in node.names):
                        violations.append(str(path.relative_to(root.parent)))
                elif node.module.startswith("geoviz.") or node.module.split(
                    ".", 1
                )[0].startswith("geoviz_"):
                    violations.append(str(path.relative_to(root.parent)))
            elif isinstance(node, ast.Import):
                if any(
                    item.name.startswith("geoviz.")
                    or item.name.split(".", 1)[0].startswith("geoviz_")
                    for item in node.names
                ):
                    violations.append(str(path.relative_to(root.parent)))
    return violations


def test_workbench_production_imports_only_geoviz_facade():
    root = Path(__file__).resolve().parents[1] / "paleo_workbench"
    violations = _workbench_geoviz_import_violations(root)
    assert not violations, violations


@pytest.mark.parametrize("private_name", ("engine", "previews"))
def test_workbench_rejects_private_names_imported_from_facade(
    tmp_path: Path, private_name: str
):
    package = tmp_path / "paleo_workbench"
    package.mkdir()
    package.joinpath("bad.py").write_text(
        f"from geoviz import {private_name}\n", encoding="utf-8"
    )

    assert _workbench_geoviz_import_violations(package) == [
        "paleo_workbench/bad.py"
    ]


def test_workbench_accepts_documented_facade_imports(tmp_path: Path):
    package = tmp_path / "paleo_workbench"
    package.mkdir()
    package.joinpath("good.py").write_text(
        "from geoviz import (\n"
        "    ErrorCode, GeoVizEngine, GeoVizError, PreparedPreview,\n"
        "    PreviewCapabilities, PreviewKind, PreviewOptions, PreviewRegistry,\n"
        "    PreviewRequest, PAYLOAD_SCHEMA_VERSION,\n"
        "    encode_prepared_preview, decode_prepared_preview,\n"
        "    WellLogCanvas, WellLogData, CurveData,\n"
        "    build_qpainter_tracks, SeismicView, ProfileWidget, PaleoMapCanvas,\n"
        "    CrossWellCanvas, PlotWidget, SurfaceWidget,\n"
        ")\n",
        encoding="utf-8",
    )

    assert _workbench_geoviz_import_violations(package) == []


def _pkg_dirs() -> list[Path]:
    return sorted(
        p for p in PACKAGES_ROOT.iterdir() if p.is_dir() and p.name.startswith("geoviz_")
    )


def _declared_geoviz_deps(pyproject: Path) -> set[str]:
    """Required (non-optional) geoviz_* dependencies from pyproject.toml."""
    text = pyproject.read_text(encoding="utf-8")
    # Split off optional-dependencies so we only parse hard deps.
    main = text.split("[project.optional-dependencies]")[0]
    # Only scan the dependencies = [ ... ] table, not project name/urls.
    deps_block = ""
    m = re.search(r"dependencies\s*=\s*\[(.*?)\]", main, flags=re.DOTALL)
    if m:
        deps_block = m.group(1)
    pkg_name = ""
    nm = re.search(r'name\s*=\s*["\']([^"\']+)["\']', main)
    if nm:
        pkg_name = nm.group(1).replace("-", "_")
    deps: set[str] = set()
    for hit in re.finditer(r'["\'](geoviz[-_][a-z0-9_-]+)["\']', deps_block):
        dep = hit.group(1).replace("-", "_")
        if dep != pkg_name:
            deps.add(dep)
    return deps


def _optional_geoviz_deps(pyproject: Path) -> set[str]:
    text = pyproject.read_text(encoding="utf-8")
    if "[project.optional-dependencies]" not in text:
        return set()
    opt = text.split("[project.optional-dependencies]", 1)[1]
    deps: set[str] = set()
    for m in re.finditer(r'["\'](geoviz[-_][a-z0-9_-]+)["\']', opt):
        deps.add(m.group(1).replace("-", "_"))
    return deps


def _production_imports(pkg_dir: Path, pkg_name: str) -> set[str]:
    src = pkg_dir / pkg_name
    found: set[str] = set()
    if not src.is_dir():
        return found
    for py in src.rglob("*.py"):
        if "tests" in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for mod in modules:
                top = mod.split(".")[0]
                if top.startswith("geoviz_") and top != pkg_name:
                    # Soft imports (inside try/except ImportError) still appear in AST;
                    # treat as OK if declared as optional OR required.
                    found.add(top)
    return found


def _hard_imports_outside_try(pkg_dir: Path, pkg_name: str) -> set[str]:
    """geoviz_* imports that are not nested under a try that catches ImportError."""
    src = pkg_dir / pkg_name
    hard: set[str] = set()
    if not src.is_dir():
        return hard
    for py in src.rglob("*.py"):
        if "tests" in py.parts:
            continue
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError:
            continue

        def walk(node, in_soft: bool = False):
            if isinstance(node, ast.Try):
                catches_import = any(
                    isinstance(h.type, ast.Name) and h.type.id == "ImportError"
                    or (
                        isinstance(h.type, ast.Tuple)
                        and any(
                            isinstance(e, ast.Name) and e.id == "ImportError"
                            for e in h.type.elts
                        )
                    )
                    for h in node.handlers
                    if h.type is not None
                )
                soft = in_soft or catches_import
                for child in node.body:
                    walk(child, soft)
                for h in node.handlers:
                    for child in h.body:
                        walk(child, in_soft)
                for child in node.orelse:
                    walk(child, in_soft)
                for child in node.finalbody:
                    walk(child, in_soft)
                return
            if isinstance(node, ast.Import):
                for a in node.names:
                    top = a.name.split(".")[0]
                    if top.startswith("geoviz_") and top != pkg_name and not in_soft:
                        hard.add(top)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top.startswith("geoviz_") and top != pkg_name and not in_soft:
                    hard.add(top)
            for child in ast.iter_child_nodes(node):
                walk(child, in_soft)

        walk(tree)
    return hard


def test_no_undeclared_hard_cross_package_imports():
    violations = []
    for pkg_dir in _pkg_dirs():
        name = pkg_dir.name
        required = _declared_geoviz_deps(pkg_dir / "pyproject.toml")
        optional = _optional_geoviz_deps(pkg_dir / "pyproject.toml")
        hard = _hard_imports_outside_try(pkg_dir, name)
        for dep in sorted(hard):
            if dep not in required and dep not in optional:
                violations.append(f"{name} hard-imports {dep} without declaring it")
            if dep not in required and dep in optional:
                # optional must only be soft-imported
                violations.append(
                    f"{name} hard-imports optional {dep}; must use try/except ImportError"
                )
    assert not violations, "\n".join(violations)


def test_geoviz_dependency_graph_is_acyclic():
    edges: set[tuple[str, str]] = set()
    for pkg_dir in _pkg_dirs():
        name = pkg_dir.name
        for dep in _hard_imports_outside_try(pkg_dir, name):
            if dep != name:
                edges.add((name, dep))
        for dep in _declared_geoviz_deps(pkg_dir / "pyproject.toml"):
            if dep != name:
                edges.add((name, dep))

    g: dict[str, set[str]] = defaultdict(set)
    nodes: set[str] = set()
    for a, b in edges:
        g[a].add(b)
        nodes.add(a)
        nodes.add(b)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}
    stack: list[str] = []
    found: list[list[str]] = []

    def dfs(u: str) -> None:
        color[u] = GRAY
        stack.append(u)
        for v in g.get(u, ()):
            if v == u:
                continue
            if color.get(v, WHITE) == GRAY:
                if v in stack:
                    found.append(stack[stack.index(v) :] + [v])
            elif color.get(v, WHITE) == WHITE:
                dfs(v)
        stack.pop()
        color[u] = BLACK

    for n in nodes:
        if color[n] == WHITE:
            dfs(n)
    assert not found, f"cycles: {found}"


@pytest.mark.parametrize("pkg", CORE_FOR_WORKBENCH)
def test_core_package_public_import(pkg: str):
    """Core packages used by workbench viz import under offscreen Qt."""
    import importlib

    mod = importlib.import_module(pkg)
    assert mod is not None
    # Primary surfaces
    if pkg == "geoviz_well_log":
        assert hasattr(mod, "WellLogCanvas")
    elif pkg == "geoviz_seismic":
        assert hasattr(mod, "SeismicView")
    elif pkg == "geoviz_paleo_map":
        assert hasattr(mod, "PaleoMapCanvas")
    elif pkg == "geoviz_cross_well":
        assert hasattr(mod, "CrossWellCanvas")
