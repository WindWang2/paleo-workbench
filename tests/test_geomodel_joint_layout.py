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
