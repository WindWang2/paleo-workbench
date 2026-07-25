"""GeologicalModeling3DPage joint chrome — well–seismic workbench (#121 / PRD #120)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem


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
