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
# Documented private-API usage that the public facade intentionally cannot
# cover: underscore-prefixed C++ acceleration hooks (map_edit) and the
# type-checking-only import of WellSeismicScene (never executed at runtime).
PRIVATE_API_EXEMPTIONS: frozenset[tuple[str, None]] = frozenset(
    {
        ("geoviz_plots.map_edit.api", None),
        ("geoviz_well_seismic_3d", None),
    }
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
        "WellSectionCanvas",
        "DatumTransformer",
        "WellLogData",
        "CurveData",
        "LineStyle",
        "build_qpainter_tracks",
        "load_las_preview",
        "load_xml_preview",
        "inspect_las_file",
        "curve_data_from_arrays",
        "compute_robust_display_range",
        "export_svg",
        "export_pdf",
        "export_png",
        "SeismicView",
        "ProfileWidget",
        "SeismicLoader",
        "PaleoMapCanvas",
        "FaciesHierarchy",
        "export_professional_figure",
        "CrossWellCanvas",
        "WellTieCanvas",
        # Sonic slowness unit normalization. The single unit table, now called
        # by viz/hosts/well_tie_host instead of a private host copy that could
        # not recognise the µ/μ spellings (#879).
        "normalize_sonic_units",
        "PlotWidget",
        "SurfaceWidget",
        "XYPreviewPayload",
        "interpolate_idw",
        "interpolate_scipy",
        "azimuth_to_rad",
        "directional_distance",
        "directional_trend_grid",
        "directional_weights",
        "rotate_to_uv",
        "trend_value_at",
        "compute_sand_ratio",
        "median_absolute_deviation",
        "modified_z_scores",
        "CancellationToken",
        "JobCancelled",
        "validate_polygon_geometry",
        "extract_contour_lines",
        "extract_filled_contours",
        "ContourSegment",
        "DEFAULT_N_LEVELS",
        "GENERATOR_VERSION",
        "coerce_grid",
        "extract_contour_segments",
        "segments_to_line_features",
        "suggest_levels",
        "DEFAULT_FACTOR_TYPES",
        "DEFAULT_GRID_N",
        "DEFAULT_SEMI_MAJOR",
        "DEFAULT_SEMI_MINOR",
        "MAX_LOO_SAMPLES",
        "extract_xy_values",
        "extract_xy_z_weights",
        "interpolate_factor_grid",
        "method_to_backend",
        "mvp_note_for",
        "resolve_anisotropy_params",
        "snapshot_hash",
        "synthetic_sample_points",
        "FeatureEditor",
        "HAS_CPP",
        "HAS_SHAPELY",
        "SnapCandidateIndex",
        "TopologyError",
        "closest_edge",
        "delete_vertex",
        "hit_test",
        "insert_vertex",
        "merge_rings",
        "move_features",
        "rebuild_topology",
        "set_vertex",
        "snap_point",
        "snap_point_indexed",
        "snap_shared_nodes",
        "split_ring_by_line",
        "validate_adjacency",
        "validate_ring",
        "CrossWellFenceGenerator",
        "generate_fence_mesh",
        # 阶段 1 engine sink-down (docs/agents/geo-viz-boundary.md): the whole
        # viz/geomodel engine core moved into geo-viz-engine. Only the business
        # advisor + FLAC3D/Abaqus exporters stayed in the workbench.
        "BoreholeTraceGenerator",
        "ClippedGLMeshItem",
        "ClippedGLVolumeItem",
        "FaultCuttingEngine",
        "TunnelMeshGenerator",
        "analyze_lithology_crossplot",
        "blend_rgba",
        "build_proportional_surfaces",
        "build_synthetic_seismogram_overlay",
        "correlate_synthetic_to_trace",
        "extract_stratal_slice",
        "generate_cylinder_geometry",
        "generate_fault_geometry",
        "generate_tube_geometry",
        "get_seam_boundaries",
        "offset_curve_along_trajectory",
        "shift_depths",
        "stratal_slice_volume",
        "synthetic_from_logs",
        "validate_horizon_pair",
        # Phase-2 PR-A #32: BandedFill + FilledContourLayer + CRS helpers (T2/T3).
        "BandedFill",
        "FilledContourLayer",
        "coerce_to_project_crs",
        "get_project_crs",
        "list_known_crs",
        "set_project_crs",
        # Phase-2 PR-A #32: plan_section facade re-export (T5).
        "plan_section",
        "FaciesData",
        "FaciesInterval",
        "FormationTop",
        "HorizonAxes",
        "HorizonParser",
        "IntervalItem",
        "LithologyInterval",
        "WellIntervals",
        "set_downsample_provider",
        "get_downsample_provider",
        "numpy_minmax_downsample",
        "set_las_parser_provider",
        "get_las_parser_provider",
        "set_isosurface_extractor",
        "get_isosurface_extractor",
        "WellSeismicScene",
        # Pre-existing drift fix (documented on #256): well-seismic joint 3D
        # names the facade exports but the allow-list was missing.
        "JointDisplaySettings",
        "JointWellId",
        "OrthogonalSliceState",
        "TimeSliceState",
        "WellSeismicJointWidget",
        "WellHead",
        "TimeDepthTable",
        "InMemoryVolumeAccess",
        "VerticalDomain",
        "FenceSection",
        "VolumeRegistration",
        "survey_corners_from_segy",
        "horizon_corners_from_dat",
        "align_horizon_corners_to_loader_axes",
        "select_depth_transform",
    }
)


def _workbench_geoviz_import_violations(root: Path) -> list[str]:
    violations = []
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        _attach_parents(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if _is_type_checking_guarded(node):
                    continue
                if node.module == "geoviz":
                    if any(item.name not in GEOVIZ_PUBLIC_FACADE for item in node.names):
                        violations.append(str(path.relative_to(root.parent)))
                elif node.module.startswith("geoviz.") or node.module.split(
                    ".", 1
                )[0].startswith("geoviz_"):
                    if (node.module, None) not in PRIVATE_API_EXEMPTIONS:
                        violations.append(str(path.relative_to(root.parent)))
            elif isinstance(node, ast.Import):
                for item in node.names:
                    if _is_type_checking_guarded(node):
                        continue
                    if item.name.startswith("geoviz.") or item.name.split(
                        ".", 1
                    )[0].startswith("geoviz_"):
                        if (item.name, None) not in PRIVATE_API_EXEMPTIONS:
                            violations.append(str(path.relative_to(root.parent)))
    return violations


def _is_type_checking_guarded(node: ast.AST) -> bool:
    """True when the import sits under ``if TYPE_CHECKING:`` (no runtime cost)."""
    parent = node
    while parent is not None:
        if (
            isinstance(parent, ast.If)
            and isinstance(parent.test, ast.Name)
            and parent.test.id == "TYPE_CHECKING"
        ):
            return True
        parent = getattr(parent, "_parent", None)
    return False


def _attach_parents(tree: ast.AST) -> None:
    for child in ast.walk(tree):
        for field_child in ast.iter_child_nodes(child):
            field_child._parent = child


@pytest.mark.parametrize("root_name", ["paleo_workbench"])
def test_workbench_production_imports_only_geoviz_facade(root_name: str):
    """Workbench production code must import only the public facade.

    Phase-2 T1 (#245): the shared allow-list is enforced for the workbench.
    The Well Log Workstation moved out of this tree into the well-log-engine
    submodule (apps/wellplot-desktop/well_log_workstation); its imports are
    governed by that repo's own policy, not by this parent-repo test.
    """
    root = Path(__file__).resolve().parents[1] / root_name
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
