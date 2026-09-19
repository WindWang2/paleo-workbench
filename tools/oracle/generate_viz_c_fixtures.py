#!/usr/bin/env python3
"""VIZ-C joint well-seismic oracle generator (plan V4).

Runs the REAL geoviz_well_seismic_3d package (frozen legacy reference,
submodule 08851951) and freezes exact expected values for the C++ port in
libs/geo3d_viz/joint. The C++ replay test (tests/cpp/viz_c) loads
viz_c_joint_oracle.json and must reproduce every number bit-for-bit
(exact float equality where the Python side is float64; the fixture
records repr-precision floats).

No hand-copied expectations: every value below is computed by importing
the Python package. The fixture embeds a `tamper` block consumed by the
C++ negative self-check (a perturbed fixture must be DETECTED, never
silently pass).

Usage: python3 tools/oracle/generate_viz_c_fixtures.py [--out DIR]
Requires: numpy (PySide6 not needed — the Qt surfaces are out of scope).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGES = REPO / "geo-viz-engine" / "packages"
# Each geoviz package is a project dir wrapping the importable package
# (packages/<name>/<name>); both project roots join the path explicitly so
# the frozen submodule copy at THIS gitlink wins over any host-level
# editable install pointing elsewhere.
for _project in ("geoviz_well_seismic_3d", "geoviz_seismic", "geoviz_common"):
    sys.path.insert(0, str(PACKAGES / _project))

import numpy as np  # noqa: E402

from geoviz_well_seismic_3d.depth_transform import (  # noqa: E402
    DepthTransformState,
    select_depth_transform,
)
from geoviz_well_seismic_3d.fence import (  # noqa: E402
    FenceSection,
    extract_fence_strip,
    sample_fence_polyline,
)
from geoviz_well_seismic_3d.models import (  # noqa: E402
    OrthogonalSliceState,
    TimeDepthTable,
    TimeSliceState,
    VerticalDomain,
    WellHead,
)
from geoviz_well_seismic_3d.color_scales import (  # noqa: E402
    colorize_amplitude,
    colorize_gr,
)
from geoviz_well_seismic_3d.probe import probe_from_fence_s  # noqa: E402
from geoviz_well_seismic_3d.registration import VolumeRegistration  # noqa: E402
from geoviz_well_seismic_3d.scene import WellSeismicScene  # noqa: E402
from geoviz_well_seismic_3d.survey import survey_from_corners  # noqa: E402
from geoviz_well_seismic_3d.volume_access import InMemoryVolumeAccess  # noqa: E402
from geoviz_well_seismic_3d.well_geometry import (  # noqa: E402
    offset_curve_along_trajectory,
    pierce_xy_at_z,
    project_well_trajectory,
)

FLOAT_MIN_PRECISION = 17


def f(x) -> float:
    return float(x)


def case_survey() -> dict:
    out = {"cases": [], "errors": []}

    def record(name, spec, corners=None, kwargs=None):
        bg = spec.bin_grid
        entry = {
            "corners": [list(c) for c in corners] if corners else None,
            "kwargs": ({k: (v if not isinstance(v, float) else f(v))
                        for k, v in kwargs.items()} if kwargs else None),
            "name": name,
            "bin_grid": {
                "x_origin": f(bg.x_origin), "y_origin": f(bg.y_origin),
                "il_azimuth_deg": f(bg.il_azimuth_deg),
                "il_spacing_m": f(bg.il_spacing_m),
                "xl_spacing_m": f(bg.xl_spacing_m),
            },
            "iline_start": spec.iline_start, "iline_step": spec.iline_step,
            "xline_start": spec.xline_start, "xline_step": spec.xline_step,
            "n_inlines": spec.n_inlines, "n_crosslines": spec.n_crosslines,
            "n_samples": spec.n_samples, "dt_ms": f(spec.dt_ms),
            "t0_ms": f(spec.t0_ms),
            "xy_roundtrip": [
                [f(v) for v in spec.il_xl_to_xy(*spec.xy_to_il_xl(x, y))]
                for (x, y) in [(0.0, 0.0), (1500.25, -300.5), (-1e-3, 1e3)]
            ],
        }
        out["cases"].append(entry)

    # Classic IL=+Y / XL=+X, step 1.
    record(
        "classic",
        survey_from_corners((1, 1, 1000.0, 2000.0), (1, 10, 1900.0, 2000.0),
                            (20, 10, 1900.0, 2600.0),
                            n_samples=64, dt_ms=2.0),
        corners=[(1, 1, 1000.0, 2000.0), (1, 10, 1900.0, 2000.0),
                 (20, 10, 1900.0, 2600.0)],
        kwargs=dict(n_samples=64, dt_ms=2.0),
    )
    # IL along +X (azimuth 90) → spacing sign flip (wayfinder #84).
    record(
        "il_along_x",
        survey_from_corners((1, 1, 0.0, 0.0), (1, 8, 700.0, 0.0),
                            (12, 8, 700.0, -600.0),
                            n_samples=32, dt_ms=4.0),
        corners=[(1, 1, 0.0, 0.0), (1, 8, 700.0, 0.0), (12, 8, 700.0, -600.0)],
        kwargs=dict(n_samples=32, dt_ms=4.0),
    )
    # Explicit line step > 1 with matching counts (IL 1000..1002).
    record(
        "numbered_step2",
        survey_from_corners((1000, 10, 500.0, 100.0), (1000, 14, 500.0, 300.0),
                            (1002, 14, 620.0, 300.0),
                            n_samples=16, dt_ms=1.0, iline_step=2,
                            xline_step=1, n_inlines=2, n_crosslines=5),
        corners=[(1000, 10, 500.0, 100.0), (1000, 14, 500.0, 300.0),
                 (1002, 14, 620.0, 300.0)],
        kwargs=dict(n_samples=16, dt_ms=1.0, iline_step=2, xline_step=1,
                    n_inlines=2, n_crosslines=5),
    )
    # Negative direction corners (step -1 derived from span).
    record(
        "negative_span",
        survey_from_corners((10, 5, 0.0, 0.0), (10, 4, 0.0, -250.0),
                            (8, 4, -125.0, -250.0),
                            n_samples=8, dt_ms=2.0),
        corners=[(10, 5, 0.0, 0.0), (10, 4, 0.0, -250.0), (8, 4, -125.0, -250.0)],
        kwargs=dict(n_samples=8, dt_ms=2.0),
    )

    for name, corners, kwargs in [
        ("corner_inline_mismatch",
         [(1, 1, 0.0, 0.0), (2, 10, 0.0, 0.0), (20, 10, 0.0, 100.0)],
         dict(n_samples=8, dt_ms=2.0)),
        ("degenerate_coordinates",
         [(1, 1, 0.0, 0.0), (1, 10, 0.0, 0.0), (20, 10, 0.0, 0.0)],
         dict(n_samples=8, dt_ms=2.0)),
        ("span_step_mismatch",
         [(1000, 10, 0.0, 0.0), (1000, 14, 0.0, 400.0), (1005, 14, 500.0, 400.0)],
         dict(n_samples=8, dt_ms=2.0, iline_step=2, n_inlines=2)),
    ]:
        try:
            survey_from_corners(*corners, **kwargs)
            out["errors"].append({"name": name, "raised": False})
        except ValueError as ex:
            out["errors"].append({"name": name, "raised": True,
                                  "message": str(ex)})
    return out


def case_registration() -> dict:
    spec = survey_from_corners(
        (1, 1, 1000.0, 2000.0), (1, 10, 1900.0, 2000.0),
        (20, 10, 1900.0, 2600.0), n_samples=64, dt_ms=2.0)
    full = VolumeRegistration.from_survey_and_shape(spec, (20, 10, 64))
    preview = VolumeRegistration.from_survey_and_shape(spec, (10, 5, 32))
    explicit = VolumeRegistration(spec, 10, 5, 32, (2, 2, 2))
    out = {
        "full": {
            "strides": list(full.strides),
            "idx": [
                list(map(f, full.il_xl_to_volume_idx(il, xl)))
                for il, xl in [(1, 1), (20, 10), (11.5, 3.25)]
            ],
            "xy_idx": [
                list(map(f, full.xy_to_volume_idx(x, y)))
                for x, y in [(1000.0, 2000.0), (1455.5, 2310.25)]
            ],
            "time_idx": [f(full.time_ms_to_sample_idx(t)) for t in
                         [0.0, 2.0, 63.0, 126.0, -4.0, 500.0]],
            "sample_to_time": [f(full.sample_idx_to_time_ms(s))
                               for s in [0.0, 1.0, 31.5, 63.0]],
            "idx_to_il_xl": [
                list(map(f, full.volume_idx_to_il_xl(i, x)))
                for i, x in [(0, 0), (19, 9), (5.5, 2.25)]
            ],
            "clamp": [list(full.clamp_indices(i, x, t))
                      for i, x, t in [(-3, 4, 2), (100, -2, 70), (9, 4, 31.6)]],
            "world_xyz": [list(full.world_xyz_to_volume(x, y, z))
                          for x, y, z in [(1000, 2000, 0.0),
                                          (1900, 2600, 126.0)]],
        },
        "preview": {
            "strides": list(preview.strides),
            "idx": [
                list(map(f, preview.il_xl_to_volume_idx(il, xl)))
                for il, xl in [(1, 1), (11, 5), (13, 7)]
            ],
            "time_idx": [f(preview.time_ms_to_sample_idx(t)) for t in
                         [0.0, 4.0, 126.0]],
            "sample_to_time": [f(preview.sample_idx_to_time_ms(s))
                               for s in [0.0, 1.0, 31.0]],
        },
        "explicit_same_as_preview": list(explicit.strides),
        "errors": [],
    }
    zero_dt = survey_from_corners(
        (1, 1, 0.0, 0.0), (1, 4, 0.0, 300.0), (6, 4, 400.0, 300.0),
        n_samples=8, dt_ms=0.0)
    try:
        full.time_ms_to_sample_idx(0.0)
        zero_dt_case = {"name": "dt_zero_on_survey_with_dt", "raised": False}
    except ValueError:
        zero_dt_case = {"name": "dt_zero_on_survey_with_dt", "raised": True}
    out["errors"].append(zero_dt_case)
    for name, shape, strides in [
        ("stride_shape_mismatch", (10, 5, 33), (2, 2, 2)),
        ("loaded_above_native", (21, 5, 32), None),
        ("zero_stride", (10, 5, 32), (0, 1, 1)),
    ]:
        try:
            if strides is None:
                VolumeRegistration(spec, *shape)
            else:
                VolumeRegistration(spec, *shape, strides=strides)
            out["errors"].append({"name": name, "raised": False})
        except ValueError as ex:
            out["errors"].append({"name": name, "raised": True,
                                  "message": str(ex)})
    return out


def case_depth_transform() -> dict:
    out = {"cases": [], "errors": []}
    for name, state in {
        "default_none": select_depth_transform(),
        "external": select_depth_transform(has_external_volume=True,
                                           v0_m_s=2400.0),
        "constant": select_depth_transform(constant_v0=True, v0_m_s=2800.5),
        "well_tz_reserved": DepthTransformState(
            kind=__import__(
                "geoviz_well_seismic_3d.depth_transform",
                fromlist=["DepthTransformKind"]).DepthTransformKind.WELL_TZ_FIELD),
    }.items():
        entry = {
            "name": name,
            "available": bool(state.available),
            "warning": state.approximate_warning,
        }
        if state.available:
            entry["t2d"] = [f(state.time_ms_to_depth_m(t))
                            for t in [0.0, 100.0, 2500.5]]
            entry["d2t"] = [f(state.depth_m_to_time_ms(d))
                            for d in [0.0, 150.0, 3000.0]]
        out["cases"].append(entry)
    try:
        __import__(
            "geoviz_well_seismic_3d.depth_transform",
            fromlist=["ConstantVelocityDepth"]).ConstantVelocityDepth(0.0)
        out["errors"].append({"name": "v0_zero", "raised": False})
    except ValueError as ex:
        out["errors"].append({"name": "v0_zero", "raised": True,
                              "message": str(ex)})
    return out


def case_td_and_geometry() -> dict:
    td = TimeDepthTable("W-1",
                        time_ms=np.array([0.0, 200.0, 700.0, 1500.0]),
                        md_m=np.array([0.0, 250.0, 1000.0, 2000.0]))
    well = WellHead(name="W-1", x=1200.0, y=2100.0, bottom_x=1230.0,
                    bottom_y=2130.0, total_depth_m=2000.0, id="w1")
    well_deep = WellHead(name="W-deep", x=0.0, y=0.0, bottom_x=0.0,
                         bottom_y=0.0, total_depth_m=4000.0, id="w2")
    out = {
        "td": {
            "md_range": [f(td.md_range[0]), f(td.md_range[1])],
            "md_to_time": [f(v) for v in td.md_to_time_ms(
                np.array([-1.0, 0.0, 125.0, 250.0, 1500.0, 2000.0, 2500.0]))],
            "time_to_md": [f(v) for v in td.time_ms_to_md(
                np.array([-5.0, 0.0, 200.0, 900.0, 1500.0, 2000.0]))],
        },
        "trajectory_time": {
            "n_points": None, "has_td": None, "warning": None, "head": None,
            "first": None, "last": None,
        },
        "trajectory_time_deep_truncated": {},
        "trajectory_time_no_td": {},
        "trajectory_depth_no_transform": {},
        "trajectory_depth_v0": {},
        "pierce": {},
        "overlay": {},
        "errors": [],
    }
    traj = project_well_trajectory(well, domain=VerticalDomain.TIME,
                                   td=td, n_samples=8)
    out["trajectory_time"].update({
        "n_points": int(traj.points.shape[0]), "has_td": traj.has_td,
        "warning": traj.warning,
        "head": [f(v) for v in traj.points[0]],
        "first": [f(v) for v in traj.points[1]],
        "last": [f(v) for v in traj.points[-1]],
    })
    traj_deep = project_well_trajectory(
        well_deep, domain=VerticalDomain.TIME, td=TimeDepthTable(
            "W-deep", time_ms=np.array([0.0, 400.0]),
            md_m=np.array([0.0, 1000.0])), n_samples=8)
    out["trajectory_time_deep_truncated"] = {
        "n_points": int(traj_deep.points.shape[0]),
        "warning": traj_deep.warning,
        "last_md_z": f(traj_deep.points[-1][2]) if traj_deep.points.size else None,
    }
    traj_no_td = project_well_trajectory(well, domain=VerticalDomain.TIME, td=None)
    out["trajectory_time_no_td"] = {
        "n_points": int(traj_no_td.points.shape[0]),
        "has_td": traj_no_td.has_td, "warning": traj_no_td.warning,
    }
    traj_depth_none = project_well_trajectory(
        well, domain=VerticalDomain.DEPTH, td=td, depth_transform=None)
    out["trajectory_depth_no_transform"] = {
        "n_points": int(traj_depth_none.points.shape[0]),
        "warning": traj_depth_none.warning,
    }
    depth_state = select_depth_transform(constant_v0=True, v0_m_s=2500.0)
    traj_depth = project_well_trajectory(
        well, domain=VerticalDomain.DEPTH, td=td, depth_transform=depth_state,
        n_samples=8)
    out["trajectory_depth_v0"] = {
        "n_points": int(traj_depth.points.shape[0]), "has_td": traj_depth.has_td,
        "last": [f(v) for v in traj_depth.points[-1]],
    }
    pts = np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 100.0], [10.0, 5.0, 200.0]])
    out["pierce"] = {
        "at_100": [f(v) for v in pierce_xy_at_z(pts, 100.0)],
        "at_50": [f(v) for v in pierce_xy_at_z(pts, 50.0)],
        "at_exact_200": [f(v) for v in pierce_xy_at_z(pts, 200.0)],
        "outside": pierce_xy_at_z(pts, 500.0),
        "below": pierce_xy_at_z(pts, -1.0),
    }
    path = np.array([[0.0, 0.0, k] for k in range(4)], dtype=np.float32)
    overlay = offset_curve_along_trajectory(
        path, np.array([0.0, 1.0, -1.0, 0.5], dtype=np.float32), scale=2.0)
    out["overlay"] = [[f(v) for v in row] for row in overlay]
    for name, args in {
        "overlay_short_curve": (
            np.zeros((4, 3), dtype=np.float32),
            np.zeros(2, dtype=np.float32)),
    }.items():
        try:
            offset_curve_along_trajectory(*args)
            out["errors"].append({"name": name, "raised": False})
        except ValueError as ex:
            out["errors"].append({"name": name, "raised": True,
                                  "message": str(ex)})
    return out


def case_fence_probe() -> dict:
    spec = survey_from_corners(
        (1, 1, 1000.0, 2000.0), (1, 10, 1900.0, 2000.0),
        (20, 10, 1900.0, 2600.0), n_samples=64, dt_ms=2.0)
    ni, nx, nt = 20, 10, 64
    data = np.zeros((ni, nx, nt), dtype=np.float32)
    for i in range(ni):
        for x in range(nx):
            for t in range(nt):
                data[i, x, t] = (i * 7 + x * 3 + t) % 97 - 48.0
    data[0, 0, 0] = np.nan
    data[19, 9, 63] = np.inf
    access = InMemoryVolumeAccess(data)
    fence = FenceSection(name="F1", vertices_xy=np.array(
        [[1000.0, 2000.0], [1900.0, 2000.0], [1900.0, 2600.0]]), id="fence-1")
    out = {
        "sample_polyline": [
            [f(p[0]), f(p[1])] for p in sample_fence_polyline(
                fence.vertices_xy, 5)
        ],
        "extract": {},
        "probe": {},
        "errors": [],
    }
    reg = VolumeRegistration.from_survey_and_shape(spec, (ni, nx, nt))
    ext = extract_fence_strip(access, fence=fence, n_along=4,
                              sample_axis=np.arange(nt, dtype=np.float64) * 2.0,
                              registration=reg)
    amp = np.asarray(ext.amplitude, dtype=np.float32)
    out["extract"] = {
        "fence_id": ext.fence_id,
        "shape": [int(amp.shape[0]), int(amp.shape[1])],
        "arc_length": [f(v) for v in ext.arc_length_m],
        "row0_first8": [f(v) for v in amp[0, :8]],
        "row3_last8": [f(v) for v in amp[3, -8:]],
        "sample_axis_first4": [f(v) for v in ext.sample_axis[:4]],
    }
    probe = probe_from_fence_s(s_m=500.0, z=100.0,
                               vertices_xy=fence.vertices_xy, survey=spec)
    out["probe"] = {
        "s_m": f(probe.s_m), "z": f(probe.z), "x": f(probe.x), "y": f(probe.y),
        "il": f(probe.il), "xl": f(probe.xl),
        "slice_indices": [int(v) for v in probe.slice_indices(spec)],
        "slice_indices_none": [int(v) for v in probe.slice_indices(None)],
    }
    try:
        FenceSection(name="bad", vertices_xy=np.zeros((1, 2)))
        out["errors"].append({"name": "fence_single_vertex", "raised": False})
    except ValueError as ex:
        out["errors"].append({"name": "fence_single_vertex", "raised": True,
                              "message": str(ex)})
    return out


def case_color_scales() -> dict:
    amp = np.array([-100.0, -50.0, -0.001, 0.0, 0.001, 30.0, 80.0, np.nan,
                    1e9, -1e9, 0.5, 127.5, 12.75],
                   dtype=np.float32)
    rgba = colorize_amplitude(amp)
    gr = np.array([0.0, 0.25, 0.5, 0.75, 1.0, 0.125, np.nan, 0.99999, -3.0,
                   4.0])
    gr_rgba = colorize_gr(gr, value_range=(0.0, 1.0))
    gr_rgba_cividis = colorize_gr(gr, value_range=(0.0, 1.0),
                                  color_scale="cividis")
    gr_bad_range = colorize_gr(np.array([5.0]), value_range=(2.0, 2.0))
    return {
        "amplitude_rgba": [int(v) for v in rgba.reshape(-1)],
        "gr_rgba": [int(v) for v in gr_rgba.reshape(-1)],
        "gr_rgba_cividis": [int(v) for v in gr_rgba_cividis.reshape(-1)],
        "gr_bad_range": [int(v) for v in gr_bad_range.reshape(-1)],
    }


def case_scene_maps_and_state() -> dict:
    spec = survey_from_corners(
        (1, 1, 1000.0, 2000.0), (1, 10, 1900.0, 2000.0),
        (20, 10, 1900.0, 2600.0), n_samples=64, dt_ms=2.0)
    ni, nx, nt = 20, 10, 64
    data = np.zeros((ni, nx, nt), dtype=np.float32)
    for i in range(ni):
        for x in range(nx):
            for t in range(nt):
                data[i, x, t] = float((i * 11 + x * 5 + t * 2) % 89) - 44.0
    scene = WellSeismicScene()
    scene.set_survey(spec)
    scene.set_volume_access(InMemoryVolumeAccess(data))
    td = TimeDepthTable("W-1", time_ms=np.array([0.0, 300.0, 1200.0]),
                        md_m=np.array([0.0, 500.0, 1800.0]))
    scene.set_wells(
        [WellHead(name="W-1", x=1200.0, y=2100.0, bottom_x=1230.0,
                  bottom_y=2130.0, total_depth_m=1800.0, id="w1")],
        {"W-1": td})
    scene.add_time_slice(64.0)
    scene.add_time_slice(20.0)

    world = np.array([
        [1000.0, 2000.0, 0.0], [1450.0, 2300.0, 64.0],
        [1900.0, 2600.0, 126.0], [1300.0, 2200.0, -10.0]])
    render = scene.world_to_render_xyz_array(world)
    back = scene.render_to_world_xyz_array(render)
    out = {
        "render": [[f(v) for v in row] for row in render],
        "render_back": [[f(v) for v in row] for row in back],
        "survey_only_render": None,
        "slice_state": {
            "il": scene.orthogonal_slice_state.inline_index,
            "xl": scene.orthogonal_slice_state.crossline_index,
            "slices": [[f(s.time_ms), s.visible] for s in
                       scene.orthogonal_slice_state.time_slices],
            "active": f(scene.orthogonal_slice_state.active_time_ms),
            "opacity": f(scene.orthogonal_slice_state.time_opacity),
            "warning": scene.slice_state_warning,
        },
        "render_state": None,
        "snap": [f(scene._snap_time_ms(t)) for t in
                 [0.0, 3.9, 5.0, 126.0, 130.0, -3.0]],
        "validate_corners": None,
        "depth_refused": None,
        "pierce": {},
        "pierce_none_when_depth": None,
        "fence_well_flow": {},
    }
    rs = scene.orthogonal_slice_render_state()
    out["render_state"] = {
        "il": rs[0], "xl": rs[1],
        "times": [[int(t), v] for t, v in rs[2]],
        "active": int(rs[3]), "opacity": f(rs[4]),
    }
    ok, msg = scene.validate_against_corners(
        (1, 1, 1000.0, 2000.0), (1, 10, 1900.0, 2000.0),
        (20, 10, 1900.0, 2600.0))
    bad, bad_msg = scene.validate_against_corners(
        (1, 1, 1000.0, 2000.0), (1, 10, 1900.0, 2000.0),
        (20, 10, 2900.0, 2600.0))
    out["validate_corners"] = {
        "ok": bool(ok), "msg": msg, "bad_ok": bool(bad), "bad_msg": bad_msg,
    }
    try:
        scene.set_vertical_domain(VerticalDomain.DEPTH)
        out["depth_refused"] = False
    except ValueError as ex:
        out["depth_refused"] = str(ex)
    pierce = scene.pierce_points_on_active_time()
    out["pierce"] = {
        "count": len(pierce),
        "first": ([pierce[0].x, pierce[0].y, pierce[0].z]
                  if pierce else None),
    }
    # Well-to-well fence flow (single well → ValueError without TD reach).
    try:
        scene.add_well_to_well_fence(["w1"])
        out["fence_well_flow"]["single_well_raised"] = False
    except ValueError as ex:
        out["fence_well_flow"]["single_well_raised"] = str(ex)

    # Survey-only (no volume) map: fresh scene.
    scene2 = WellSeismicScene()
    scene2.set_survey(spec)
    out["survey_only_render"] = [
        [f(v) for v in row] for row in scene2.world_to_render_xyz_array(world)
    ]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",
                        default=str(REPO / "tests/cpp/viz_c/fixtures"))
    args = parser.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    fixture = {
        "source": ("geo-viz-engine@08851951f3bbc0beb90886adf52e1928f4383c16 "
                   "packages/geoviz_well_seismic_3d"),
        "generator": "tools/oracle/generate_viz_c_fixtures.py",
        "note": "exact float64 equality expected on the C++ side",
        "survey": case_survey(),
        "registration": case_registration(),
        "depth_transform": case_depth_transform(),
        "td_and_geometry": case_td_and_geometry(),
        "fence_probe": case_fence_probe(),
        "color_scales": case_color_scales(),
        "scene": case_scene_maps_and_state(),
    }
    # NaN/inf appear deliberately (TD-out-of-range markers, colorize
    # guards): keep them as explicit string markers instead of JSON nan.
    def encode(obj):
        if isinstance(obj, float):
            if math.isnan(obj):
                return "nan"
            if math.isinf(obj):
                return "inf" if obj > 0 else "-inf"
            return obj
        if isinstance(obj, dict):
            return {k: encode(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [encode(v) for v in obj]
        return obj

    text = json.dumps(encode(fixture), indent=1, ensure_ascii=False,
                      allow_nan=False)
    path = out_dir / "viz_c_joint_oracle.json"
    path.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {path} ({len(text)} bytes)")

    # Negative self-check input: one perturbed amplitude value that the
    # C++ replay MUST detect (and the Python side recorded verbatim).
    tampered = json.loads(text)
    tampered["color_scales"]["amplitude_rgba"][7] = (
        tampered["color_scales"]["amplitude_rgba"][7] + 1) % 256
    tampered_path = out_dir / "viz_c_joint_oracle_tampered.json"
    tampered_path.write_text(
        json.dumps(tampered, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(f"wrote {tampered_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
