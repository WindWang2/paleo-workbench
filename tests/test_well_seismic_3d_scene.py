"""WellSeismicScene survey + Time-domain well projection (#58)."""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import MagicMock

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from geoviz_well_seismic_3d import (  # noqa: E402
    InMemoryVolumeAccess,
    JointWellId,
    OrthogonalSliceState,
    TimeDepthTable,
    TimeSliceState,
    VerticalDomain,
    WellHead,
    WellSeismicScene,
    survey_from_corners,
)

# Local rectangular corners matching data/层位 + SEGY text header style
P1 = (1315, 4165, 0.0, 0.0)
P2 = (1315, 4805, 12793.0, 0.0)
P3 = (1725, 4805, 12793.0, 16406.0)


def _scene_with_preview(
    shape: tuple[int, int, int] = (5, 7, 11),
) -> WellSeismicScene:
    scene = WellSeismicScene()
    scene.set_survey_from_corners(
        P1,
        P2,
        P3,
        n_samples=101,
        dt_ms=2.0,
        t0_ms=0.0,
    )
    scene.set_volume_access(
        InMemoryVolumeAccess(np.zeros(shape, dtype=np.float32))
    )
    return scene


def test_survey_from_corners_maps_xy_to_il_xl():
    survey = survey_from_corners(
        p1=P1, p2=P2, p3=P3, n_samples=901, dt_ms=2.0, t0_ms=0.0
    )
    il, xl = survey.xy_to_il_xl(0.0, 0.0)
    assert il == pytest.approx(1315.0, abs=0.5)
    assert xl == pytest.approx(4165.0, abs=0.5)

    il2, xl2 = survey.xy_to_il_xl(12793.0, 0.0)
    assert il2 == pytest.approx(1315.0, abs=0.5)
    assert xl2 == pytest.approx(4805.0, abs=0.5)

    il3, xl3 = survey.xy_to_il_xl(12793.0, 16406.0)
    assert il3 == pytest.approx(1725.0, abs=0.5)
    assert xl3 == pytest.approx(4805.0, abs=0.5)


def test_survey_roundtrip_il_xl_xy():
    survey = survey_from_corners(P1, P2, P3, n_samples=100, dt_ms=2.0)
    x, y = survey.il_xl_to_xy(1500.0, 4500.0)
    il, xl = survey.xy_to_il_xl(x, y)
    assert il == pytest.approx(1500.0, abs=0.5)
    assert xl == pytest.approx(4500.0, abs=0.5)


def test_scene_set_survey_from_corners_and_validate():
    scene = WellSeismicScene()
    scene.set_survey_from_corners(P1, P2, P3, n_samples=901, dt_ms=2.0)
    assert scene.survey is not None
    ok, msg = scene.validate_against_corners(P1, P2, P3)
    assert ok is True
    assert msg == ""


def test_scene_validate_against_mismatched_corners():
    scene = WellSeismicScene()
    scene.set_survey_from_corners(P1, P2, P3, n_samples=100, dt_ms=2.0)
    bad = (1315, 4165, 100.0, 100.0)
    ok, msg = scene.validate_against_corners(bad, P2, P3, tol_m=1.0)
    assert ok is False
    assert "mismatch" in msg.lower() or "differ" in msg.lower()


def test_well_trajectory_time_domain_with_td():
    scene = WellSeismicScene()
    scene.set_survey_from_corners(P1, P2, P3, n_samples=901, dt_ms=2.0)
    scene.set_vertical_domain(VerticalDomain.TIME)

    td = TimeDepthTable(
        well_name="A1",
        time_ms=np.array([0.0, 1000.0], dtype=np.float64),
        md_m=np.array([0.0, 2000.0], dtype=np.float64),
    )
    well = WellHead(
        name="A1",
        x=5288.67,
        y=8219.94,
        bottom_x=5288.67,
        bottom_y=8219.94,
        total_depth_m=2000.0,
        kb_m=0.0,
        id=JointWellId("source:a1"),
    )
    scene.set_wells([well], td_tables={"A1": td})

    traj = next(iter(scene.well_trajectories().values()))
    assert traj.has_td is True
    assert traj.warning is None
    assert traj.points.shape[1] == 3
    assert traj.points[-1, 2] == pytest.approx(1000.0, abs=1.0)
    assert traj.points[0, 0] == pytest.approx(5288.67)
    assert traj.points[-1, 0] == pytest.approx(5288.67)


def test_well_trajectory_missing_td_safe_behaviour():
    scene = WellSeismicScene()
    scene.set_survey_from_corners(P1, P2, P3, n_samples=100, dt_ms=2.0)
    scene.set_vertical_domain(VerticalDomain.TIME)
    well = WellHead(
        name="A2",
        x=1000.0,
        y=2000.0,
        bottom_x=1000.0,
        bottom_y=2000.0,
        total_depth_m=2100.0,
        id=JointWellId("source:a2"),
    )
    scene.set_wells([well], td_tables={})

    traj = next(iter(scene.well_trajectories().values()))
    assert traj.has_td is False
    assert traj.warning is not None
    assert len(traj.points) == 1
    assert traj.points[0, 0] == pytest.approx(1000.0)
    assert traj.points[0, 1] == pytest.approx(2000.0)


def test_scene_keeps_source_ids_stable_when_duplicate_wells_are_renamed_or_reordered():
    scene = WellSeismicScene()
    scene.set_wells([
        WellHead("A1", 0, 0, 0, 0, 100, id=JointWellId("source:7")),
        WellHead("A1", 10, 10, 10, 10, 100, id=JointWellId("source:8")),
    ])
    source_7, source_8 = [
        presentation.id for presentation in scene.well_presentations()
    ]
    scene.set_well_visibility(source_8, False)

    scene.set_wells([
        WellHead(
            "RENAMED", 99, 99, 99, 99, 999, id=JointWellId("source:8")
        ),
        WellHead("A1", 0, 0, 0, 0, 100, id=JointWellId("source:7")),
    ])

    assert [
        (well.id, well.name, well.visible)
        for well in scene.well_presentations()
    ] == [
        (source_8, "RENAMED", False),
        (source_7, "A1", True),
    ]


def test_scene_rejects_invalid_source_ids_without_replacing_current_wells():
    scene = WellSeismicScene()
    original = WellHead(
        "A1", 0, 0, 0, 0, 100, id=JointWellId("source:a1")
    )
    scene.set_wells([original])

    with pytest.raises(ValueError, match="stable source JointWellId"):
        scene.set_wells([WellHead("MISSING", 1, 1, 1, 1, 100)])
    with pytest.raises(ValueError, match="must be unique"):
        scene.set_wells(
            [
                original,
                WellHead(
                    "DUP",
                    2,
                    2,
                    2,
                    2,
                    100,
                    id=JointWellId("source:a1"),
                ),
            ]
        )

    assert [
        (well.id, well.name) for well in scene.well_presentations()
    ] == [(JointWellId("source:a1"), "A1")]


def test_scene_visibility_filters_3d_trajectories_without_deleting_analysis():
    scene = WellSeismicScene()
    scene.set_wells(
        [
            WellHead("A1", 0, 0, 0, 0, 100, id=JointWellId("source:a1")),
            WellHead("B1", 10, 10, 10, 10, 100, id=JointWellId("source:b1")),
        ]
    )
    fence = scene.add_well_to_well_fence(["A1", "B1"])

    scene.set_well_visibility(JointWellId("source:a1"), False)

    assert (
        set(scene.well_trajectories(visible_only=True)),
        set(scene.well_trajectories()),
        [saved.id for saved in scene.fences],
    ) == (
        {JointWellId("source:b1")},
        {JointWellId("source:a1"), JointWellId("source:b1")},
        [fence.id],
    )


def test_scene_reload_preserves_known_visibility_and_shows_new_wells():
    scene = WellSeismicScene()
    a1 = WellHead(
        "A1", 0, 0, 0, 0, 100, id=JointWellId("source:a1")
    )
    b1 = WellHead(
        "B1", 10, 10, 10, 10, 100, id=JointWellId("source:b1")
    )
    scene.set_wells([a1, b1])
    scene.set_well_visibility(JointWellId("source:a1"), False)

    scene.set_wells([
        a1,
        b1,
        WellHead(
            "C1", 20, 20, 20, 20, 100, id=JointWellId("source:c1")
        ),
    ])

    assert [
        (well.id, well.visible)
        for well in scene.well_presentations()
    ] == [
        (JointWellId("source:a1"), False),
        (JointWellId("source:b1"), True),
        (JointWellId("source:c1"), True),
    ]


def test_scene_exposes_gr_tracks_and_one_shared_robust_range():
    scene = WellSeismicScene()
    wells = [
        WellHead(
            "A1", 0, 0, 0, 0, 100, id=JointWellId("source:a1")
        ),
        WellHead(
            "B1", 10, 10, 10, 10, 100, id=JointWellId("source:b1")
        ),
    ]
    td_tables = {
        name: TimeDepthTable(
            well_name=name,
            time_ms=np.array([0.0, 1000.0]),
            md_m=np.array([0.0, 100.0]),
        )
        for name in ("A1", "B1")
    }
    scene.set_wells(wells, td_tables=td_tables)
    scene.set_well_curves(
        {
            "A1": {
                "GR": (
                    np.array([0.0, 50.0, 100.0]),
                    np.array([0.0, np.nan, 20.0]),
                )
            },
            "B1": {
                "GR": (
                    np.array([0.0, 50.0, 100.0]),
                    np.array([30.0, 40.0, 50.0]),
                )
            },
        }
    )

    tracks = scene.gr_well_trajectories()

    assert scene.gr_value_range() == pytest.approx((1.6, 49.2))
    assert tracks[JointWellId("source:a1")].points[:, 2].tolist() == [
        0.0,
        500.0,
        1000.0,
    ]
    assert tracks[JointWellId("source:a1")].gr_values[0] == 0.0
    assert np.isnan(tracks[JointWellId("source:a1")].gr_values[1])
    assert tracks[JointWellId("source:a1")].gr_values[2] == 20.0


def test_deviated_well_head_to_bottom_xy():
    scene = WellSeismicScene()
    scene.set_survey_from_corners(P1, P2, P3, n_samples=100, dt_ms=2.0)
    scene.set_vertical_domain(VerticalDomain.TIME)
    td = TimeDepthTable(
        well_name="A10",
        time_ms=np.array([0.0, 500.0, 1000.0], dtype=np.float64),
        md_m=np.array([0.0, 1000.0, 2000.0], dtype=np.float64),
    )
    well = WellHead(
        name="A10",
        x=10547.09,
        y=11754.19,
        bottom_x=10457.533,
        bottom_y=11189.500,
        total_depth_m=2000.0,
        id=JointWellId("source:a10"),
    )
    scene.set_wells([well], td_tables={"A10": td})
    pts = next(iter(scene.well_trajectories().values())).points
    assert pts[0, 0] == pytest.approx(10547.09)
    assert pts[0, 1] == pytest.approx(11754.19)
    assert pts[-1, 0] == pytest.approx(10457.533)
    assert pts[-1, 1] == pytest.approx(11189.500)


def test_volume_access_injectable_slice():
    vol = np.arange(2 * 3 * 4, dtype=np.float32).reshape(2, 3, 4)
    access = InMemoryVolumeAccess(vol)
    scene = WellSeismicScene()
    scene.set_volume_access(access)
    sl = scene.slice_inline(0)
    assert sl.shape == (3, 4)
    assert sl[0, 0] == pytest.approx(0.0)
    sl_xl = scene.slice_crossline(1)
    assert sl_xl.shape == (2, 4)
    sl_t = scene.slice_time(2)
    assert sl_t.shape == (2, 3)


def test_scene_default_vertical_domain_is_time():
    scene = WellSeismicScene()
    assert scene.vertical_domain is VerticalDomain.TIME


def test_scene_defaults_to_centered_orthogonal_slices_and_snaps_time_stack():
    scene = _scene_with_preview()

    assert scene.orthogonal_slice_state == OrthogonalSliceState(
        inline_index=2,
        crossline_index=3,
        time_slices=(TimeSliceState(time_ms=100.0),),
        active_time_ms=100.0,
        time_opacity=0.8,
    )

    assert scene.add_time_slice(147.0) == pytest.approx(140.0)
    assert scene.add_time_slice(141.0) == pytest.approx(140.0)
    state = scene.orthogonal_slice_state
    assert [item.time_ms for item in state.time_slices] == [100.0, 140.0]
    assert state.active_time_ms == 140.0


def test_scene_time_slice_stack_enforces_limit_minimum_and_sorted_uniqueness():
    scene = _scene_with_preview()
    for time_ms in (0, 20, 40, 60, 80, 120, 140):
        scene.add_time_slice(time_ms)

    assert len(scene.orthogonal_slice_state.time_slices) == 8
    with pytest.raises(ValueError, match="8"):
        scene.add_time_slice(160)

    for time_ms in (0, 20, 40, 60, 80, 100, 120):
        assert scene.remove_time_slice(time_ms) is True
    assert scene.remove_time_slice(140) is False
    assert len(scene.orthogonal_slice_state.time_slices) == 1


def test_scene_restores_only_time_slices_valid_for_replacement_volume():
    scene = WellSeismicScene()
    scene.restore_orthogonal_slice_state(
        OrthogonalSliceState(
            inline_index=99,
            crossline_index=-5,
            time_slices=(
                TimeSliceState(-20.0),
                TimeSliceState(40.0, visible=False),
                TimeSliceState(400.0),
            ),
            active_time_ms=400.0,
            time_opacity=0.65,
        )
    )
    scene.set_survey_from_corners(
        P1,
        P2,
        P3,
        n_samples=101,
        dt_ms=2.0,
        t0_ms=0.0,
    )
    scene.set_volume_access(
        InMemoryVolumeAccess(np.zeros((5, 7, 11), dtype=np.float32))
    )

    assert scene.orthogonal_slice_state == OrthogonalSliceState(
        inline_index=4,
        crossline_index=0,
        time_slices=(TimeSliceState(40.0, visible=False),),
        active_time_ms=40.0,
        time_opacity=0.65,
    )
    assert "越界" in scene.slice_state_warning


def test_joint_widget_legacy_slice_api_moves_only_active_time_slice():
    from geoviz_well_seismic_3d.joint_widget import WellSeismicJointWidget

    scene = _scene_with_preview()
    scene.add_time_slice(40.0)
    renderer = MagicMock()
    widget = WellSeismicJointWidget.__new__(WellSeismicJointWidget)
    widget._scene = scene
    widget._renderer = renderer

    WellSeismicJointWidget.set_slice_indices(widget, 1, 2, 8)

    state = scene.orthogonal_slice_state
    assert (state.inline_index, state.crossline_index) == (1, 2)
    assert [item.time_ms for item in state.time_slices] == [100.0, 160.0]
    assert state.active_time_ms == 160.0
    renderer.set_orthogonal_slices.assert_called_once()


def test_package_importable_and_joint_widget_facades_renderer(qtbot):
    """Joint widget composes Renderer3D rather than a second slice pipeline."""
    from geoviz_well_seismic_3d import WellSeismicJointWidget

    scene = WellSeismicScene()
    scene.set_survey_from_corners(P1, P2, P3, n_samples=16, dt_ms=2.0)
    vol = np.random.randn(8, 8, 16).astype(np.float32)
    scene.set_volume_access(InMemoryVolumeAccess(vol))
    scene.add_time_slice(4.0)
    td = TimeDepthTable(
        well_name="W1",
        time_ms=np.array([0.0, 30.0], dtype=np.float64),
        md_m=np.array([0.0, 100.0], dtype=np.float64),
    )
    scene.set_wells(
        [
            WellHead(
                name="W1",
                x=1000.0,
                y=2000.0,
                bottom_x=1000.0,
                bottom_y=2000.0,
                total_depth_m=100.0,
                id=JointWellId("source:w1"),
            )
        ],
        td_tables={"W1": td},
    )

    w = WellSeismicJointWidget()
    qtbot.addWidget(w)
    if w.renderer is not None:
        w.renderer.set_render_mode("volume")
    w.set_scene(scene)
    assert w.scene is scene
    # Facade: when Renderer3D is available, it is the slice backend
    if w.renderer is not None:
        from geoviz_seismic.renderer_3d import Renderer3D

        assert isinstance(w.renderer, Renderer3D)
        render_state = scene.orthogonal_slice_render_state()
        assert render_state is not None
        assert w.renderer.get_time_slices() == render_state[2]
        assert w.renderer._mode == "planes"
        assert w.renderer._slice_controls.isHidden()


def test_joint_widget_exposes_gr_colored_3d_overlay_specs(qtbot):
    from geoviz import select_depth_transform
    from geoviz_well_seismic_3d import (
        JointDisplaySettings,
        WellSeismicJointWidget,
    )

    scene = WellSeismicScene()
    # Depth requires an explicit transform (fail-closed); the test opts into
    # the constant-V0 approximation the way a synthetic demo would.
    scene.set_depth_transform(select_depth_transform(constant_v0=True))
    scene.set_vertical_domain(VerticalDomain.DEPTH)
    scene.set_wells(
        [
            WellHead(
                "A1",
                0,
                0,
                10,
                10,
                100,
                id=JointWellId("source:a1"),
            )
        ],
        td_tables={
            "source:a1": TimeDepthTable(
                well_name="A1",
                time_ms=np.array([0.0, 50.0, 100.0]),
                md_m=np.array([0.0, 50.0, 100.0]),
            )
        },
    )
    scene.set_well_curves(
        {
            "A1": {
                "GR": (
                    np.array([0.0, 50.0, 100.0]),
                    np.array([0.0, 50.0, 100.0]),
                )
            }
        }
    )
    scene.set_display_settings(
        JointDisplaySettings(well_width_px=7)
    )
    widget = WellSeismicJointWidget()
    qtbot.addWidget(widget)
    widget.set_scene(scene)

    spec = widget.well_overlay_specs()[JointWellId("source:a1")]

    assert spec.width_px == 7
    assert spec.positions.shape == (4, 3)
    assert tuple(spec.colors[0, :3]) == pytest.approx(
        (68 / 255, 1 / 255, 84 / 255)
    )
    assert tuple(spec.colors[-1, :3]) == pytest.approx(
        (253 / 255, 231 / 255, 37 / 255)
    )
    assert widget.gr_legend_title == "GR (API)"
