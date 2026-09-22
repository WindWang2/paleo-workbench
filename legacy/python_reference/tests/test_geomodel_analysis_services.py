"""Behavior tests for the extracted 3D geomodel analysis services.

Covers the pure service modules extracted from ``GeologicalModeling3DPage``:
``paleo_workbench.viz.geomodel.analysis`` (scientific/algorithm methods),
``paleo_workbench.viz.geomodel.lithology`` (shared property tables), and
``paleo_workbench.viz.geomodel.demo`` (explicit demo providers). These tests
run WITHOUT widgets/GL — pure numpy + geoviz engine only (mirrors the
``test_geomodel_geometry_generators`` pattern).
"""
from __future__ import annotations

import numpy as np

from paleo_workbench.viz.geomodel import analysis, demo, lithology

from geoviz import analyze_lithology_crossplot


# --- fixtures ----------------------------------------------------------------

def _demo_boreholes() -> list[dict]:
    """Two boreholes with the demo layer stacks (from the modeling worker)."""
    return [
        {
            "name": "钻孔 HZ21-1", "x": -40.0, "y": -40.0, "total_depth": 150.0,
            "layers": [
                {"top": 0.0, "bottom": 30.0, "lithology": "砂岩"},
                {"top": 30.0, "bottom": 75.0, "lithology": "泥岩"},
                {"top": 75.0, "bottom": 120.0, "lithology": "石灰岩"},
                {"top": 120.0, "bottom": 150.0, "lithology": "花岗岩"},
            ],
        },
        {
            "name": "钻孔 HZ19-6", "x": 40.0, "y": -40.0, "total_depth": 180.0,
            "layers": [
                {"top": 0.0, "bottom": 40.0, "lithology": "砂岩"},
                {"top": 40.0, "bottom": 90.0, "lithology": "泥岩"},
                {"top": 90.0, "bottom": 140.0, "lithology": "石灰岩"},
                {"top": 135.0, "bottom": 180.0, "lithology": "花岗岩"},
            ],
        },
    ]


# --- lithology tables ---------------------------------------------------------

def test_lithology_tables_cover_all_demo_lithologies():
    names = {"砂岩", "泥岩", "石灰岩", "花岗岩"}
    for table in (
        lithology.LITHO_GR,
        lithology.LITHO_SONIC,
        lithology.LITHO_DENSITY,
        lithology.LITHO_AI,
    ):
        assert names.issubset(set(table))


def test_sample_log_values_assigns_per_layer_and_default():
    layers = [
        {"top": 0.0, "bottom": 30.0, "lithology": "砂岩"},
        {"top": 30.0, "bottom": 60.0, "lithology": "未知岩性"},
    ]
    depths = np.array([0.0, 10.0, 40.0, 70.0, 90.0], dtype=np.float32)
    values = lithology.sample_log_values(
        layers, depths, lithology.LITHO_GR, lithology.DEFAULT_GR
    )
    assert values.dtype == np.float32
    # 砂岩 covered depth -> table value
    assert values[0] == lithology.LITHO_GR["砂岩"]
    # covered depth with unknown lithology -> default
    assert values[2] == lithology.DEFAULT_GR
    # uncovered depths -> 0.0 (mirrors the original inline mask loop)
    assert values[3] == 0.0
    assert values[4] == 0.0


# --- analysis.generate_well_curve_overlays -------------------------------------

def test_generate_well_curve_overlays_shape_and_offsets():
    overlays = analysis.generate_well_curve_overlays(_demo_boreholes(), freq=30.0, td_shift=5.0)
    assert len(overlays) == 2

    for overlay in overlays:
        well_path = overlay["well_path"]
        curve_pts = overlay["curve_pts"]
        n = len(well_path)
        assert curve_pts.shape == (n, 3)
        assert well_path.dtype == np.float32
        # Z axis: upward (surface at 0, depth negative)
        assert well_path[:, 2].max() == 0.0
        assert well_path[:, 2].min() < 0.0
        # The GR curve is offset sideways off the trajectory (not identical rows)
        assert not np.array_equal(curve_pts[:, :2], well_path[:, :2])
        # Synthetic seismogram + aligned/offset path present
        assert overlay["synthetic"].ndim == 1
        assert overlay["synthetic"].size > 0
        assert overlay["syn_curve_pts"].shape == (overlay["synthetic"].size, 3)


def test_generate_well_curve_overlays_skips_empty_boreholes():
    overlays = analysis.generate_well_curve_overlays(
        [{"name": "X", "x": 0.0, "y": 0.0, "total_depth": 10.0, "layers": []}],
        freq=30.0, td_shift=0.0,
    )
    assert overlays == []


def test_generate_well_curve_overlays_is_deterministic():
    a = analysis.generate_well_curve_overlays(_demo_boreholes(), freq=45.0, td_shift=-10.0)
    b = analysis.generate_well_curve_overlays(_demo_boreholes(), freq=45.0, td_shift=-10.0)
    for oa, ob in zip(a, b):
        assert np.array_equal(oa["curve_pts"], ob["curve_pts"])
        assert np.array_equal(oa["syn_curve_pts"], ob["syn_curve_pts"])


# --- analysis.generate_seismic_slice_overlay -----------------------------------

def test_generate_seismic_slice_overlay_geometry():
    verts, faces, colors = analysis.generate_seismic_slice_overlay()
    assert verts.dtype == np.float32 and verts.shape[1] == 3
    assert faces.dtype == np.int32 and faces.shape[1] == 3
    assert colors.shape == (len(faces), 4)
    # 30x30 grid -> 900 vertices, 2 triangles per quad -> 2*29*29 faces
    assert len(verts) == 900
    assert len(faces) == 2 * 29 * 29
    # Z is a horizontal slice (negative, gently undulating)
    assert np.all(verts[:, 2] < 0)


# --- analysis.run_auto_tie -----------------------------------------------------

def test_run_auto_tie_returns_shift_and_cc():
    result = analysis.run_auto_tie(_demo_boreholes(), freq=30.0)
    assert result is not None
    assert isinstance(result["shift_samples"], int)
    assert isinstance(result["cc"], float)
    assert 0.0 <= result["cc"] <= 1.0


def test_run_auto_tie_empty_data_returns_none():
    assert analysis.run_auto_tie([], freq=30.0) is None


# --- analysis.generate_rgb_fusion_slice -----------------------------------------

def test_generate_rgb_fusion_slice_geometry():
    verts, faces, face_colors = analysis.generate_rgb_fusion_slice()
    assert verts.dtype == np.float32 and verts.shape[1] == 3
    assert faces.dtype == np.int32 and faces.shape[1] == 3
    assert face_colors.shape == (len(faces), 4)
    assert face_colors.dtype == np.float32
    # 40x40 grid -> 1600 vertices
    assert len(verts) == 1600


# --- analysis.generate_cross_well_fence ------------------------------------------

def test_generate_cross_well_fence_connects_boreholes():
    mesh = analysis.generate_cross_well_fence(_demo_boreholes(), nz_samples=25)
    assert mesh is not None
    verts, faces, colors = mesh
    assert len(verts) > 0 and len(faces) > 0
    assert colors.shape == (len(faces), 4)


def test_generate_cross_well_fence_empty_returns_none():
    assert analysis.generate_cross_well_fence([]) is None


# --- analysis.run_lithology_crossplot --------------------------------------------

def test_run_lithology_crossplot_matches_direct_engine_call():
    bh_raw = _demo_boreholes()
    result = analysis.run_lithology_crossplot(bh_raw)
    assert set(result) == {"points", "clusters"}

    # Equivalent to the direct engine call with the same demo sampling.
    gr_list, ai_list, lith_list = demo.crossplot_samples(bh_raw)
    expected = analyze_lithology_crossplot(
        np.array(gr_list, dtype=np.float32),
        np.array(ai_list, dtype=np.float32),
        lith_list,
    )
    assert result == expected


def test_run_lithology_crossplot_empty_data_has_no_points():
    result = analysis.run_lithology_crossplot([])
    assert result["points"] == []
    assert result["clusters"] == {}


# --- demo providers (explicit, NOT production code) --------------------------------

def test_demo_gr_noise_shape_and_determinism():
    noise = demo.gr_noise(100)
    assert noise.shape == (100,)
    assert noise.dtype == np.float32
    assert np.array_equal(noise, demo.gr_noise(100))  # fixed seed


def test_demo_synthetic_field_trace_is_deterministic_shifted_noisy():
    synthetic = np.sin(np.linspace(0, 10, 200))
    trace = demo.synthetic_field_trace(synthetic)
    assert trace.shape == synthetic.shape
    # Deterministic (fixed seed)
    assert np.array_equal(trace, demo.synthetic_field_trace(synthetic))
    # A shifted + noisy variant, never identical to the plain synthetic.
    assert not np.array_equal(trace, synthetic)


def test_demo_crossplot_samples_counts_and_tables():
    gr_list, ai_list, lith_list = demo.crossplot_samples(_demo_boreholes())
    # 2 boreholes * 4 layers * 10 samples
    assert len(gr_list) == len(ai_list) == len(lith_list) == 80
    assert set(lith_list) == {"砂岩", "泥岩", "石灰岩", "花岗岩"}
    # Values hover around the table bases (GR 25..120, AI thousands)
    assert min(gr_list) >= 0 and max(gr_list) <= 200
    assert min(ai_list) > 2000
