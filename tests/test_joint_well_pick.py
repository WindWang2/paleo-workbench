"""Joint 3D well pick controller + hit-test (#123)."""

from __future__ import annotations

import pytest

from paleo_workbench.viz.joint_well_pick import (
    WellPickController,
    WellScreenGeom,
    pick_well_name,
)


def test_pick_controller_two_click_pair():
    c = WellPickController()
    s, pair = c.on_well_click("A1")
    assert pair is None
    assert c.half_select == "A1"
    assert "A1" in s and "Esc" in s
    s, pair = c.on_well_click("A11")
    assert pair == ("A1", "A11")
    assert c.half_select is None
    assert "A1" in s and "A11" in s


def test_pick_controller_same_well_rejected():
    c = WellPickController()
    c.on_well_click("A1")
    s, pair = c.on_well_click("A1")
    assert pair is None
    assert c.half_select == "A1"
    assert "同一口" in s


def test_pick_controller_esc_and_blank_clear_half():
    c = WellPickController()
    c.on_well_click("A1")
    assert c.on_escape()
    assert c.half_select is None
    c.on_well_click("B3")
    assert c.on_blank_click()
    assert c.half_select is None


def test_pick_controller_empty_name():
    c = WellPickController()
    s, pair = c.on_well_click("  ")
    assert pair is None
    assert "未命中" in s


def test_hit_test_head_preferred_over_trajectory():
    # B's trajectory passes through click, but A's head is closer within radius
    wells = [
        WellScreenGeom("A", head=(100.0, 100.0), traj=((100.0, 100.0), (100.0, 200.0))),
        WellScreenGeom("B", head=(300.0, 300.0), traj=((50.0, 100.0), (150.0, 100.0))),
    ]
    # Click on B traj line center — should hit B via traj if no head nearby
    assert pick_well_name(100.0, 100.0, wells) == "A"  # head A
    assert pick_well_name(100.0, 100.0, wells, head_radius_px=5.0) == "A"
    # Far from heads, on B's traj
    assert pick_well_name(100.0, 100.0, wells, head_radius_px=1.0)  # still A head at exact
    # Mid B trajectory, heads far
    name = pick_well_name(100.0, 100.0, [
        WellScreenGeom("A", head=(500.0, 500.0), traj=()),
        WellScreenGeom("B", head=(400.0, 400.0), traj=((50.0, 100.0), (150.0, 100.0))),
    ], head_radius_px=10.0, traj_radius_px=12.0)
    assert name == "B"


def test_hit_test_miss_returns_none():
    wells = [WellScreenGeom("A", head=(10.0, 10.0), traj=((10.0, 10.0), (10.0, 20.0)))]
    assert pick_well_name(200.0, 200.0, wells) is None


def test_hit_test_head_beats_nearby_other_traj():
    """Head priority: even if another well's traj is slightly closer overall."""
    wells = [
        WellScreenGeom("HEAD", head=(100.0, 100.0), traj=((100.0, 100.0), (100.0, 180.0))),
        WellScreenGeom("TRAJ", head=(0.0, 0.0), traj=((95.0, 100.0), (105.0, 100.0))),
    ]
    # Click near HEAD head; TRAJ traj also near — head wins
    assert pick_well_name(102.0, 100.0, wells, head_radius_px=16.0, traj_radius_px=16.0) == "HEAD"


def test_page_pick_routes_to_host(qtbot, tmp_path, monkeypatch):
    """Controller pair completion calls host.add_well_to_well_fence (#123)."""
    from paleo_workbench.viz import joint_host as host_mod
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    assert hasattr(page, "_well_pick")
    calls: list[tuple[str, str]] = []
    page._joint_host.add_well_to_well_fence = lambda a, b, **kw: calls.append((a, b))  # type: ignore
    page._handle_joint_well_pick("W1")
    assert page._well_pick.half_select == "W1"
    page._handle_joint_well_pick("W2")
    assert calls == [("W1", "W2")]
    assert page._well_pick.half_select is None


def test_page_esc_clears_half(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.viz import joint_host as host_mod
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page._handle_joint_well_pick("A1")
    assert page._well_pick.half_select == "A1"
    page.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert page._well_pick.half_select is None


def test_pick_controller_draw_mode_drag_snap():
    c = WellPickController()
    assert "选井" in c.set_mode("pick") or c.mode == "pick"
    c.set_mode("draw")
    assert c.mode == "draw"
    assert c.half_select is None
    s = c.on_draw_press("A1")
    assert c.draw_from == "A1"
    assert "A1" in s
    s, pair = c.on_draw_release("A11")
    assert pair == ("A1", "A11")
    assert c.draw_from is None


def test_pick_controller_draw_same_well_and_miss():
    c = WellPickController()
    c.set_mode("draw")
    c.on_draw_press("A1")
    s, pair = c.on_draw_release("A1")
    assert pair is None
    assert "同一口" in s
    c.on_draw_press("A1")
    s, pair = c.on_draw_release(None)
    assert pair is None
    assert "未吸附" in s


def test_pick_mode_blocks_draw_click_path():
    c = WellPickController()
    c.set_mode("draw")
    s, pair = c.on_well_click("A1")
    assert pair is None
    assert "画线" in s


def test_hit_test_head_only_skips_traj():
    wells = [
        WellScreenGeom("A", head=(500.0, 500.0), traj=()),
        WellScreenGeom("B", head=(400.0, 400.0), traj=((50.0, 100.0), (150.0, 100.0))),
    ]
    assert pick_well_name(100.0, 100.0, wells, head_only=True, head_radius_px=16.0) is None
    assert pick_well_name(100.0, 100.0, wells, head_only=False, traj_radius_px=12.0) == "B"


def test_page_mode_switch_and_delete_active(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.viz import joint_host as host_mod
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    assert hasattr(page, "_joint_pick_mode")
    assert page._joint_pick_mode.currentData() == "pick"
    assert hasattr(page, "_joint_del_fence_btn")
    page._joint_pick_mode.setCurrentIndex(1)  # draw
    assert page._well_pick.mode == "draw"
    page._joint_pick_mode.setCurrentIndex(0)
    assert page._well_pick.mode == "pick"
    removed: list[bool] = []
    page._joint_host.remove_active_fence = lambda: removed.append(True)  # type: ignore
    page._on_joint_delete_active_fence()
    assert removed == [True]


def test_host_remove_active_fence(tmp_path, monkeypatch):
    from paleo_workbench.viz import joint_host as host_mod
    from paleo_workbench.viz.joint_host import WellSeismicJointHost

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    host = WellSeismicJointHost()
    if host.scene is None:
        pytest.skip(f"geoviz unavailable: {getattr(host, 'engine_error', None)}")
    from geoviz_well_seismic_3d import FenceSection, JointWellId, WellHead
    import numpy as np

    scene = host.scene
    scene.set_wells(
        [
            WellHead(
                "A1", 0, 0, 0, 0, 0, id=JointWellId("source:a1")
            ),
            WellHead(
                "A2",
                100,
                100,
                100,
                100,
                0,
                id=JointWellId("source:a2"),
            ),
        ]
    )
    scene.add_well_to_well_fence(["A1", "A2"], name="f1")
    scene.add_fence(
        FenceSection("f2", np.array([[0.0, 0.0], [50.0, 0.0]], dtype=float)),
        activate=True,
    )
    assert len(scene.fences) == 2
    host.remove_active_fence()
    assert len(scene.fences) == 1
    host.remove_active_fence()
    assert len(scene.fences) == 0
    host.remove_active_fence()  # no-op
