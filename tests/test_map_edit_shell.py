from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.mapping_page import MappingPage


def test_mapping_page_gis_shell_assembly(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)

    assert page.objectName() == "MappingPage"
    assert isinstance(page.toolbar, MapEditToolbar)
    assert isinstance(page.layer_tree, MapLayerTree)
    assert isinstance(page.edit_view, MapEditView)
    assert isinstance(page.attribute_table, MapAttributeTable)
    assert page.attribute_table.maximumHeight() == 220
    assert page.edit_view.scene() is not None


def test_toolbar_has_core_actions(qtbot):
    bar = MapEditToolbar()
    qtbot.addWidget(bar)

    assert bar.select_btn is not None
    assert bar.move_btn is not None
    assert bar.vertex_btn is not None
    assert bar.line_btn is not None
    assert bar.label_btn is not None
    assert bar.save_draft_btn is not None
    assert bar.snap_btn is not None
    assert bar.undo_btn is not None
    assert bar.redo_btn is not None
    assert bar.preview_btn is not None
