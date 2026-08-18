"""Regression tests for #825 (seismic LOD ladder), #829 (FLAC3D/Abaqus hex
export), and #846 (viz correlation/modeling library batch)."""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from paleo_workbench.viz.formation_volume import FormationVolumeIntegrator
from paleo_workbench.viz.fault_displacement import FaultDisplacement
from paleo_workbench.viz.geomodel.exporters import (
    _generate_structured_grid,
    export_to_abaqus,
    export_to_flac3d,
)
from paleo_workbench.viz.geomodel.models import GridSpec
from paleo_workbench.viz.horizon_sculpting import SculptableHorizonMesh
from paleo_workbench.viz.seismic_volume_cache import reset_global_seismic_cache
from paleo_workbench.viz.seismic_volume_source import (
    SeismicVolumeSource,
    clear_seismic_source_registry,
)
from paleo_workbench.viz.stratigraphic_correlation_engine import (
    StratigraphicCorrelationEngine,
)


@pytest.fixture(autouse=True)
def _clean_seismic():
    clear_seismic_source_registry()
    reset_global_seismic_cache()
    yield
    clear_seismic_source_registry()
    reset_global_seismic_cache()


# --------------------------------------------------------------------------- #
# #825 — LOD ladder
# --------------------------------------------------------------------------- #
def _mini_segy(path: Path, n_il: int, n_xl: int, n_s: int) -> Path:
    segyio = pytest.importorskip("segyio")
    spec = segyio.spec()
    spec.sorting = 2
    spec.format = 1
    spec.samples = list(range(n_s))
    spec.ilines = list(range(1, n_il + 1))
    spec.xlines = list(range(1, n_xl + 1))
    with segyio.create(str(path), spec) as f:
        for ili, il in enumerate(spec.ilines):
            for xli, xl in enumerate(spec.xlines):
                tr = np.linspace(0.0, 1.0, n_s, dtype=np.float32) + 0.01 * ili
                f.header[ili * n_xl + xli] = {
                    segyio.TraceField.INLINE_3D: il,
                    segyio.TraceField.CROSSLINE_3D: xl,
                }
                f.trace[ili * n_xl + xli] = tr
    return path


def test_lod1_delivers_finer_shape_with_single_read(tmp_path: Path) -> None:
    """A 300-inline survey: LOD1 strides (2,1,1) give a 150-strong axis (>128)
    — the module-default 128 clamp used to truncate it and raise."""
    segy = _mini_segy(tmp_path / "lod.sgy", n_il=300, n_xl=8, n_s=16)
    src = SeismicVolumeSource(segy)
    try:
        vol, strides, _warning = src.read_lod_volume_with_strides(level=1)
        assert vol is not None
        assert strides == (2, 1, 1)
        assert tuple(int(x) for x in vol.shape) == (150, 8, 16)
        assert max(vol.shape) > 128  # genuinely finer than the L0 budget
        assert src.physical_reads == 1  # no discarded read + fallback re-read
    finally:
        src.close()


def test_lod2_delivers_native_axis_shape(tmp_path: Path) -> None:
    segy = _mini_segy(tmp_path / "lod2.sgy", n_il=300, n_xl=8, n_s=16)
    src = SeismicVolumeSource(segy)
    try:
        vol, strides, _warning = src.read_lod_volume_with_strides(level=2)
        assert vol is not None
        assert strides == (1, 1, 1)
        assert tuple(int(x) for x in vol.shape) == (300, 8, 16)
        assert src.physical_reads == 1
    finally:
        src.close()


def test_lod2_scheduled_after_lod1(qtbot) -> None:
    """The ladder must continue past level 1 (#825: dead code before)."""
    from paleo_workbench.viz.joint_host import WellSeismicJointHost

    host = WellSeismicJointHost()  # QObject, not a widget
    started: list[int] = []
    host._start_next_lod_worker = lambda path, next_lod=1: started.append(next_lod)

    host._maybe_start_next_lod("x.sgy", 1)
    assert started == [2]  # pre-fix: early return, nothing scheduled
    host._maybe_start_next_lod("x.sgy", 2)
    assert started == [2]  # ladder ends at level 2


def test_lod2_scheduled_via_release_path(qtbot) -> None:
    from paleo_workbench.viz.joint_host import WellSeismicJointHost

    host = WellSeismicJointHost()  # QObject, not a widget
    started: list[int] = []
    host._start_next_lod_worker = lambda path, next_lod=1: started.append(next_lod)

    host._volume_phase = "L1_READY"
    host._volume_lod = 1
    host._paths = SimpleNamespace(segy=Path("x.sgy"), source="x")
    host._on_volume_job_released()
    assert started == [2]  # pre-fix: only "L0_READY" was accepted here


# --------------------------------------------------------------------------- #
# #829 — FLAC3D / Abaqus hex export
# --------------------------------------------------------------------------- #
# Faces listed OUTWARD-oriented (bottom reversed: CCW seen from outside,
# i.e. from below) so Newell normals point away from the element centroid.
_C3D8_FACES = (
    (0, 3, 2, 1),  # bottom (normal -z)
    (4, 5, 6, 7),  # top (normal +z)
    (0, 1, 5, 4),
    (1, 2, 6, 5),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
)


def _newell_normal(points: np.ndarray) -> np.ndarray:
    n = np.zeros(3)
    for i in range(len(points)):
        a, b = points[i], points[(i + 1) % len(points)]
        n += np.cross(a, b)
    return n


def test_structured_grid_elements_have_outward_faces_and_volume() -> None:
    """C3D8 face-cyclic order: every face's Newell normal points away from the
    element centroid, and the closed-surface divergence volume is a positive
    fraction of dx*dy*dz (a bowtie order gives 0)."""
    nodes, elements = _generate_structured_grid(GridSpec(3, 3, 3, 10.0, 10.0, 10.0))
    for elem in elements[:5]:
        pts = nodes[elem]
        centroid = pts.mean(axis=0)
        vol6 = 0.0
        for face_ids in _C3D8_FACES:
            quad = pts[list(face_ids)]
            normal = _newell_normal(quad)
            face_center = quad.mean(axis=0)
            assert float(np.dot(normal, face_center - centroid)) > 0.0, (
                f"face {face_ids} normal points inward — bowtie connectivity"
            )
            for tri in ((0, 1, 2), (0, 2, 3)):
                a, b, c = quad[list(tri)]
                vol6 += float(np.dot(a, np.cross(b, c)))
        volume = vol6 / 6.0
        assert volume > 0.5 * 1000.0 and volume < 2.0 * 1000.0, (
            f"closed-surface volume {volume} far from dx*dy*dz=1000 (bowtie → 0.0)"
        )


def test_trilinear_volume_matches_divergence_volume() -> None:
    """Independent oracle: integrate det(J) of the trilinear map numerically
    and compare with the exported connectivity's divergence volume."""
    nodes, elements = _generate_structured_grid(GridSpec(2, 2, 2, 10.0, 12.0, 8.0))
    elem = elements[0]
    pts = nodes[elem]
    # C3D8 corner order ↔ trilinear (xi, eta, zeta) bits.
    corner_coords = np.array(
        [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
         [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], dtype=float
    )
    step = 0.02
    total = 0.0
    for xi in np.arange(0.0, 1.0, step):
        for eta in np.arange(0.0, 1.0, step):
            for zeta in np.arange(0.0, 1.0, step):
                jac = np.zeros((3, 3))
                for d, (du, dv, dw) in enumerate(
                    ((step * 0.5, 0.0, 0.0), (0.0, step * 0.5, 0.0), (0.0, 0.0, step * 0.5))
                ):
                    p_plus = _trilinear_point(pts, corner_coords, xi + du, eta + dv, zeta + dw)
                    p_minus = _trilinear_point(pts, corner_coords, xi - du, eta - dv, zeta - dw)
                    jac[:, d] = (p_plus - p_minus) / step
                total += float(np.linalg.det(jac)) * step**3
    vol6 = 0.0
    for face_ids in _C3D8_FACES:
        quad = pts[list(face_ids)]
        for tri in ((0, 1, 2), (0, 2, 3)):
            a, b, c = quad[list(tri)]
            vol6 += float(np.dot(a, np.cross(b, c)))
    divergence_volume = vol6 / 6.0
    assert divergence_volume == pytest.approx(total, rel=0.05)


def _trilinear_point(pts, corner_coords, xi, eta, zeta):
    weights = (
        (1 - corner_coords[:, 0] - xi + 2 * xi * corner_coords[:, 0])
        * (1 - corner_coords[:, 1] - eta + 2 * eta * corner_coords[:, 1])
        * (1 - corner_coords[:, 2] - zeta + 2 * zeta * corner_coords[:, 2])
    )
    return weights @ pts


def test_flac3d_export_uses_itasca_grid_keywords(tmp_path: Path) -> None:
    out = tmp_path / "grid.f3grid"
    assert export_to_flac3d(str(out), nx=2, ny=2, nz=2, dx=5.0, dy=5.0, dz=5.0)
    lines = out.read_text(encoding="utf-8").splitlines()
    gp = [ln for ln in lines if ln.startswith("G ")]
    zones = [ln for ln in lines if ln.startswith("Z B8 ")]
    assert len(gp) == 27 and len(zones) == 8
    assert not any(ln.startswith("GRID ") for ln in lines)
    assert not any(ln.startswith("ZON ") for ln in lines)
    for zone in zones:
        ids = [int(tok) for tok in zone.split()[3:]]
        assert len(ids) == 8
        assert all(1 <= i <= 27 for i in ids)  # 1-based gridpoint references


def test_abaqus_export_c3d8_connectivity_matches_flac3d(tmp_path: Path) -> None:
    f3 = tmp_path / "g.f3grid"
    inp = tmp_path / "g.inp"
    export_to_flac3d(str(f3), nx=2, ny=2, nz=2, dx=5.0, dy=5.0, dz=5.0)
    export_to_abaqus(str(inp), nx=2, ny=2, nz=2, dx=5.0, dy=5.0, dz=5.0)
    f3_zones = [
        [int(tok) for tok in ln.split()[3:]]
        for ln in f3.read_text(encoding="utf-8").splitlines()
        if ln.startswith("Z B8 ")
    ]
    inp_zones = []
    in_elements = False
    for ln in inp.read_text(encoding="utf-8").splitlines():
        if ln.upper().startswith("*ELEMENT"):
            in_elements = True
            continue
        if ln.startswith("*"):
            in_elements = False
            continue
        if in_elements and ln.strip():
            inp_zones.append([int(tok) for tok in ln.split(",")[1:]])
    assert inp_zones == f3_zones  # same connectivity, both 1-based


# --------------------------------------------------------------------------- #
# #846 — viz library batch
# --------------------------------------------------------------------------- #
def test_compute_closed_volume_requires_explicit_grid_shape() -> None:
    integrator = FormationVolumeIntegrator()
    n = 36  # both 4x9 and 6x6 — ambiguous, must not be guessed
    top = np.column_stack(
        [np.tile(np.arange(9.0), 4), np.repeat(np.arange(4.0), 9), np.full(n, 10.0)]
    )
    bot = top - 10.0
    with pytest.raises(ValueError, match="grid_shape"):
        integrator.compute_closed_volume(top, bot)


def test_compute_closed_volume_4x9_grid_not_square_inferred() -> None:
    integrator = FormationVolumeIntegrator()
    rows, cols = 4, 9
    xx, yy = np.meshgrid(np.arange(cols, dtype=float), np.arange(rows, dtype=float))
    top = np.column_stack([xx.ravel(), yy.ravel(), np.full(rows * cols, 10.0)])
    bot = top - 10.0
    volume = integrator.compute_closed_volume(top, bot, (rows, cols))
    # The prism spans (cols-1) x (rows-1) unit cells of thickness 10.
    assert volume == pytest.approx((cols - 1) * (rows - 1) * 1.0 * 1.0 * 10.0, rel=1e-6)


def test_fault_heave_sign_follows_throw_sign() -> None:
    fd = FaultDisplacement()
    verts = np.array([[5.0, 0.0, 0.0], [-5.0, 0.0, 0.0]])
    normal = fd.apply_fault_throw(verts, fault_line_x=0.0, throw_z=10.0, dip_deg=60.0)
    reverse = fd.apply_fault_throw(verts, fault_line_x=0.0, throw_z=-10.0, dip_deg=60.0)
    heave_normal = normal[0, 0] - 5.0
    heave_reverse = reverse[0, 0] - 5.0
    assert heave_normal == pytest.approx(10.0 / math.tan(math.radians(60.0)))
    assert heave_reverse == pytest.approx(-10.0 / math.tan(math.radians(60.0)))


def test_smooth_anneal_requires_grid_shape_and_records_sparse_patch() -> None:
    rows, cols = 6, 6
    x, y = np.meshgrid(np.arange(cols, dtype=float), np.arange(rows, dtype=float))
    z = np.zeros(rows * cols)
    z[14] = 5.0  # one bump; far corners stay flat through one smoothing pass
    verts = np.column_stack([x.ravel(), y.ravel(), z])
    mesh = SculptableHorizonMesh(verts)
    with pytest.raises(ValueError, match="grid_shape"):
        mesh.smooth_anneal()

    mesh.grid_shape = (rows, cols)
    before = mesh.vertices.copy()
    mesh.smooth_anneal(iterations=1)
    patch = mesh._undo_stack[-1]
    assert len(patch.indices) < rows * cols, "patch must be sparse, not arange(N)"
    unchanged = set(np.nonzero(mesh.vertices[:, 2] == before[:, 2])[0].tolist())
    assert unchanged, "fixture must contain vertices the pass leaves untouched"
    assert unchanged.isdisjoint(patch.indices.tolist())
    assert mesh.undo() is True
    np.testing.assert_array_equal(mesh.vertices, before)


def test_sculpt_brush_weight_is_zero_at_radius() -> None:
    x, y = np.meshgrid(np.arange(5, dtype=float), np.arange(5, dtype=float))
    verts = np.column_stack([x.ravel(), y.ravel(), np.zeros(25)])
    mesh = SculptableHorizonMesh(verts)
    mesh.sculpt_surface((0.0, 0.0), delta_z=10.0, radius=3.0)
    rim = np.hypot(mesh.vertices[:, 0], mesh.vertices[:, 1])
    rim_vertex = int(np.argmin(np.abs(rim - 3.0)))
    assert mesh.vertices[rim_vertex, 2] == pytest.approx(0.0, abs=1e-12)
    center = int(np.argmin(rim))
    assert mesh.vertices[center, 2] == pytest.approx(10.0)  # full delta at center


def _engine_with_depth_axes() -> StratigraphicCorrelationEngine:
    depths = np.arange(1000.0, 1004.5, 0.5)  # 9 samples, 1000..1004
    curve = np.array([1.0, 2.0, 1.5, 2.5, 3.0, 2.0, 1.0, 2.5, 3.5])
    wells = [
        {"name": "A", "curves": {"GR": curve}, "depths": {"GR": depths}},
        {"name": "B", "curves": {"GR": curve}, "depths": {"GR": depths}},
    ]
    return StratigraphicCorrelationEngine().with_wells(wells)


def test_recommend_top_uses_real_depth_axes() -> None:
    """Identical curves with a 1000-1004 m axis: the recommendation must land
    near the true 1004 m top, not the fabricated ~500 m legacy-grid value."""
    engine = _engine_with_depth_axes()
    rec = engine.recommend_top("A", "B", ref_top_depth=1004.0, curve_key="GR")
    assert 1000.0 <= rec.suggested_depth <= 1004.5
    assert abs(rec.suggested_depth - 1004.0) <= 1.0


def test_execute_fills_recommendations_and_alignments() -> None:
    engine = _engine_with_depth_axes()
    for w in engine._wells:
        w["tops"] = [{"name": "H1", "depth": 1002.0}]
    result = engine.execute(["H1"], curve_key="GR")
    assert ("A", "B") in result.alignments
    assert "H1@B" in result.recommendations
    rec = result.recommendations["H1@B"]
    assert 1000.0 <= rec.suggested_depth <= 1004.5


def test_correlation_polygons_accept_layers_spelling() -> None:
    from paleo_workbench.viz.formation_top_correlator import FormationTopCorrelator

    correlator = FormationTopCorrelator()
    well_a = {
        "name": "A",
        "layers": [
            {"lithology": "H1", "top": 10.0},
            {"lithology": "H2", "top": 20.0},
        ],
    }
    well_b = {
        "name": "B",
        "layers": [
            {"lithology": "H1", "top": 12.0},
            {"lithology": "H2", "top": 22.0},
        ],
    }
    polys = correlator.compute_correlation_polygons(
        well_a, well_b, x_a=0.0, x_b=100.0, top_names=["H1", "H2"]
    )
    assert polys, "'layers'/'top' spellings must produce polygons (was silently empty)"
