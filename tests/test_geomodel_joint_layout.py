"""GeologicalModeling3DPage joint chrome layout (#87)."""

from __future__ import annotations


def test_geomodel_page_has_joint_host_regions(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    assert page.findChild(type(page), "Joint3DHost") is not None or hasattr(page, "joint_3d_host")
    assert page.joint_3d_host.objectName() == "Joint3DHost"
    assert page.joint_2d_host.objectName() == "Joint2DHost"
    assert page._joint_3d_panel is not None
    assert page._joint_2d_panel is not None
    assert page._main_splitter.count() == 4


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


def test_geomodel_joint_panels_collapse(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)

    assert page.joint_3d_host.isVisible()
    page.btn_toggle_joint_3d.click()
    assert page.btn_toggle_joint_3d.isChecked()
    assert not page.joint_3d_host.isVisible()
    page.btn_toggle_joint_3d.click()
    assert page.joint_3d_host.isVisible()

    page.btn_toggle_joint_2d.click()
    assert not page.joint_2d_host.isVisible()
    page.btn_toggle_joint_2d.click()
    assert page.joint_2d_host.isVisible()
