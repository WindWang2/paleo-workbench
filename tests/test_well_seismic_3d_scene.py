"""WellSeismicScene survey + Time-domain well projection (#58)."""

from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from geoviz_well_seismic_3d import (  # noqa: E402
    InMemoryVolumeAccess,
    JointWellId,
    TimeDepthTable,
    VerticalDomain,
    WellHead,
    WellSeismicScene,
    survey_from_corners,
)

# Local rectangular corners matching data/层位 + SEGY text header style
P1 = (1315, 4165, 0.0, 0.0)
P2 = (1315, 4805, 12793.0, 0.0)
P3 = (1725, 4805, 12793.0, 16406.0)


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


def test_package_importable_and_joint_widget_facades_renderer(qtbot):
    """Joint widget composes Renderer3D rather than a second slice pipeline."""
    from geoviz_well_seismic_3d import WellSeismicJointWidget

    scene = WellSeismicScene()
    scene.set_survey_from_corners(P1, P2, P3, n_samples=16, dt_ms=2.0)
    vol = np.random.randn(8, 8, 16).astype(np.float32)
    scene.set_volume_access(InMemoryVolumeAccess(vol))
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
    w.set_scene(scene)
    assert w.scene is scene
    # Facade: when Renderer3D is available, it is the slice backend
    if w.renderer is not None:
        from geoviz_seismic.renderer_3d import Renderer3D

        assert isinstance(w.renderer, Renderer3D)
