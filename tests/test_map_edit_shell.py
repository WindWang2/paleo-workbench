import pytest
from PySide6.QtCore import QSettings

from paleo_workbench.ui.layout_persistence import LayoutPersistence
from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.mapping_page import MappingPage


@pytest.fixture(autouse=True)
def _hermetic_layout_store(monkeypatch, tmp_path):
    """Isolate the QSettings-backed layout store per test."""
    import paleo_workbench.ui.pages.mapping_page as mapping_page_module

    settings = QSettings(str(tmp_path / "layout.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(
        mapping_page_module,
        "LayoutPersistence",
        lambda: LayoutPersistence(settings),
    )


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


def test_mapping_page_float_wiring_keeps_the_canvas_docked(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)

    assert page.dock_manager.is_floating("layers") is False
    # The center canvas stack never registers as floatable, so it stays a
    # splitter child (never reparented into a floating window).
    assert page.center_stack.parent() is page.mid_splitter


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
