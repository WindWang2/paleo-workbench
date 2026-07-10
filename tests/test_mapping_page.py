from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.mapping_page import MappingPage


def test_mapping_page_assembles_gis_shell(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)

    assert page.objectName() == "MappingPage"
    assert isinstance(page.toolbar, MapEditToolbar)
    assert isinstance(page.layer_tree, MapLayerTree)
    assert isinstance(page.edit_view, MapEditView)
    assert isinstance(page.attribute_table, MapAttributeTable)
    assert page.attribute_table.maximumHeight() == 160


def test_mapping_page_update_state_sets_layer_tree(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)

    docs = [
        PaleoMapDocument(name="Map A", linked_target_horizon="H1"),
        PaleoMapDocument(name="Map B", linked_target_horizon="H2"),
    ]
    page.update_state(docs)

    root = page.layer_tree.tree.topLevelItem(0)
    assert root.childCount() == 2
    assert root.child(0).text(0) == "Map A"
    assert root.child(1).text(0) == "Map B"
    # Active is last document — layers under Map B
    assert root.child(1).childCount() == 4


def test_mapping_page_context_snapshot(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    received: list[dict] = []
    page.mapping_context_changed.connect(received.append)

    page.update_state([
        PaleoMapDocument(name="Delta Map", linked_target_horizon="H3"),
    ])
    ctx = page.mapping_context()
    assert ctx["map_name"] == "Delta Map"
    assert ctx["horizon"] == "H3"
    assert ctx["dirty"] is False
    assert received
    assert received[-1]["map_name"] == "Delta Map"


def test_mapping_page_forwards_generate_demo_draft_signal(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    received = []
    page.generate_demo_draft_requested.connect(lambda: received.append(True))

    page.toolbar.generate_demo_draft_btn.click()
    assert received == [True]
