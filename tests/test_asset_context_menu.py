from paleo_workbench.project.models import ResourceItem, ExportArtifact
from paleo_workbench.ui.pages.asset_context_menu import AssetContextMenu


def _res(fmt="las", rtype="well_log"):
    return ResourceItem(name="x", path=f"/x.{fmt}", type=rtype, format=fmt, status="parsed")


def test_menu_empty_when_no_asset(qtbot):
    menu = AssetContextMenu()
    menu.build(None, viz_supported=False)
    assert menu.actions() == []


def test_menu_has_preview_always(qtbot):
    menu = AssetContextMenu()
    menu.build(_res(), viz_supported=False)
    assert any(a.text() == "预览" for a in menu.actions())


def test_menu_rescan_only_for_resource(qtbot):
    menu = AssetContextMenu()
    art = ExportArtifact(linked_id="m1", format="PDF", output_path="/m.pdf")
    menu.build(art, viz_supported=False)
    assert not any(a.text() == "重新扫描" for a in menu.actions())

    menu2 = AssetContextMenu()
    menu2.build(_res(), viz_supported=False)
    assert any(a.text() == "重新扫描" for a in menu2.actions())


def test_menu_export_hidden_when_no_converters(qtbot):
    """Spec: 导出 is hidden when no converters apply, even for a resource.

    A resource whose format has no converters must not show the 导出 menu
    (the always-available 工程清单 inventory cannot surface it on its own).
    """
    menu = AssetContextMenu()
    menu.build(_res(fmt="unknown"), viz_supported=False)
    assert not any(a.text() == "导出" for a in menu.actions())


def test_menu_export_shown_with_subitems(qtbot):
    menu = AssetContextMenu()
    menu.build(_res(fmt="las"), viz_supported=False)
    export_action = next(a for a in menu.actions() if a.text() == "导出")
    assert export_action.menu() is not None
    sub_labels = [a.text() for a in export_action.menu().actions()]
    assert "CSV" in sub_labels
    assert any("清单" in t for t in sub_labels)


def test_menu_visualize_hidden_when_unsupported(qtbot):
    menu = AssetContextMenu()
    menu.build(_res(), viz_supported=False)
    assert not any("可视化" in a.text() for a in menu.actions())


def test_menu_remove_always_present(qtbot):
    menu = AssetContextMenu()
    menu.build(_res(), viz_supported=False)
    assert any(a.text() == "移出项目" for a in menu.actions())


def _res_with_role(role: str):
    return ResourceItem(
        name="x",
        path="/x.las",
        type="well_log",
        format="las",
        status="parsed",
        artifact_role=role,
    )


def test_menu_new_version_enabled_for_derived(qtbot):
    """ctx_new_version (新建版本/工作副本) is enabled for DERIVED assets now
    that the working-copy workflow is wired."""
    menu = AssetContextMenu()
    menu.build(_res_with_role("derived"), viz_supported=False)
    act = menu.find_action("ctx_new_version")
    assert act is not None
    assert act.isEnabled() is True
    assert "工作副本" in act.toolTip()


def test_menu_promote_enabled_for_intermediate(qtbot):
    """ctx_promote (提升为正式数据) is enabled for INTERMEDIATE assets now that
    the promote workflow is wired."""
    menu = AssetContextMenu()
    menu.build(_res_with_role("intermediate"), viz_supported=False)
    act = menu.find_action("ctx_promote")
    assert act is not None
    assert act.isEnabled() is True


def test_menu_export_open_enabled_for_output(qtbot):
    """ctx_export_open (导出/交付) is enabled for OUTPUT assets now that the
    delivery workflow is wired."""
    menu = AssetContextMenu()
    menu.build(_res_with_role("export"), viz_supported=False)
    act = menu.find_action("ctx_export_open")
    assert act is not None
    assert act.isEnabled() is True


def test_menu_trashed_asset_shows_restore_not_remove(qtbot):
    """A trashed (回收站) asset gets a 还原 action instead of the destructive
    移出项目 action."""
    trashed = ResourceItem(
        name="t.las",
        path="/t.las",
        type="well_log",
        format="las",
        status="parsed",
        parsed_summary={"catalog_trashed": True},
    )
    menu = AssetContextMenu()
    menu.build(trashed, viz_supported=False)
    assert menu.find_action("ctx_restore") is not None
    assert menu.find_action("ctx_remove") is None
