"""GeologicalModeling3DPage joint chrome layout — G1 unified viewport (#106 / #107–#110)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidgetItem


def test_geomodel_page_g1_chrome_three_columns(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    assert page.joint_3d_host.objectName() == "Joint3DHost"
    assert page.joint_2d_host.objectName() == "Joint2DHost"
    assert page._main_splitter.count() == 3
    # No independent joint-3D side panel column
    assert getattr(page, "_joint_3d_panel", None) is None
    assert not hasattr(page, "btn_toggle_joint_3d") or page.findChild(type(page), "Joint3DPanel") is None
    # Primary path is joint host, not modeling GL in center splitter top
    assert page.joint_3d_host.parent() is not None
    # gl_widget may exist for off-path modeling helpers but must not be the main viewport
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


def test_geomodel_tree_has_geoviz_joint_group(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    labels = []
    root = page.model_tree.invisibleRootItem()
    for i in range(root.childCount()):
        labels.append(root.child(i).text(0))
    assert any("井震联合 (geoviz)" in t for t in labels)
    assert any("井震标定与综合 (geomodel)" in t for t in labels)
    assert page._joint_host is not None


def test_geomodel_tree_only_geoviz_checkable(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    root = page.model_tree.invisibleRootItem()
    for i in range(root.childCount()):
        group = root.child(i)
        title = group.text(0)
        if "井震联合 (geoviz)" in title:
            for j in range(group.childCount()):
                child = group.child(j)
                assert child.flags() & Qt.ItemIsUserCheckable
                assert child.flags() & Qt.ItemIsEnabled
        else:
            for j in range(group.childCount()):
                child = group.child(j)
                assert not (child.flags() & Qt.ItemIsEnabled), child.text(0)


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
    # G1: no align / grid coord toggle on chrome
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
        # Controls may exist but must not be shown in the right rail path
        assert not page.chk_clip_x.isVisibleTo(page)
