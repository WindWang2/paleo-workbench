"""GeologicalModeling3DPage joint chrome — well–seismic workbench (#121 / PRD #120)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt


def test_geomodel_page_chrome_two_columns(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    assert page.joint_3d_host.objectName() == "Joint3DHost"
    assert page.joint_2d_host.objectName() == "Joint2DHost"
    assert page._main_splitter.count() == 2
    # Right rail retained off-layout for legacy helpers; not a splitter child
    right = getattr(page, "_right_rail", None)
    assert right is not None
    assert page._main_splitter.indexOf(right) == -1
    assert not right.isVisibleTo(page)
    assert getattr(page, "_joint_3d_panel", None) is None
    assert page.joint_3d_host.parent() is not None
    if hasattr(page, "gl_widget") and page.gl_widget is not None:
        assert page.gl_widget.parent() is page or not page.gl_widget.isVisible()


def test_geomodel_page_has_joint_host_regions(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    assert page.findChild(type(page), "Joint3DHost") is not None or hasattr(page, "joint_3d_host")
    assert page.joint_3d_host.objectName() == "Joint3DHost"
    assert page.joint_2d_host.objectName() == "Joint2DHost"
    assert page._joint_2d_panel is not None


def test_geomodel_tree_only_geoviz_group(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    root = page.model_tree.invisibleRootItem()
    assert root.childCount() == 1
    group = root.child(0)
    assert "井震联合 (geoviz)" in group.text(0)
    labels = [group.child(j).text(0) for j in range(group.childCount())]
    assert any("地震预览体" in t for t in labels)
    assert any("fence" in t for t in labels)
    assert page._joint_host is not None
    # No geomodel / structure placeholder groups
    all_top = [root.child(i).text(0) for i in range(root.childCount())]
    assert not any("geomodel" in t for t in all_top)
    assert not any("地层构造" in t for t in all_top)


def test_geomodel_tree_geoviz_layers_checkable(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    root = page.model_tree.invisibleRootItem()
    group = root.child(0)
    for j in range(group.childCount()):
        child = group.child(j)
        assert child.flags() & Qt.ItemIsUserCheckable
        assert child.flags() & Qt.ItemIsEnabled


def test_geomodel_tree_lists_each_joint_well_as_an_independent_checkbox(qtbot):
    from geoviz_well_seismic_3d import JointWellId, WellHead
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page._joint_host.scene.set_wells(
        [
            WellHead("A1", 0, 0, 0, 0, 100, id=JointWellId("source:1")),
            WellHead("A1", 10, 10, 10, 10, 100, id=JointWellId("source:2")),
            WellHead("B1", 20, 20, 20, 20, 100, id=JointWellId("source:3")),
        ]
    )

    page._joint_host.scene_updated.emit()

    group = page.model_tree.invisibleRootItem().child(0)
    wells = next(
        group.child(index)
        for index in range(group.childCount())
        if group.child(index).text(0) == "联合井轨迹 (geoviz)"
    )
    assert [
        (wells.child(index).text(0), wells.child(index).checkState(0))
        for index in range(wells.childCount())
    ] == [
        ("A1 (1)", Qt.Checked),
        ("A1 (2)", Qt.Checked),
        ("B1", Qt.Checked),
    ]


def test_geomodel_tree_hides_one_well_updates_parent_and_clears_selection(qtbot):
    from geoviz_well_seismic_3d import JointWellId, WellHead
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page._joint_host.scene.set_wells(
        [
            WellHead("A1", 0, 0, 0, 0, 100, id=JointWellId("source:a1")),
            WellHead("B1", 10, 10, 10, 10, 100, id=JointWellId("source:b1")),
        ]
    )
    page._joint_host.scene_updated.emit()
    page._well_pick.on_well_click("source:a1")
    wells = page._joint_wells_tree_item

    wells.child(0).setCheckState(0, Qt.Unchecked)

    assert (
        [(well.id, well.visible) for well in page._joint_host.scene.well_presentations()],
        wells.checkState(0),
        page._well_pick.half_select,
    ) == (
        [("source:a1", False), ("source:b1", True)],
        Qt.PartiallyChecked,
        None,
    )


def test_geomodel_well_parent_checkbox_controls_all_wells(qtbot):
    from geoviz_well_seismic_3d import JointWellId, WellHead
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page._joint_host.scene.set_wells(
        [
            WellHead("A1", 0, 0, 0, 0, 100, id=JointWellId("source:a1")),
            WellHead("B1", 10, 10, 10, 10, 100, id=JointWellId("source:b1")),
        ]
    )
    page._joint_host.scene_updated.emit()

    page._joint_wells_tree_item.setCheckState(0, Qt.Unchecked)
    hidden = [
        well.visible for well in page._joint_host.scene.well_presentations()
    ]
    page._joint_wells_tree_item.setCheckState(0, Qt.Checked)

    assert (
        hidden,
        [well.visible for well in page._joint_host.scene.well_presentations()],
    ) == ([False, False], [True, True])


def test_geomodel_toolbar_displays_duplicate_labels_but_keeps_joint_well_ids(qtbot):
    from geoviz_well_seismic_3d import JointWellId, WellHead
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page._joint_host.scene.set_wells(
        [
            WellHead("A1", 0, 0, 0, 0, 100, id=JointWellId("source:1")),
            WellHead("A1", 10, 10, 10, 10, 100, id=JointWellId("source:2")),
        ]
    )

    page._joint_host.scene_updated.emit()

    assert [
        (page._joint_well_a.itemText(index), page._joint_well_a.itemData(index))
        for index in range(page._joint_well_a.count())
    ] == [("A1 (1)", "source:1"), ("A1 (2)", "source:2")]


def test_geomodel_tree_checks_ignore_unknown_keys(qtbot):
    """Unknown tree_checks keys from older projects are ignored safely (#114 C1 / #121)."""
    from paleo_workbench.project.models import JointAnalysisState, ProjectDocument
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    project = ProjectDocument.new("demo")
    project.joint_analysis = JointAnalysisState(
        tree_checks={
            "地震预览体 (geoviz)": False,
            "REMOVED_LAYER_THAT_NO_LONGER_EXISTS": True,
            "地层构造格架": False,
        }
    )
    page.set_project(project)
    page._apply_joint_tree_checks_from_project()
    # Known key applied
    assert page._tree_item_checked("地震预览体 (geoviz)") is False
    # Unknown keys did not raise; other known layers stay default checked
    assert page._tree_item_checked("联合井轨迹 (geoviz)") is True


def test_geomodel_joint_auto_reload_empty(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.viz import joint_host as host_mod
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page._joint_loaded_once = True
    page._ensure_joint_widget()
    page._joint_host.reload()
    assert "空状态" in page._joint_status.text() or "未找到" in page._joint_status.text()


def test_geomodel_joint_toolbar_domain_and_fence_api(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.viz import joint_host as host_mod
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    monkeypatch.setattr(host_mod, "_repo_root", lambda: tmp_path)
    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    assert hasattr(page, "_joint_domain")
    assert hasattr(page, "_joint_fence_btn")
    assert hasattr(page, "_joint_add_btn")
    assert hasattr(page, "btn_orbit")
    assert hasattr(page, "btn_pan")
    assert hasattr(page, "btn_reset")
    assert not hasattr(page, "_joint_align_btn") or page._joint_align_btn is None
    assert not hasattr(page, "btn_coord") or page.btn_coord is None or not page.btn_coord.isVisibleTo(page)
    page._on_joint_domain_changed("Depth")
    page._on_joint_fence()
    assert page._joint_status.text()


def test_geomodel_joint_2d_collapse(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)

    assert page.joint_2d_host.isVisible()
    page.btn_toggle_joint_2d.click()
    assert not page.joint_2d_host.isVisible()
    page.btn_toggle_joint_2d.click()
    assert page.joint_2d_host.isVisible()


def test_geomodel_clip_card_hidden(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    card = getattr(page, "_card_clip", None)
    if card is not None:
        assert not card.isVisibleTo(page)
    else:
        assert not page.chk_clip_x.isVisibleTo(page)


def test_nav_label_is_joint_workbench():
    from paleo_workbench import tokens

    assert tokens.PAGE_NAMES[10] == "井震联合"
    assert "井震" in tokens.PAGE_DESCRIPTIONS[10]


def test_joint_2d_time_only_chip_and_empty_hint(qtbot):
    """Unified domain chip: 2D/3D share one domain; empty hint guides fences."""
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    assert hasattr(page, "_joint_2d_time_chip")
    assert "Time" in page._joint_2d_time_chip.text()
    assert "联动" in page._joint_2d_time_chip.text()
    # Before profile mount: empty-state guidance on placeholder
    ph = getattr(page, "_joint_2d_placeholder", None)
    if ph is not None:
        assert "fence" in ph.text().lower() or "井" in ph.text()
    # Without a time-depth transform, Depth is refused and the chip keeps
    # reporting the actual (Time) domain — no fake Depth display.
    page._on_joint_domain_changed("Depth")
    scene = page._joint_host.scene
    if scene is not None and not scene.depth_available:
        assert "Time" in page._joint_2d_time_chip.text()
    page._on_joint_domain_changed("Time")
    assert page._joint_2d_time_chip.text() == "域: Time · 2D/3D 联动"


def test_profile_follows_scene_extract_domain(qtbot):
    """FenceProfile2D follows the scene domain (old #122 Time-force removed)."""
    from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

    ensure_geoviz_on_path()
    from geoviz_well_seismic_3d import (
        FenceSection,
        InMemoryVolumeAccess,
        JointWellId,
        VerticalDomain,
        WellHead,
        WellSeismicScene,
        select_depth_transform,
    )
    from geoviz_well_seismic_3d.profile_2d import FenceProfile2D
    import numpy as np

    scene = WellSeismicScene()
    p1, p2, p3 = (1315, 4165, 0.0, 0.0), (1315, 4805, 12793.0, 0.0), (1725, 4805, 12793.0, 16406.0)
    scene.set_survey_from_corners(p1, p2, p3, n_samples=16, dt_ms=2.0)
    scene.set_volume_access(InMemoryVolumeAccess(np.random.randn(8, 8, 16).astype(np.float32)))
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
    scene.add_fence(
        FenceSection("F", np.array([[0.0, 0.0], [5000.0, 5000.0]], dtype=np.float64))
    )
    scene.set_depth_transform(select_depth_transform(constant_v0=True, v0_m_s=3000.0))
    scene.set_vertical_domain(VerticalDomain.DEPTH)

    profile = FenceProfile2D()
    qtbot.addWidget(profile)
    # The workbench page policy clears any override: profile follows scene.
    page_policy_clear = getattr(profile, "set_extract_domain", None)
    if callable(page_policy_clear):
        page_policy_clear(None)
    profile.set_scene(scene)
    # Not empty: has fence + volume
    assert profile._label.pixmap() is not None and not profile._label.pixmap().isNull()
    assert scene.vertical_domain is VerticalDomain.DEPTH
    # The profile's z range matches the scene-domain (depth) extraction axis,
    # i.e. 2D and 3D describe the same physical vertical extent.
    ext = scene.extract_active_fence()
    assert ext is not None
    assert profile._z1 == pytest.approx(float(ext.sample_axis[-1]))


def test_analysis_auto_tie_crossplot_not_offered_without_wells(qtbot, monkeypatch):
    """#529: Auto-Tie / 岩性交会图 must complete via a visible path or not be offered."""
    from PySide6.QtWidgets import QMessageBox

    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    infos: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: infos.append(args)),
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page._joint_analysis_btn.setChecked(True)

    auto = page._wtie_auto_proxy
    cross = page._facies_crossplot_proxy
    offered = auto.isEnabled() or cross.isEnabled()
    if not offered:
        return

    auto.click()
    cross.click()
    joined = " ".join(str(item) for item in infos)
    assert "三维建模" not in joined
    assert page.bh_raw_data, "visible Auto-Tie/crossplot must have a load path"


def test_analysis_auto_tie_crossplot_complete_from_joint_wells(qtbot, monkeypatch):
    """#529: joint-scene wells fill bh_raw_data so visible analysis actions complete."""
    from PySide6.QtWidgets import QMessageBox

    from geoviz_well_seismic_3d import JointWellId, WellHead
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    infos: list[tuple] = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *args, **kwargs: infos.append(args)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *args, **kwargs: infos.append(args)),
    )
    dialogs: list[dict] = []

    class _FakeDialog:
        def __init__(self, result, parent=None):
            dialogs.append(result)

        def exec(self):
            return 1

    monkeypatch.setattr(
        "paleo_workbench.ui.pages.geological_modeling_3d_page.LithologyCrossplotDialog",
        _FakeDialog,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page._joint_host.scene.set_wells(
        [
            WellHead(
                "A1",
                0.0,
                0.0,
                0.0,
                0.0,
                120.0,
                id=JointWellId("source:a1"),
            )
        ]
    )
    page._joint_host.scene_updated.emit()
    page._joint_analysis_btn.setChecked(True)

    assert page.bh_raw_data
    assert page._wtie_auto_proxy.isEnabled()
    assert page._facies_crossplot_proxy.isEnabled()

    page._wtie_auto_proxy.click()
    joined = " ".join(str(item) for item in infos)
    assert "三维建模" not in joined
    assert "—" not in page.label_correlation.text()

    page._facies_crossplot_proxy.click()
    assert dialogs
    assert dialogs[0].get("points") or dialogs[0].get("clusters") is not None
