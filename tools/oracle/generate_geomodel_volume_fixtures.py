#!/usr/bin/env python3
"""Oracle for the CONV-12 geomodel geometric kernels.

Freezes the pure-geometry surface of:
  * paleo_workbench.viz.formation_volume  (Gauss-divergence closed volume)
  * paleo_workbench.viz.horizon_sculpting (Gaussian brush / laplacian anneal)
  * paleo_workbench.viz.fault_displacement(anchored throw / heave / decay)
  * paleo_workbench.viz.geomodel.builders (triangulation / curtain / volume
    shell / columnar hex mesh / station dedupe)
  * paleo_workbench.viz.geomodel.measurements (distance family / thickness /
    plane orientation / format_result)
  * paleo_workbench.viz.geomodel.section  (plane / clip equations / mesh and
    horizon intersections / well crossing)
  * paleo_workbench.viz.geomodel.qc       (numeric mesh cores only)

Every expectation is produced by calling the real modules — nothing is
hand-written. Run with the conv-12 oracle venv:
  PYTHONPATH=<repo root> PALEO_REPO_ROOT=<main checkout with geo-viz-engine> \
      oracle-venvs/conv12/bin/python tools/oracle/generate_geomodel_volume_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path  # noqa: E402

ensure_geoviz_on_path()

from paleo_workbench.viz.formation_volume import FormationVolumeIntegrator  # noqa: E402
from paleo_workbench.viz.fault_displacement import FaultDisplacement, FaultSpec  # noqa: E402
from paleo_workbench.viz.geomodel import builders  # noqa: E402
from paleo_workbench.viz.geomodel import measurements as meas  # noqa: E402
from paleo_workbench.viz.geomodel import qc as geomodel_qc  # noqa: E402
from paleo_workbench.viz.geomodel import section  # noqa: E402
from paleo_workbench.viz.horizon_sculpting import SculptableHorizonMesh  # noqa: E402

OUT = REPO_ROOT / "libs" / "geomodel" / "geomodel_tests" / "fixtures"

CRS = "EPSG:32650"


def jnum(v) -> float | None:
    """JSON-safe number: NaN/inf -> None (oracle convention: null = NaN)."""
    if v is None:
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def jarr(a) -> list:
    a = np.asarray(a)
    if a.ndim == 1:
        return [jnum(v) for v in a]
    return [jarr(row) for row in a]


def jverts(a) -> list:
    """(N,3) vertex array as [[x,y,z],...]."""
    return [[jnum(c) for c in row] for row in np.asarray(a)]


def jpts2(a) -> list:
    return [[jnum(c) for c in row] for row in np.asarray(a)]


def flat_grid(a, origin=(0.0, 0.0), spacing=(1.0, 1.0)) -> dict:
    """2-D grid -> {"rows", "cols", "origin", "spacing", "z" row-major}."""
    g = np.asarray(a, dtype=np.float64)
    return {"rows": int(g.shape[0]), "cols": int(g.shape[1]),
            "origin": [float(origin[0]), float(origin[1])],
            "spacing": [float(spacing[0]), float(spacing[1])],
            "z": [jnum(v) for v in g.reshape(-1)]}


def horizon(name, z_grid, origin=(0.0, 0.0), spacing=(10.0, 10.0),
            crs=CRS, vertical_domain="depth", unit="m"):
    """Real builder; object_id derives deterministically as horizon:<slug>."""
    return builders.build_horizon_from_grid(
        name, np.asarray(z_grid, dtype=np.float64),
        origin=origin, spacing=spacing, crs=crs,
        vertical_domain=vertical_domain, unit=unit,
    )


def raises(fn) -> str:
    """Return the exception message, or raise if nothing was raised."""
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - oracle freezes the message
        return str(exc)
    raise AssertionError("expected an exception")


def make_integrator():
    return FormationVolumeIntegrator()


def volume_cases(cases):
    integ = make_integrator()

    def box(n=11, span=10.0, top=100.0, bot=80.0, dtype=np.float32):
        x, y = np.meshgrid(np.linspace(0.0, span, n), np.linspace(0.0, span, n))
        top_z = np.full_like(x, top)
        bot_z = np.full_like(x, bot)
        return (np.column_stack([x.ravel(), y.ravel(), top_z.ravel()]).astype(dtype),
                np.column_stack([x.ravel(), y.ravel(), bot_z.ravel()]).astype(dtype))

    def add_volume(id_, top, bot, rows, cols, rtol):
        cases.append({
            "family": "volume", "id": id_,
            "top": jverts(top), "bot": jverts(bot),
            "rows": rows, "cols": cols, "rtol": rtol,
            "volume": float(integ.compute_closed_volume(top, bot, grid_shape=(rows, cols))),
        })

    top, bot = box()
    add_volume("box_11x11", top, bot, 11, 11, 1e-9)

    x, y = np.meshgrid(np.linspace(0, 10, 11), np.linspace(0, 10, 11))
    top = np.column_stack([x.ravel(), y.ravel(), (100.0 + 0.5 * x).ravel()]).astype(np.float32)
    bot = np.column_stack([x.ravel(), y.ravel(), (80.0 + 0.5 * x).ravel()]).astype(np.float32)
    add_volume("deformed_11x11", top, bot, 11, 11, 1e-9)

    rows, cols = 4, 9
    xx, yy = np.meshgrid(np.arange(cols, dtype=float), np.arange(rows, dtype=float))
    top = np.column_stack([xx.ravel(), yy.ravel(), np.full(rows * cols, 10.0)])
    bot = top - 10.0
    add_volume("grid_4x9", top.astype(np.float32), bot.astype(np.float32), rows, cols, 1e-9)

    utm_x = np.linspace(499900.0, 500100.0, 21)
    utm_y = np.linspace(3199900.0, 3200100.0, 21)
    xx, yy = np.meshgrid(utm_x, utm_y)
    top = np.column_stack([xx.ravel(), yy.ravel(), np.full(xx.size, 100.0)]).astype(np.float32)
    bot = np.column_stack([xx.ravel(), yy.ravel(), np.full(xx.size, 85.0)]).astype(np.float32)
    add_volume("utm_scale_float32", top, bot, 21, 21, 1e-9)

    top, bot = box(top=100.0, bot=100.0)
    add_volume("zero_thickness", top, bot, 11, 11, 1e-12)

    top, bot = box(top=80.0, bot=100.0)
    add_volume("inverted_abs", top, bot, 11, 11, 1e-9)

    t4 = np.column_stack([np.zeros(4), np.zeros(4), np.zeros(4)])
    b5 = np.column_stack([np.zeros(5), np.zeros(5), np.zeros(5)])
    cases.append({
        "family": "volume", "id": "err_shape_mismatch",
        "top": jverts(t4), "bot": jverts(b5), "rows": 2, "cols": 2,
        "raises": raises(lambda: integ.compute_closed_volume(t4, b5, grid_shape=(2, 2))),
    })
    x1, y1 = np.meshgrid(np.arange(5.0), np.arange(1.0))
    top1 = np.column_stack([x1.ravel(), y1.ravel(), np.full(5, 10.0)])
    bot1 = top1 - 5.0
    add_volume("degenerate_single_row", top1.astype(np.float32),
               bot1.astype(np.float32), 1, 5, 1e-9)

    t16 = np.column_stack([np.zeros(16), np.zeros(16), np.zeros(16)])
    b16 = t16.copy()
    cases.append({
        "family": "volume", "id": "err_grid_mismatch",
        "top": jverts(t16), "bot": jverts(b16), "rows": 5, "cols": 5,
        "raises": raises(lambda: integ.compute_closed_volume(t16, b16, grid_shape=(5, 5))),
    })


def _flat_verts(rows, cols, z=100.0, dtype=np.float32, x0=0.0, y0=0.0, step=1.0):
    x, y = np.meshgrid(np.arange(cols, dtype=dtype) * dtype(step) + dtype(x0),
                       np.arange(rows, dtype=dtype) * dtype(step) + dtype(y0))
    zq = np.full_like(x, dtype(z))
    return np.column_stack([x.ravel(), y.ravel(), zq.ravel()])


def sculpt_cases(cases):
    def mesh5(z=100.0):
        verts = _flat_verts(5, 5, z=z)
        return SculptableHorizonMesh(verts)

    # 1. brush: center full delta, rim exactly zero (#846)
    m = mesh5(100.0)
    m.sculpt_surface((0.0, 0.0), delta_z=10.0, radius=3.0)
    patch = m._undo_stack[-1]
    cases.append({
        "family": "sculpt", "id": "brush_center_rim_zero",
        "z": jarr(m.vertices[:, 2]), "z_tol": 1e-4,
        "patch_indices": [int(v) for v in patch.indices],
        "patch_new_z": jarr(patch.new_z), "patch_tol": 1e-4,
    })

    # 2. non-positive radius: no-op, no patch (#897)
    m = mesh5(100.0)
    out0 = m.sculpt_surface((0.5, 0.5), delta_z=-3.0, radius=0.0)
    outn = m.sculpt_surface((0.5, 0.5), delta_z=-3.0, radius=-1.0)
    cases.append({
        "family": "sculpt", "id": "nonpositive_radius_noop",
        "z": jarr(m.vertices[:, 2]), "z_tol": 0.0,
        "undo_depth": len(m._undo_stack),
        "returned_same": bool(out0 is m.vertices and outn is not None),
    })

    # 3. set_heights single patch
    m = mesh5(50.0)
    m.set_heights(np.array([3, 7]), np.array([-5.0, 2.5], dtype=np.float32))
    patch = m._undo_stack[-1]
    cases.append({
        "family": "sculpt", "id": "set_heights",
        "z": jarr(m.vertices[:, 2]), "z_tol": 0.0,
        "patch_indices": [int(v) for v in patch.indices],
        "patch_old_z": jarr(patch.old_z),
    })

    # 4. smooth anneal one bump: sparse patch + exact float32 result
    rows, cols = 6, 6
    x, y = np.meshgrid(np.arange(cols, dtype=float), np.arange(rows, dtype=float))
    z = np.zeros(rows * cols)
    z[14] = 5.0
    verts = np.column_stack([x.ravel(), y.ravel(), z])
    m = SculptableHorizonMesh(verts, grid_shape=(rows, cols))
    before = m.vertices.copy()
    m.smooth_anneal(iterations=1)
    patch = m._undo_stack[-1]
    cases.append({
        "family": "sculpt", "id": "anneal_sparse_patch",
        "z": jarr(m.vertices[:, 2]), "z_tol": 0.0,
        "patch_indices": [int(v) for v in patch.indices],
        "patch_new_z": jarr(patch.new_z), "patch_tol": 0.0,
        "sparse_lt_n": bool(len(patch.indices) < rows * cols),
        "undo_restores_exact": bool((lambda: (m.undo(), np.array_equal(m.vertices, before))[1])()),
    })

    # 5. smooth anneal 3 iterations on a deterministic pattern
    rng = np.random.default_rng(8)
    z_grid = rng.uniform(90.0, 110.0, size=(10, 10)).astype(np.float32)
    m = SculptableHorizonMesh(
        np.column_stack([np.arange(100, dtype=np.float32) * 0.0,
                         np.arange(100, dtype=np.float32) * 0.0, z_grid.ravel()]),
        grid_shape=(10, 10))
    m.smooth_anneal(iterations=3)
    cases.append({
        "family": "sculpt", "id": "anneal_3_iterations",
        "anneal_input": jarr(z_grid.ravel()),
        "z": jarr(m.vertices[:, 2]), "z_tol": 0.0,
    })

    # 5b. smooth anneal on an already-flat grid: zero-delta patch, no undo
    m = SculptableHorizonMesh(
        np.column_stack([np.zeros(36), np.zeros(36), np.full(36, 7.0)]),
        grid_shape=(6, 6))
    m.smooth_anneal(iterations=2)
    cases.append({
        "family": "sculpt", "id": "anneal_no_change",
        "z": jarr(m.vertices[:, 2]), "z_tol": 0.0,
        "undo_depth": len(m._undo_stack),
    })

    # 5c. set_heights with no indices: silent no-op
    m = mesh5(50.0)
    m.set_heights(np.array([], dtype=np.int64), np.array([], dtype=np.float32))
    cases.append({
        "family": "sculpt", "id": "set_heights_empty",
        "z": jarr(m.vertices[:, 2]), "z_tol": 0.0,
        "undo_depth": len(m._undo_stack),
    })

    # 5d. smooth_anneal with mismatched grid_shape: numpy reshape error
    m = SculptableHorizonMesh(
        np.column_stack([np.zeros(36), np.zeros(36), np.zeros(36)]),
        grid_shape=(6, 5))
    cases.append({
        "family": "sculpt", "id": "anneal_reshape_mismatch",
        "raises": raises(m.smooth_anneal),
    })

    # 6. anneal without grid_shape raises (#846)
    m = SculptableHorizonMesh(np.column_stack([np.zeros(36), np.zeros(36), np.zeros(36)]))
    cases.append({
        "family": "sculpt", "id": "anneal_requires_grid_shape",
        "raises": raises(m.smooth_anneal),
    })

    # 7. undo / redo round trip
    m = mesh5(50.0)
    can_undo_before = m.can_undo()
    m.sculpt_surface((2.0, 2.0), delta_z=15.0, radius=2.5)
    after_sculpt = m.vertices[:, 2].copy()
    did_undo = m.undo()
    after_undo = m.vertices[:, 2].copy()
    did_redo = m.redo()
    after_redo = m.vertices[:, 2].copy()
    cases.append({
        "family": "sculpt", "id": "undo_redo_roundtrip",
        "can_undo_before": bool(can_undo_before),
        "can_undo_after_sculpt": bool(m.can_undo()),
        "did_undo": bool(did_undo), "did_redo": bool(did_redo),
        "after_sculpt": jarr(after_sculpt), "after_undo": jarr(after_undo),
        "after_redo": jarr(after_redo), "z_tol": 1e-4,
    })

    # 8. sculpt with no vertices inside the radius: no patch, redo intact
    m = mesh5(50.0)
    m.sculpt_surface((2.0, 2.0), delta_z=1.0, radius=2.0)  # patches + clears redo
    m.undo()
    m.redo()  # redo stack now empty again, undo has 1 patch
    m.sculpt_surface((1000.0, 1000.0), delta_z=5.0, radius=3.0)
    cases.append({
        "family": "sculpt", "id": "sculpt_outside_no_patch",
        "z": jarr(m.vertices[:, 2]), "z_tol": 1e-4,
        "undo_depth": len(m._undo_stack),
        "can_undo": bool(m.can_undo()), "can_redo": bool(m.can_redo()),
    })


def fault_cases(cases):
    engine = FaultDisplacement()

    def add(id_, verts, dtype, tol, **kw):
        out = engine.apply_fault_throw(verts, **kw)
        cases.append({
            "family": "fault", "id": id_,
            "verts": jverts(verts), "dtype": dtype, "tol": tol, **kw,
            "out": jverts(out),
        })

    verts = _flat_verts(10, 10, z=100.0)
    add("vertical_hanging_float32", verts, "float32", 1e-6,
        fault_line_x=5.0, throw_z=-15.0)

    verts = np.array([[4.0, 5.0, 100.0], [5.1, 5.0, 100.0], [10.0, 5.0, 100.0]],
                     dtype=np.float32)
    add("decay_float32", verts, "float32", 1e-6,
        fault_line_x=5.0, throw_z=-20.0, decay_radius=3.0)

    def utm_grid():
        x, y = np.meshgrid(np.linspace(499900.0, 500100.0, 21),
                           np.linspace(3199900.0, 3200100.0, 21))
        z = np.full_like(x, 100.0)
        return np.column_stack([x.ravel(), y.ravel(), z.ravel()])

    add("utm_anchored_float64", utm_grid(), "float64", 1e-9,
        fault_line_x=500000.0, fault_line_y=3200000.0, throw_z=-15.0)

    strike = 30.0
    local = np.column_stack([
        np.linspace(-10, 10, 9).repeat(9),
        np.tile(np.linspace(-10, 10, 9), 9),
        np.full(81, 100.0),
    ])
    shifted = local + np.array([500000.0, 3200000.0, 0.0])
    out_local = engine.apply_fault_throw(local, fault_line_x=0.0, fault_line_y=0.0,
                                         throw_z=-10.0, strike_deg=strike)
    out_shifted = engine.apply_fault_throw(shifted, fault_line_x=500000.0,
                                           fault_line_y=3200000.0,
                                           throw_z=-10.0, strike_deg=strike)
    cases.append({
        "family": "fault", "id": "strike30_translation_invariant",
        "verts": jverts(local), "dtype": "float64", "tol": 1e-9,
        "fault_line_x": 0.0, "fault_line_y": 0.0, "throw_z": -10.0,
        "strike_deg": 30.0,
        "out_local": jverts(out_local),
        "out_shifted": jverts(out_shifted),
        "shifted": jverts(shifted),
    })

    anchor = (500000.0, 3200000.0)
    normal = np.array([math.cos(math.radians(45.0)), math.sin(math.radians(45.0))])
    plus = np.array([[*(anchor + 5.0 * normal), 100.0]])
    minus = np.array([[*(anchor - 5.0 * normal), 100.0]])
    both = np.vstack([plus, minus])
    add("strike45_anchor_float64", both, "float64", 1e-9,
        fault_line_x=anchor[0], fault_line_y=anchor[1], throw_z=-20.0,
        strike_deg=45.0)

    verts = np.array([[5.0, 0.0, 0.0], [-5.0, 0.0, 0.0]])
    add("heave_normal_float64", verts, "float64", 1e-9,
        fault_line_x=0.0, throw_z=10.0, dip_deg=60.0)
    add("heave_reverse_float64", verts, "float64", 1e-9,
        fault_line_x=0.0, throw_z=-10.0, dip_deg=60.0)

    verts = np.array([[2.0, 0.0, 50.0], [8.0, 0.0, 50.0]])
    add("throwx_explicit_float64", verts, "float64", 1e-9,
        fault_line_x=5.0, throw_z=-10.0, throw_x=3.0)
    add("dip0_uses_throwx_path_float64", verts, "float64", 1e-9,
        fault_line_x=5.0, throw_z=-10.0, dip_deg=0.0)
    add("dip90_uses_throwx_path_float64", verts, "float64", 1e-9,
        fault_line_x=5.0, throw_z=-10.0, dip_deg=90.0)

    spec = FaultSpec(fault_line_x=500000.0, fault_line_y=3200000.0,
                     throw_z=-10.0, dip_deg=45.0, strike_deg=20.0,
                     decay_radius=50.0)
    out = engine.apply_fault_throw(utm_grid(), spec=spec)
    cases.append({
        "family": "fault", "id": "spec_object_float64", "tol": 1e-9,
        "spec": {"fault_line_x": spec.fault_line_x, "throw_z": spec.throw_z,
                 "fault_line_y": spec.fault_line_y, "throw_x": spec.throw_x,
                 "dip_deg": spec.dip_deg, "strike_deg": spec.strike_deg,
                 "decay_radius": spec.decay_radius},
        "verts": jverts(utm_grid()), "out": jverts(out),
    })

    # boundary: dist_normal == 0 belongs to the hanging wall
    verts = np.array([[5.0, 0.0, 100.0], [4.999, 0.0, 100.0]])
    add("boundary_is_hanging_float64", verts, "float64", 1e-9,
        fault_line_x=5.0, throw_z=-15.0)


def _grid(nI=6, nX=6, top=100.0, thick=50.0, dtype="flat"):
    x = np.arange(nX, dtype=float) * 10.0
    y = np.arange(nI, dtype=float) * 10.0
    xx, yy = np.meshgrid(x, y)
    if dtype == "flat":
        tg = np.full((nI, nX), top)
        bg = np.full((nI, nX), top + thick)
    else:  # dipping
        tg = top + 0.2 * xx + 0.1 * yy
        bg = tg + thick
    return tg, bg


def triangulate_cases(cases):
    tg, _ = _grid()
    verts, faces = builders.triangulate_heightfield(tg)
    cases.append({
        "family": "triangulate", "id": "full_grid_6x6",
        "grid": flat_grid(tg), "verts": jverts(verts),
        "faces": [[int(c) for c in f] for f in faces],
    })

    tg, _ = _grid()
    tg[2:4, 2:4] = np.nan
    verts, faces = builders.triangulate_heightfield(tg)
    cases.append({
        "family": "triangulate", "id": "nan_hole_drops_quads",
        "grid": flat_grid(tg), "verts": jverts(verts),
        "faces": [[int(c) for c in f] for f in faces],
    })

    tg, _ = _grid(nI=1, nX=5)
    verts, faces = builders.triangulate_heightfield(tg)
    cases.append({
        "family": "triangulate", "id": "single_row_no_faces",
        "grid": flat_grid(tg), "verts": jverts(verts),
        "faces": [[int(c) for c in f] for f in faces],
    })

    tg, _ = _grid()
    tg = tg + 0.01 * np.arange(tg.size).reshape(tg.shape)
    verts, faces = builders.triangulate_heightfield(tg)
    cases.append({
        "family": "triangulate", "id": "relief_winding",
        "grid": flat_grid(tg), "verts": jverts(verts),
        "faces": [[int(c) for c in f] for f in faces],
    })


def curtain_cases(cases):
    trace = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0)]
    fault = builders.build_fault_curtain_from_trace("F1", trace, 100.0, 300.0)
    cases.append({
        "family": "curtain", "id": "three_point_trace",
        "verts": jverts(fault.verts),
        "faces": [[int(c) for c in f] for f in fault.faces],
    })
    cases.append({
        "family": "curtain", "id": "err_inverted_z",
        "raises": raises(lambda: builders.build_fault_curtain_from_trace(
            "F", [(0, 0), (1, 1)], 300.0, 100.0)),
    })
    cases.append({
        "family": "curtain", "id": "err_single_point_trace",
        "raises": raises(lambda: builders.build_fault_curtain_from_trace(
            "F", [(0.0, 0.0)], 100.0, 300.0)),
    })
    cases.append({
        "family": "curtain", "id": "err_nonfinite_trace",
        "raises": raises(lambda: builders.build_fault_curtain_from_trace(
            "F", [(0.0, 0.0), (float("nan"), 1.0)], 100.0, 300.0)),
    })
    cases.append({
        "family": "curtain", "id": "err_equal_z",
        "raises": raises(lambda: builders.build_fault_curtain_from_trace(
            "F", [(0.0, 0.0), (1.0, 1.0)], 100.0, 100.0)),
    })


def _shell_qc(qc):
    return {
        "column_count": int(qc["column_count"]),
        "dropped_crossed": int(qc["dropped_crossed"]),
        "dropped_nan_nodes": int(qc["dropped_nan_nodes"]),
        "negative_thickness_count": int(qc["negative_thickness_count"]),
        "min_thickness": jnum(qc["min_thickness"]),
        "max_thickness": jnum(qc["max_thickness"]),
        "mean_thickness": jnum(qc["mean_thickness"]),
        "closed": bool(qc["closed"]),
        "unit": qc["unit"],
    }


def shell_cases(cases):
    def make(id_, tg, bg, boundary, vertical_domain="depth", unit="m",
             object_id="volume:v"):
        top = horizon("Top", tg, vertical_domain=vertical_domain, unit=unit)
        base = horizon("Base", bg, vertical_domain=vertical_domain, unit=unit)
        vol, qc = builders.build_volume_shell(
            top, base, boundary, object_id=object_id)
        cases.append({
            "family": "shell", "id": id_, "tol": 1e-12,
            "top": flat_grid(tg, spacing=(10.0, 10.0)),
            "base": flat_grid(bg, spacing=(10.0, 10.0)),
            "boundary": jpts2(boundary),
            "vertical_domain": vertical_domain, "unit": unit,
            "object_id": object_id,
            "qc": _shell_qc(qc),
            "thicknesses": [jnum(t) for t in qc.get("_thicknesses", [])]
            if "_thicknesses" in qc else None,
            "verts": jverts(vol.verts) if len(np.asarray(vol.verts)) else [],
            "faces": [[int(c) for c in f] for f in vol.faces]
            if len(np.asarray(vol.faces)) else [],
        })

    tg, bg = _grid()
    make("flat_box16", tg, bg, [(0.0, 0.0), (40.0, 0.0), (40.0, 40.0), (0.0, 40.0)])

    tg, bg = _grid()
    bg[1:3, 1:3] = tg[1:3, 1:3] - 10.0
    make("crossed_columns_dropped", tg, bg,
         [(0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)])

    tg, bg = _grid()
    tg[3:, 3:] = np.nan
    bg[3:, 3:] = np.nan
    make("nan_region_dropped", tg, bg,
         [(0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)])

    tg = np.full((4, 4), -100.0)
    bg = np.full((4, 4), -150.0)
    make("tvdss_closes", tg, bg, [(0, 0), (30, 0), (30, 30), (0, 30)],
         vertical_domain="tvdss", object_id="volume:t")
    bg2 = np.full((4, 4), -90.0)
    make("tvdss_inverted", tg, bg2, [(0, 0), (30, 0), (30, 30), (0, 30)],
         vertical_domain="tvdss", object_id="volume:t")

    tg, bg = _grid()
    make("boundary_outside_empty", tg, bg,
         [(1000.0, 1000.0), (1040.0, 1000.0), (1040.0, 1040.0), (1000.0, 1040.0)])

    tg, bg = _grid(dtype="dipping")
    make("dipping_arrays", tg, bg,
         [(0.0, 0.0), (50.0, 0.0), (50.0, 50.0), (0.0, 50.0)])

    # error branches (verbatim DomainError text)
    top = horizon("Top", _grid()[0], vertical_domain="depth")
    base = horizon("Base", _grid()[1], vertical_domain="twt")
    cases.append({
        "family": "shell", "id": "err_domain_mismatch", "object_id": "volume:x",
        "raises": raises(lambda: builders.build_volume_shell(
            top, base, [(0, 0), (10, 0), (10, 10), (0, 10)], object_id="volume:x")),
    })
    top = horizon("Top", _grid()[0], origin=(0.0, 0.0), spacing=(10.0, 10.0))
    other = horizon("T2", _grid(nI=5, nX=5)[0], origin=(0.0, 0.0),
                    spacing=(10.0, 10.0))
    cases.append({
        "family": "shell", "id": "err_grid_mismatch", "object_id": "volume:x",
        "raises": raises(lambda: builders.build_volume_shell(
            other, top, [(0, 0), (10, 0), (10, 10), (0, 10)], object_id="volume:x")),
    })
    top = horizon("Top", _grid()[0])
    base = horizon("Base", _grid()[1])
    cases.append({
        "family": "shell", "id": "err_boundary_nonfinite", "object_id": "volume:x",
        "raises": raises(lambda: builders.build_volume_shell(
            top, base,
            [(0.0, 0.0), (10.0, float("nan")), (10.0, 10.0), (0.0, 10.0)],
            object_id="volume:x")),
    })
    cases.append({
        "family": "shell", "id": "err_boundary_two_points", "object_id": "volume:x",
        "raises": raises(lambda: builders.build_volume_shell(
            top, base, [(0.0, 0.0), (10.0, 0.0)], object_id="volume:x")),
    })
    cases.append({
        "family": "shell", "id": "err_single_row_lattice", "object_id": "volume:x",
        "raises": raises(lambda: builders.build_volume_shell(
            horizon("Top", _grid(nI=1, nX=6)[0]),
            horizon("Base", _grid(nI=1, nX=6)[1]),
            [(0, 0), (50, 0), (50, 10), (0, 10)], object_id="volume:x")),
    })


def hex_cases(cases):
    def make(id_, tg, bg, boundary, n_layers=4, vertical_domain="depth"):
        top = horizon("Top", tg, vertical_domain=vertical_domain)
        base = horizon("Base", bg, vertical_domain=vertical_domain)
        nodes, hexes, info = builders.build_columnar_hex_mesh(
            top, base, boundary, n_layers=n_layers)
        cases.append({
            "family": "hex", "id": id_,
            "top": flat_grid(tg, spacing=(10.0, 10.0)),
            "base": flat_grid(bg, spacing=(10.0, 10.0)),
            "boundary": jpts2(boundary), "n_layers": n_layers,
            "vertical_domain": vertical_domain,
            "nodes": jverts(nodes),
            "hexes": [[int(c) for c in h] for h in hexes],
            "info": {"n_cells": int(info["n_cells"]),
                     "n_layers": int(info["n_layers"]),
                     "n_hexes": int(info["n_hexes"]),
                     "skipped_crossed": int(info["skipped_crossed"]),
                     "unit": info["unit"], "merge": info["merge"]},
        })

    tg, bg = _grid()
    make("box25_4layers", tg, bg, [(0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)])

    tg, bg = _grid()
    bg[2, 2] = tg[2, 2] - 5.0
    make("crossed_skipped", tg, bg, [(0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)])

    tg, bg = _grid()
    make("one_layer", tg, bg, [(0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)],
         n_layers=1)

    tg = np.full((4, 4), -100.0)
    bg = np.full((4, 4), -150.0)
    make("tvdss_hex", tg, bg, [(0, 0), (30, 0), (30, 30), (0, 30)],
         vertical_domain="tvdss")

    tg, bg = _grid(dtype="dipping")
    make("dipping_2layers", tg, bg, [(0.0, 0.0), (60.0, 0.0), (60.0, 60.0), (0.0, 60.0)],
         n_layers=2)

    top = horizon("Top", _grid()[0])
    base = horizon("Base", _grid()[1])
    tg, bg = _grid()
    top_h = horizon("Top", tg)
    base_h = horizon("Base", bg)
    cases.append({
        "family": "hex", "id": "err_boundary_two_points",
        "raises": raises(lambda: builders.build_columnar_hex_mesh(
            top_h, base_h, [(0.0, 0.0), (10.0, 0.0)])),
    })
    cases.append({
        "family": "hex", "id": "err_boundary_nonfinite",
        "raises": raises(lambda: builders.build_columnar_hex_mesh(
            top_h, base_h,
            [(0.0, 0.0), (10.0, float("nan")), (10.0, 10.0), (0.0, 10.0)])),
    })
    top_tw = horizon("Top", tg, vertical_domain="depth")
    base_tw = horizon("Base", bg, vertical_domain="twt")
    cases.append({
        "family": "hex", "id": "err_domain_mismatch",
        "raises": raises(lambda: builders.build_columnar_hex_mesh(
            top_tw, base_tw, [(0, 0), (10, 0), (10, 10), (0, 10)])),
    })
    empty_top = horizon("Top", np.full((3, 3), 100.0))
    empty_base = horizon("Base", np.full((3, 3), 150.0))
    empty_nodes, empty_hexes, empty_info = builders.build_columnar_hex_mesh(
        empty_top, empty_base,
        [(1000.0, 1000.0), (1040.0, 1000.0), (1040.0, 1040.0), (1000.0, 1040.0)])
    cases.append({
        "family": "hex", "id": "boundary_outside_empty_mesh",
        "nodes": jverts(empty_nodes), "hexes": [[int(c) for c in h] for h in empty_hexes],
        "info": {"n_cells": int(empty_info["n_cells"]),
                 "n_layers": int(empty_info["n_layers"]),
                 "n_hexes": int(empty_info["n_hexes"]),
                 "skipped_crossed": int(empty_info["skipped_crossed"]),
                 "unit": empty_info["unit"], "merge": empty_info["merge"]},
    })

    cases.append({
        "family": "hex", "id": "err_zero_layers",
        "raises": raises(lambda: builders.build_columnar_hex_mesh(
            top, base, [(0, 0), (10, 0), (10, 10), (0, 10)], n_layers=0)),
    })
    cases.append({
        "family": "hex", "id": "err_grid_mismatch",
        "raises": raises(lambda: builders.build_columnar_hex_mesh(
            horizon("T2", _grid(nI=5, nX=5)[0]), base,
            [(0, 0), (10, 0), (10, 10), (0, 10)])),
    })


def pip_cases(cases):
    ring = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    probes = [(5.0, 5.0), (0.0, 5.0), (10.0, 5.0), (5.0, 0.0), (5.0, 10.0),
              (0.0, 0.0), (10.0, 10.0), (-1.0, 5.0), (11.0, 5.0), (2.5, 7.5)]
    from paleo_workbench.mapping.geometry_planar import points_in_polygon_vectorized
    polygon = {"type": "Polygon", "coordinates": [list(ring)]}
    expected = [bool(points_in_polygon_vectorized(np.array([px]), np.array([py]), polygon)[0])
                for px, py in probes]
    cases.append({
        "family": "pip", "id": "unit_ring_probe",
        "ring": jpts2(ring),
        "probes": jpts2(probes),
        "inside": expected,
    })

    utm_ring = [(500000.0, 3200000.0), (500100.0, 3200000.0),
                (500100.0, 3200100.0), (500000.0, 3200100.0)]
    utm_probes = [(500050.0, 3200050.0), (500000.0, 3200050.0),
                  (499999.0, 3200050.0)]
    polygon = {"type": "Polygon", "coordinates": [list(utm_ring)]}
    expected = [bool(points_in_polygon_vectorized(np.array([px]), np.array([py]), polygon)[0])
                for px, py in utm_probes]
    cases.append({
        "family": "pip", "id": "utm_ring_probe",
        "ring": jpts2(utm_ring),
        "probes": jpts2(utm_probes),
        "inside": expected,
    })


def dedupe_cases(cases):
    st = np.array([
        [100.0, 0, 0, 100],
        [0.0, 0, 0, 0],
        [100.0, 0, 0, 100],
        [200.0, 0, 0, 200],
    ])
    out, dropped = builders.dedupe_stations(st)
    cases.append({
        "family": "dedupe", "id": "sort_and_drop", "tol": 0.0,
        "stations": jarr(st),
        "kept": jarr(out), "dropped": int(dropped),
    })

    st = np.array([
        [1000.0, 1, 1, 1000],
        [1000.0 + 5e-10, 2, 2, 1000],
        [1000.0 + 1e-6, 3, 3, 1000],
        [10.0, 4, 4, 10],
        [10.0 + 1e-10, 5, 5, 10],
    ])
    out, dropped = builders.dedupe_stations(st)
    cases.append({
        "family": "dedupe", "id": "relative_tolerance", "tol": 0.0,
        "stations": jarr(st),
        "kept": jarr(out), "dropped": int(dropped),
    })

    st = np.array([
        [50.0, 1, 0, 50],
        [25.0, 2, 0, 25],
        [25.0, 3, 0, 25],
        [25.0, 4, 0, 25],
    ])
    out, dropped = builders.dedupe_stations(st)
    cases.append({
        "family": "dedupe", "id": "stable_ties_first_kept", "tol": 0.0,
        "stations": jarr(st),
        "kept": jarr(out), "dropped": int(dropped),
    })
    st = np.array([[0.0, 0, 0, 0], [float("inf"), 1, 1, 1]])
    cases.append({
        "family": "dedupe", "id": "err_nonfinite",
        "stations": jarr(st),
        "raises": raises(lambda: builders.dedupe_stations(st)),
    })


def measure_cases(cases):
    m = meas.distance((0, 0, 0), (3, 4, 0), crs=CRS)
    cases.append({
        "family": "measure", "id": "distance_345", "tol": 1e-12,
        "kind": "distance",
        "result": jnum(m.result),
        "formatted": meas.format_result(m),
    })

    m = meas.polyline_length([(0, 0, 0), (1, 0, 0), (1, 1, 0)], crs=CRS)
    cases.append({
        "family": "measure", "id": "polyline_two_legs", "tol": 1e-12,
        "kind": "polyline", "result": jnum(m.result),
        "legs": int(m.extra["legs"]),
        "formatted": meas.format_result(m),
    })

    m = meas.vertical_difference((0, 0, 10), (1, 1, -5), crs=CRS)
    cases.append({
        "family": "measure", "id": "vertical_negative", "tol": 1e-12,
        "kind": "vertical_difference", "result": jnum(m.result),
        "dz": jnum(m.extra["dz"]),
        "formatted": meas.format_result(m),
    })
    m = meas.vertical_difference((0, 0, 0), (1, 1, 10), crs=CRS)
    cases.append({
        "family": "measure", "id": "vertical_positive", "tol": 1e-12,
        "kind": "vertical_difference", "result": jnum(m.result),
        "formatted": meas.format_result(m),
    })

    g_top = np.zeros((4, 4))
    g_base = np.full((4, 4), 50.0)
    g_base[0, 0] = np.nan
    top = horizon("T", g_top)
    base = horizon("B", g_base)
    m = meas.thickness_at(15.0, 15.0, top, base)
    cases.append({
        "family": "measure", "id": "thickness_center", "tol": 1e-12,
        "kind": "thickness", "result": jnum(m.result),
        "signed": jnum(m.extra["signed"]),
        "points": jverts(m.points),
        "formatted": meas.format_result(m),
    })
    m = meas.thickness_at(30.0, 20.0, top, base)
    cases.append({
        "family": "measure", "id": "thickness_edge_clamp", "tol": 1e-12,
        "kind": "thickness", "result": jnum(m.result),
        "points": jverts(m.points),
        "formatted": meas.format_result(m),
    })
    m = meas.thickness_at(15.0, 15.0, top, base, unit="ft")
    cases.append({
        "family": "measure", "id": "thickness_ft_unit", "tol": 1e-12,
        "kind": "thickness", "result": jnum(m.result),
        "formatted": meas.format_result(m),
    })
    cases.append({
        "family": "measure", "id": "thickness_hole_raises",
        "raises": raises(lambda: meas.thickness_at(1.0, 1.0, top, base)),
    })
    top_d = horizon("T", np.zeros((3, 3)), vertical_domain="depth")
    base_t = horizon("B", np.ones((3, 3)), vertical_domain="twt")
    cases.append({
        "family": "measure", "id": "thickness_domain_mismatch_raises",
        "raises": raises(lambda: meas.thickness_at(0, 0, top_d, base_t)),
    })

    m = meas.plane_orientation([(0, 0, 0), (10, 0, 0), (0, 10, 1), (10, 10, 1)], crs=CRS)
    cases.append({
        "family": "measure", "id": "plane_tilted",
        "kind": "plane_orientation", "dip": jnum(m.extra["dip_deg"]),
        "strike": jnum(m.extra["strike_deg"]),
        "planarity": jnum(m.extra["planarity_ratio"]),
        "result": jnum(m.result),
        "formatted": meas.format_result(m),
        "tol": 1e-6,
    })
    m = meas.plane_orientation([(0, 0, 0), (10, 0, 0), (0, 10, 0), (10, 10, 0)], crs=CRS)
    cases.append({
        "family": "measure", "id": "plane_flat",
        "kind": "plane_orientation", "dip": jnum(m.extra["dip_deg"]),
        "strike": jnum(m.extra["strike_deg"]),
        "planarity": jnum(m.extra["planarity_ratio"]),
        "formatted": meas.format_result(m),
        "tol": 1e-6,
    })

    cases.append({
        "family": "measure", "id": "err_plane_two_points",
        "raises": raises(lambda: meas.plane_orientation(
            [(0, 0, 0), (1, 1, 1)], crs=CRS)),
    })
    m = meas.plane_orientation([(5, 5, 5), (5, 5, 5), (5, 5, 5)], crs=CRS)
    cases.append({
        "family": "measure", "id": "plane_zero_scatter",
        "kind": "plane_orientation", "dip": jnum(m.extra["dip_deg"]),
        "strike": jnum(m.extra["strike_deg"]),
        "planarity": jnum(m.extra["planarity_ratio"]),
        "formatted": meas.format_result(m),
        "tol": 1e-12,
    })
    cases.append({
        "family": "measure", "id": "thickness_outside_grid_raises",
        "raises": raises(lambda: meas.thickness_at(100.0, 15.0, top, base)),
    })
    # degenerate 1-column grid: bilinear must reproduce numpy's negative
    # index wraparound (both corners collapse onto the single column)
    g1 = np.array([[10.0], [20.0], [30.0]])
    t1 = horizon("T1", g1, origin=(0.0, 0.0), spacing=(10.0, 1.0))
    b1 = horizon("B1", g1 + 5.0, origin=(0.0, 0.0), spacing=(10.0, 1.0))
    for px in (0.0, 0.4):
        m = meas.thickness_at(px, 15.0, t1, b1)
        cases.append({
            "family": "measure", "id": f"thickness_single_column_x{px}",
            "tol": 1e-12,
            "kind": "thickness", "result": jnum(m.result),
            "signed": jnum(m.extra["signed"]),
            "points": jverts(m.points),
            "formatted": meas.format_result(m),
        })

    m = meas.point_coordinate((5, 6, -100), crs=CRS)
    cases.append({
        "family": "measure", "id": "point_record", "tol": 1e-12,
        "kind": "point", "extra_z": jnum(m.extra["z"]),
        "points": jverts(m.points),
        "formatted": meas.format_result(m),
    })

    cases.append({
        "family": "measure", "id": "err_nonfinite",
        "raises": raises(lambda: meas.distance((0, 0, float("nan")), (1, 1, 1), crs=CRS)),
    })
    cases.append({
        "family": "measure", "id": "err_polyline_single_point",
        "raises": raises(lambda: meas.polyline_length([(0, 0, 0)], crs=CRS)),
    })


def section_cases(cases):
    p = section.Plane((0, 0, 2), -300.0)
    cases.append({
        "family": "section", "id": "plane_normalized",
        "normal": jarr(p.n), "d": jnum(p.d),
        "signed": jarr(p.signed_distance(np.array([[0.0, 0.0, -150.0],
                                                   [0.0, 0.0, -50.0]]))),
        "clip_eq": [jnum(v) for v in p.as_clip_equation()],
        "clip_eq_invert": [jnum(v) for v in p.as_clip_equation(invert=True)],
    })

    p = section.axis_plane("z", -150.0)
    cases.append({
        "family": "section", "id": "axis_plane_clip",
        "normal": jarr(p.n), "d": jnum(p.d),
        "clip_eq": [jnum(v) for v in p.as_clip_equation()],
        "clip_eq_invert": [jnum(v) for v in p.as_clip_equation(invert=True)],
    })
    cases.append({
        "family": "section", "id": "err_bad_axis",
        "raises": raises(lambda: section.axis_plane("w", 0)),
    })
    cases.append({
        "family": "section", "id": "err_zero_normal",
        "raises": raises(lambda: section.Plane((0, 0, 0), 1.0)),
    })

    eqs = section.clip_planes_for_box([(0, 0, 0), (10, 20, 30)])
    cases.append({
        "family": "section", "id": "box_clip_six",
        "eqs": [[jnum(v) for v in eq] for eq in eqs],
    })

    p = section.plane_from_normal_point((1, 1, 0), (5, 5, -7))
    cases.append({
        "family": "section", "id": "plane_from_normal_point",
        "normal": jarr(p.n), "d": jnum(p.d),
    })

    g = np.full((6, 6), -100.0)
    curves = section.horizon_plane_intersection(
        section.axis_plane("x", 25.0), g, origin=(0, 0), spacing=(10, 10))
    cases.append({
        "family": "section", "id": "horizon_z_section_single",
        "grid": flat_grid(g, spacing=(10.0, 10.0)), "axis": "x", "value": 25.0,
        "origin": [0.0, 0.0], "spacing": [10.0, 10.0],
        "curves": [jverts(c) for c in curves],
        "tol": 1e-9,
    })

    g = np.full((6, 6), -100.0)
    g[2:4, 2:4] = np.nan
    curves = section.horizon_plane_intersection(
        section.axis_plane("x", 25.0), g, origin=(0, 0), spacing=(10, 10))
    cases.append({
        "family": "section", "id": "horizon_nan_splits_curve",
        "grid": flat_grid(g, spacing=(10.0, 10.0)), "axis": "x", "value": 25.0,
        "origin": [0.0, 0.0], "spacing": [10.0, 10.0],
        "curves": [jverts(c) for c in curves],
        "tol": 1e-9,
    })

    v = np.array([
        [0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0],
        [0, 0, -10], [10, 0, -10], [10, 10, -10], [0, 10, -10],
    ], dtype=float)
    f = np.array([
        [0, 1, 2], [0, 2, 3],
        [4, 6, 5], [4, 7, 6],
        [0, 4, 5], [0, 5, 1],
        [1, 5, 6], [1, 6, 2],
        [2, 6, 7], [2, 7, 3],
        [3, 7, 4], [3, 4, 0],
    ])
    curves = section.mesh_plane_intersection(section.axis_plane("x", 5.0), v, f)
    cases.append({
        "family": "section", "id": "mesh_box_section",
        "verts": jverts(v), "faces": [[int(c) for c in row] for row in f],
        "axis": "x", "value": 5.0,
        "curves": [jverts(c) for c in curves],
        "tol": 1e-9,
    })

    segs = section.intersect_plane_with_triangles(
        section.axis_plane("z", 0.0),
        np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [5.0, 10.0, 4.0]]),
        np.array([[0, 1, 2]]))
    cases.append({
        "family": "section", "id": "triangle_two_onscreen_vertices",
        "segs": [jverts(s) for s in segs],
        "tol": 1e-9,
    })
    # one vertex ON the plane, one above, one below: the zero point leads
    # edge_pts, the (+,-) interpolation follows
    segs = section.intersect_plane_with_triangles(
        section.axis_plane("z", 0.0),
        np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 6.0], [0.0, 10.0, -4.0]]),
        np.array([[0, 1, 2]]))
    cases.append({
        "family": "section", "id": "triangle_mixed_zero_vertex",
        "segs": [jverts(s) for s in segs],
        "tol": 1e-9,
    })

    traj = np.array([[0, 0, 0], [0, 0, -100], [0, 0, -200]], dtype=float)
    hit = section.well_plane_crossing(section.axis_plane("z", -150.0), traj)
    miss = section.well_plane_crossing(section.axis_plane("z", -500.0), traj)
    on = section.well_plane_crossing(
        section.axis_plane("z", -100.0), traj)
    cases.append({
        "family": "section", "id": "well_crossing",
        "stations": jverts(traj),
        "hit": jverts(np.asarray([hit])) if hit is not None else None,
        "miss": None if miss is None else jverts(np.asarray([miss])),
        "on_plane": None if on is None else jverts(np.asarray([on])),
        "tol": 1e-9,
    })

    # two segments chain into one 3-point polyline
    segs = [
        np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
        np.array([[1.0, 0.0, 0.0], [2.0, 1.0, 0.0]]),
    ]
    chains = section._chain_segments(segs)
    cases.append({
        "family": "section", "id": "chain_two_segments",
        "segments": [jverts(s) for s in segs],
        "chains": [jverts(c) for c in chains],
        "tol": 1e-9,
    })


def meshqc_cases(cases):
    tg, _ = _grid(nI=3, nX=3)
    top = horizon("T", tg)
    verts, faces = builders.triangulate_heightfield(tg)
    cases.append({
        "family": "meshqc", "id": "healthy_heightfield", "tol": 1e-12,
        "verts": jverts(verts), "faces": [[int(c) for c in f] for f in faces],
        "degenerate_fraction": float(
            geomodel_qc._tri_degenerate_fraction(verts, faces)),
        "edge": {"boundary": int(geomodel_qc._edge_manifold_stats(faces)[0]),
                 "nonmanifold": int(geomodel_qc._edge_manifold_stats(faces)[1])},
        "components": int(geomodel_qc._connected_components(verts, faces)),
    })

    v = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [10.0, 0.0, 0.0]])
    f = np.array([[0, 1, 2], [0, 2, 1]])
    cases.append({
        "family": "meshqc", "id": "degenerate_half", "tol": 1e-12,
        "verts": jverts(v), "faces": [[int(c) for c in row] for row in f],
        "degenerate_fraction": float(geomodel_qc._tri_degenerate_fraction(v, f)),
        "edge": {"boundary": int(geomodel_qc._edge_manifold_stats(f)[0]),
                 "nonmanifold": int(geomodel_qc._edge_manifold_stats(f)[1])},
    })

    # open shell: box minus one face
    v = np.array([
        [0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0],
        [0, 0, -10], [10, 0, -10], [10, 10, -10], [0, 10, -10],
    ], dtype=float)
    f = np.array([
        [0, 1, 2], [0, 2, 3],
        [4, 6, 5], [4, 7, 6],
        [0, 4, 5], [0, 5, 1],
        [1, 5, 6], [1, 6, 2],
        [2, 6, 7], [2, 7, 3],
        [3, 7, 4], [3, 4, 0],
    ])
    open_report_b = int(geomodel_qc._edge_manifold_stats(f[:-1])[0])
    open_report_n = int(geomodel_qc._edge_manifold_stats(f[:-1])[1])
    cases.append({
        "family": "meshqc", "id": "open_shell_boundary",
        "verts": jverts(v),
        "faces": [[int(c) for c in row] for row in f[:-1]],
        "edge": {"boundary": open_report_b, "nonmanifold": open_report_n},
        "components": int(geomodel_qc._connected_components(v, f[:-1])),
    })

    # non-manifold: three faces share one edge
    v = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [5.0, 5.0, 0.0],
                  [5.0, -5.0, 1.0], [5.0, 5.0, 1.0]])
    f = np.array([[0, 1, 2], [0, 2, 1], [0, 1, 3], [0, 1, 4]])
    b, nm = geomodel_qc._edge_manifold_stats(f)
    cases.append({
        "family": "meshqc", "id": "nonmanifold_edge",
        "verts": jverts(v), "faces": [[int(c) for c in row] for row in f],
        "edge": {"boundary": int(b), "nonmanifold": int(nm)},
        "components": int(geomodel_qc._connected_components(v, f)),
    })

    empty_v = np.zeros((0, 3))
    empty_f = np.zeros((0, 3), dtype=np.int64)
    eb, en = geomodel_qc._edge_manifold_stats(empty_f)
    cases.append({
        "family": "meshqc", "id": "empty_faces", "tol": 1e-12,
        "verts": [], "faces": [],
        "degenerate_fraction": float(
            geomodel_qc._tri_degenerate_fraction(empty_v, empty_f)),
        "edge": {"boundary": int(eb), "nonmanifold": int(en)},
        "components": int(geomodel_qc._connected_components(empty_v, empty_f)),
    })

    # isolated vertex counts as its own component (scipy parity)
    v = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [5.0, 10.0, 0.0],
                  [99.0, 99.0, 99.0]])
    f = np.array([[0, 1, 2]])
    cases.append({
        "family": "meshqc", "id": "isolated_vertex_component",
        "verts": jverts(v), "faces": [[int(c) for c in row] for row in f],
        "components": int(geomodel_qc._connected_components(v, f)),
    })


def horizon_err_cases(cases):
    cases.append({
        "family": "horizon_err", "id": "err_empty_grid",
        "raises": raises(lambda: builders.build_horizon_from_grid(
            "Bad", np.zeros((0, 0)))),
    })
    cases.append({
        "family": "horizon_err", "id": "err_inf_grid",
        "raises": raises(lambda: builders.build_horizon_from_grid(
            "Bad", np.array([[0.0, 1.0], [float("inf"), 0.0]]),
            object_id="horizon:bad")),
    })


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cases: list[dict] = []
    for add in (volume_cases, sculpt_cases, fault_cases, triangulate_cases,
                curtain_cases, shell_cases, hex_cases, pip_cases,
                dedupe_cases, measure_cases, section_cases, meshqc_cases,
                horizon_err_cases):
        add(cases)
    target = OUT / "geomodel_volume_oracle.json"
    target.write_text(
        json.dumps({"cases": cases}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    families: dict[str, int] = {}
    for c in cases:
        families[c["family"]] = families.get(c["family"], 0) + 1
    print(f"wrote {target} ({len(cases)} cases) {families}")


if __name__ == "__main__":
    main()
