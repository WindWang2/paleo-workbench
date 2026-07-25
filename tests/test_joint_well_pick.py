"""Joint 3D well pick controller + hit-test (#123)."""

from __future__ import annotations

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
