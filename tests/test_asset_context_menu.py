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


def test_menu_export_shows_inventory_even_without_converters(qtbot):
    """Resource items always get at least '工程清单' under 导出."""
    menu = AssetContextMenu()
    menu.build(_res(fmt="unknown"), viz_supported=False)
    export_action = next(a for a in menu.actions() if a.text() == "导出")
    sub_labels = [a.text() for a in export_action.menu().actions()]
    assert any("清单" in t for t in sub_labels)


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
