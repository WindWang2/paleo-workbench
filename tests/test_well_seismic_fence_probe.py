"""Fence extract, multi-fence, probe, depth, profile assembly (#60–#64)."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from geoviz_well_seismic_3d import (
    FenceSection,
    InMemoryVolumeAccess,
    JointWellId,
    TimeDepthTable,
    VerticalDomain,
    WellHead,
    WellSeismicScene,
    select_depth_transform,
    survey_from_corners,
)

P1 = (1315, 4165, 0.0, 0.0)
P2 = (1315, 4805, 12793.0, 0.0)
P3 = (1725, 4805, 12793.0, 16406.0)


def _scene_with_volume() -> WellSeismicScene:
    scene = WellSeismicScene()
    scene.set_survey_from_corners(P1, P2, P3, n_samples=16, dt_ms=2.0)
    vol = np.random.randn(8, 8, 16).astype(np.float32)
    scene.set_volume_access(InMemoryVolumeAccess(vol))
    scene.set_preview_mode(True)
    scene.set_wells(
        [
            WellHead(
                "A1",
                1000,
                2000,
                1000,
                2000,
                100,
                id=JointWellId("source:a1"),
            ),
            WellHead(
                "A2",
                3000,
                4000,
                3000,
                4000,
                100,
                id=JointWellId("source:a2"),
            ),
        ]
    )
    return scene


def test_shared_fence_extract_identity():
    scene = _scene_with_volume()
    fence = FenceSection(
        name="F1",
        vertices_xy=np.array([[0.0, 0.0], [5000.0, 5000.0]], dtype=np.float64),
    )
    scene.add_fence(fence)
    a = scene.extract_active_fence(n_along=32)
    b = scene.extract_active_fence(n_along=32)
    assert a is not None and b is not None
    assert a.fence_id == b.fence_id
    assert a.amplitude.shape == b.amplitude.shape
    np.testing.assert_array_equal(a.amplitude, b.amplitude)


def test_extract_active_fence_domain_override_time_while_scene_depth():
    """Unified domain policy: 2D and 3D share the scene domain (old #122 split removed).

    Depth still requires an explicit transform (fail-closed); the extraction
    ``domain`` override remains an API for callers that manage their own
    domain, and Time/Depth axes differ by the transform.
    """
    scene = _scene_with_volume()
    scene.add_fence(
        FenceSection(
            name="F1",
            vertices_xy=np.array([[0.0, 0.0], [5000.0, 5000.0]], dtype=np.float64),
        )
    )
    scene.set_depth_transform(select_depth_transform(constant_v0=True, v0_m_s=3000.0))
    scene.set_vertical_domain(VerticalDomain.DEPTH)
    assert scene.vertical_domain is VerticalDomain.DEPTH
    # Default extraction (what the 2D profile uses) follows the scene domain.
    default_ext = scene.extract_active_fence(n_along=16)
    depth_ext = scene.extract_active_fence(n_along=16, domain=VerticalDomain.DEPTH)
    time_ext = scene.extract_active_fence(n_along=16, domain=VerticalDomain.TIME)
    assert default_ext is not None and depth_ext is not None and time_ext is not None
    # 2D and 3D consumers see the SAME (depth) axis by default — no split-brain.
    np.testing.assert_allclose(default_ext.sample_axis, depth_ext.sample_axis)
    # Time axis is ms-scale (survey t0 + n*dt); Depth axis is metres via V0
    assert float(time_ext.sample_axis[-1]) != float(depth_ext.sample_axis[-1])
    # Scene domain still Depth after override extract
    assert scene.vertical_domain is VerticalDomain.DEPTH


def test_depth_domain_unavailable_without_transform():
    """Fail-closed: Depth is refused while no time-depth transform exists."""
    scene = _scene_with_volume()
    assert scene.depth_available is False
    with pytest.raises(ValueError, match="no time-depth transform"):
        scene.set_vertical_domain(VerticalDomain.DEPTH)
    assert scene.vertical_domain is VerticalDomain.TIME
    scene.set_depth_transform(select_depth_transform(constant_v0=True))
    assert scene.depth_available is True
    scene.set_vertical_domain(VerticalDomain.DEPTH)
    assert scene.vertical_domain is VerticalDomain.DEPTH


def test_multi_fence_active_and_well_to_well():
    scene = _scene_with_volume()
    f1 = scene.add_fence(
        FenceSection("A", np.array([[0, 0], [1000, 0]], dtype=float)), activate=True
    )
    f2 = scene.add_fence(
        FenceSection("B", np.array([[0, 0], [0, 1000]], dtype=float)), activate=False
    )
    assert scene.active_fence_id == f1.id
    scene.set_active_fence(f2.id)
    assert scene.active_fence_id == f2.id
    scene.set_fence_visible(f1.id, False)
    assert scene.fences[0].visible is False
    ww = scene.add_well_to_well_fence(["A1", "A2"], name="W2W")
    assert ww.name == "W2W"
    assert scene.active_fence_id == ww.id
    assert len(ww.vertices_xy) == 2


def test_well_to_well_fence_accepts_joint_well_ids_for_duplicate_names():
    scene = _scene_with_volume()
    scene.set_wells(
        [
            WellHead(
                "A1",
                1000,
                2000,
                1000,
                2000,
                100,
                id=JointWellId("source:a1-left"),
            ),
            WellHead(
                "A1",
                3000,
                4000,
                3000,
                4000,
                100,
                id=JointWellId("source:a1-right"),
            ),
        ]
    )

    fence = scene.add_well_to_well_fence(
        [JointWellId("source:a1-left"), JointWellId("source:a1-right")]
    )

    np.testing.assert_array_equal(
        fence.vertices_xy,
        np.array([[1000.0, 2000.0], [3000.0, 4000.0]]),
    )


def test_remove_active_fence_keeps_others():
    """#124: delete active; remaining fences stay; active moves to last."""
    scene = _scene_with_volume()
    f1 = scene.add_fence(
        FenceSection("A", np.array([[0, 0], [1000, 0]], dtype=float)), activate=True
    )
    f2 = scene.add_fence(
        FenceSection("B", np.array([[0, 0], [0, 1000]], dtype=float)), activate=True
    )
    assert scene.active_fence_id == f2.id
    assert scene.remove_active_fence() is True
    assert len(scene.fences) == 1
    assert scene.fences[0].id == f1.id
    assert scene.active_fence_id == f1.id
    assert scene.remove_active_fence() is True
    assert scene.fences == []
    assert scene.active_fence_id is None
    assert scene.remove_active_fence() is False


def test_near_well_filter_and_curve_fallback():
    scene = _scene_with_volume()
    scene.add_fence(
        FenceSection("F", np.array([[1000.0, 2000.0], [3000.0, 4000.0]], dtype=float))
    )
    scene.set_near_well_distance_m(50.0)
    scene.set_formation_tops({"A1": [("C3", 100.0)]})
    md = np.linspace(0, 100, 5)
    scene.set_well_curves(
        {
            "A1": {
                "SP": (md, md),
                "GR": (md, md * 2),
            }
        }
    )
    hits = scene.assemble_active_profile_wells()
    names = {h.name for h in hits}
    assert "A1" in names
    a1 = next(h for h in hits if h.name == "A1")
    assert a1.curve_name == "GR"
    assert a1.tops[0][0] == "C3"


def test_profile_assembly_uses_per_well_visibility_and_identity():
    scene = _scene_with_volume()
    scene.set_wells(
        [
            WellHead(
                "A1", 1000, 2000, 1000, 2000, 100, id=JointWellId("source:a1-left")
            ),
            WellHead(
                "A1", 2000, 3000, 2000, 3000, 100, id=JointWellId("source:a1-mid")
            ),
            WellHead(
                "B1", 3000, 4000, 3000, 4000, 100, id=JointWellId("source:b1")
            ),
        ]
    )
    scene.add_fence(
        FenceSection(
            "F",
            np.array([[1000.0, 2000.0], [3000.0, 4000.0]], dtype=float),
        )
    )

    scene.set_well_visibility(JointWellId("source:a1-mid"), False)

    assert [
        (hit.id, hit.display_name)
        for hit in scene.assemble_active_profile_wells()
    ] == [
        (JointWellId("source:a1-left"), "A1 (1)"),
        (JointWellId("source:b1"), "B1"),
    ]


def test_profile_assembly_maps_gr_measurement_depths_to_time():
    scene = WellSeismicScene()
    scene.set_wells(
        [
            WellHead(
                "A1",
                0,
                0,
                0,
                0,
                100,
                id=JointWellId("source:a1"),
            )
        ],
        td_tables={
            "A1": TimeDepthTable(
                well_name="A1",
                time_ms=np.array([0.0, 1000.0]),
                md_m=np.array([0.0, 100.0]),
            )
        },
    )
    scene.set_well_curves(
        {
            "A1": {
                "GR": (
                    np.array([0.0, 50.0, 100.0]),
                    np.array([10.0, 20.0, 30.0]),
                )
            }
        }
    )
    scene.add_fence(
        FenceSection(
            "F",
            np.array([[0.0, 0.0], [100.0, 0.0]], dtype=float),
        )
    )

    hit = scene.assemble_active_profile_wells(
        domain=VerticalDomain.TIME
    )[0]

    assert hit.curve_name == "GR"
    assert hit.curve_z.tolist() == [0.0, 500.0, 1000.0]


def test_probe_slice_indices():
    scene = _scene_with_volume()
    scene.add_fence(
        FenceSection("F", np.array([[0.0, 0.0], [10000.0, 10000.0]], dtype=float))
    )
    probe = scene.set_probe(s_m=100.0, z=20.0)
    # A valid probe lies on the fence at s=100m along the diagonal
    # (0,0)->(10000,10000): distance from the origin is s=100m, so the point
    # must be ~(70.71, 70.71). The prior `isinstance` check passed for any
    # numeric value including a (0,0) degenerate (F5).
    assert probe.x == pytest.approx(70.71067811865476, abs=1e-6)
    assert probe.y == pytest.approx(70.71067811865476, abs=1e-6)
    idx = scene.probe_slice_indices()
    assert idx is not None
    assert len(idx) == 3


def test_depth_domain_and_v0_warning():
    scene = _scene_with_volume()
    scene.set_depth_transform(select_depth_transform(constant_v0=True, v0_m_s=2500))
    scene.set_vertical_domain(VerticalDomain.DEPTH)
    assert scene.vertical_domain is VerticalDomain.DEPTH
    assert scene.depth_transform.approximate_warning is not None


def test_registration_scales_preview_volume_indices():
    """Preview shape vs full survey — IL/XL fractions scale into volume range."""
    # Loader-aligned: IL along +X (641), XL along +Y (411)
    scene = WellSeismicScene()
    lp1 = (4165, 1315, 0.0, 0.0)
    lp2 = (4165, 1725, 0.0, 16406.0)
    lp3 = (4805, 1725, 12793.0, 16406.0)
    scene.set_survey_from_corners(lp1, lp2, lp3, n_samples=901, dt_ms=2.0)
    assert scene.survey.n_inlines == 641
    assert scene.survey.n_crosslines == 411
    # Preview downsampled from loader 641×411
    vol = np.zeros((107, 103, 113), dtype=np.float32)
    scene.set_volume_access(InMemoryVolumeAccess(vol))
    reg = scene.registration
    assert reg is not None
    vi, vx = reg.xy_to_volume_idx(6396.5, 8203.0)
    assert 0 <= vi < 107 and 0 <= vx < 103
    vi2, vx2 = reg.xy_to_volume_idx(5288.67, 8219.94)
    ii, xi, ti = reg.clamp_indices(vi2, vx2, reg.time_ms_to_sample_idx(900.0))
    assert 0 <= ii < 107 and 0 <= xi < 103 and 0 <= ti < 113
    scene.add_fence(
        FenceSection("F", np.array([[0.0, 0.0], [12793.0, 16406.0]], dtype=float))
    )
    ext = scene.extract_active_fence(n_along=16)
    assert ext is not None
    assert ext.amplitude.shape == (16, 113)


@pytest.mark.slow
def test_survey_matches_loader_volume_axes_on_real_segy():
    """#81/#84: survey n_il/n_xl match SeismicLoader; preview keeps axis order."""
    from pathlib import Path

    from geoviz_seismic.loader import SeismicLoader
    from geoviz_well_seismic_3d import survey_corners_from_segy
    from paleo_workbench.viz.seismic_load import load_seismic_volume_from_path

    segy = Path("data/地震体/200P_seismic.sgy")
    if not segy.is_file():
        pytest.skip("no demo SEGY")
    p1, p2, p3, meta = survey_corners_from_segy(segy)
    scene = WellSeismicScene()
    scene.set_survey_from_corners(
        p1, p2, p3, n_samples=meta["n_samples"], dt_ms=meta["dt_ms"]
    )
    loader = SeismicLoader(str(segy))
    try:
        m = loader.inspect()
    finally:
        loader.close()
    assert scene.survey.n_inlines == m.n_inlines == 641
    assert scene.survey.n_crosslines == m.n_crosslines == 411
    assert scene.survey.iline_start == m.iline_start
    assert scene.survey.xline_start == m.xline_start
    vol, _ = load_seismic_volume_from_path(str(segy))
    assert vol is not None
    # No transpose: preview axis0 aspect matches loader IL count
    assert vol.shape[0] > vol.shape[1]  # 107 > 103 ≈ 641/411
    scene.set_volume_access(InMemoryVolumeAccess(vol))
    reg = scene.registration
    assert reg is not None
    # Mid-survey XY and a well-like XY land inside preview indices
    for x, y in ((6396.5, 8203.0), (5288.67, 8219.94)):
        vi, vx = reg.xy_to_volume_idx(x, y)
        assert 0 <= vi < vol.shape[0], (x, y, vi)
        assert 0 <= vx < vol.shape[1], (x, y, vx)
    # Axis contract: survey full counts track volume axes (preview scaled)
    assert reg.n_inline == vol.shape[0]
    assert reg.n_crossline == vol.shape[1]


def test_signed_bingrid_loader_orientation():
    """Loader-aligned corners: IL +X / XL +Y with consistent xy↔il_xl."""
    lp1 = (4165.0, 1315.0, 0.0, 0.0)
    lp2 = (4165.0, 1725.0, 0.0, 16406.0)
    lp3 = (4805.0, 1725.0, 12793.0, 16406.0)
    s = survey_from_corners(lp1, lp2, lp3, n_samples=901, dt_ms=2.0)
    assert s.n_inlines == 641 and s.n_crosslines == 411
    x, y = s.il_xl_to_xy(4805.0, 1725.0)
    assert abs(x - 12793.0) < 1.0 and abs(y - 16406.0) < 1.0
    il, xl = s.xy_to_il_xl(6396.5, 8203.0)
    assert 4165 <= il <= 4805
    assert 1315 <= xl <= 1725


def test_probe_uses_registration_for_slice_indices():
    scene = _scene_with_volume()
    scene.add_fence(
        FenceSection("F", np.array([[0.0, 0.0], [10000.0, 10000.0]], dtype=float))
    )
    scene.set_probe(50.0, 10.0)
    idx = scene.probe_slice_indices()
    assert idx is not None
    il, xl, t = idx
    assert 0 <= il < 8 and 0 <= xl < 8 and 0 <= t < 16


def test_profile_amplitude_color_scale_is_blue_white_red_and_zero_centered():
    from geoviz_well_seismic_3d.profile_2d import FenceProfile2D

    image = FenceProfile2D.amplitude_image(
        np.array([[-1.0, 0.0, 1.0]], dtype=np.float32),
        color_scale="blue-white-red",
    )

    top = image.pixelColor(0, 0)
    middle = image.pixelColor(0, image.height() // 2)
    bottom = image.pixelColor(0, image.height() - 1)
    assert (top.red(), top.green(), top.blue()) == (33, 102, 172)
    assert (middle.red(), middle.green(), middle.blue()) == (255, 255, 255)
    assert (bottom.red(), bottom.green(), bottom.blue()) == (178, 24, 43)


def test_profile_gr_color_scale_uses_viridis_and_gray_for_missing_values():
    from geoviz_well_seismic_3d.profile_2d import FenceProfile2D

    colors = FenceProfile2D.gr_colors(
        np.array([0.0, 50.0, np.nan, 100.0]),
        value_range=(0.0, 100.0),
        color_scale="viridis",
    )

    assert tuple(colors[0, :3]) == (68, 1, 84)
    assert tuple(colors[-1, :3]) == (253, 231, 37)
    assert tuple(colors[2, :3]) == (115, 115, 115)


def test_profile_renders_thick_depth_varying_gr_well_and_two_legends(qtbot):
    from geoviz_well_seismic_3d import JointDisplaySettings
    from geoviz_well_seismic_3d.profile_2d import FenceProfile2D

    scene = _scene_with_volume()
    scene.set_wells(
        [
            WellHead(
                "A1",
                2000,
                3000,
                2000,
                3000,
                100,
                id=JointWellId("source:a1"),
            )
        ],
        td_tables={
            "A1": TimeDepthTable(
                well_name="A1",
                time_ms=np.array([0.0, 30.0]),
                md_m=np.array([0.0, 100.0]),
            )
        },
    )
    scene.set_well_curves(
        {
            "A1": {
                "GR": (
                    np.array([0.0, 33.0, 66.0, 100.0]),
                    np.array([0.0, 33.0, 66.0, 100.0]),
                )
            }
        }
    )
    scene.set_display_settings(
        JointDisplaySettings(well_width_px=5)
    )
    scene.add_fence(
        FenceSection(
            "F",
            np.array([[1000.0, 2000.0], [3000.0, 4000.0]]),
        )
    )
    profile = FenceProfile2D()
    qtbot.addWidget(profile)
    profile.set_extract_domain(VerticalDomain.TIME)
    profile.set_scene(scene)

    image = profile.rendered_image
    x = profile.plot_width // 2
    upper = image.pixelColor(x, image.height() // 4)
    lower = image.pixelColor(x, image.height() * 3 // 4)

    assert profile.legend_titles == ("地震振幅", "GR (API)")
    assert image.width() > profile.plot_width
    assert upper != lower
    assert sum(
        image.pixelColor(x + dx, image.height() // 4) == upper
        for dx in range(-3, 4)
    ) >= 4
