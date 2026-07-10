from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.mapping_page import MappingPage


def test_app_shell_page_seven_is_mapping_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(7)
    assert isinstance(page, MappingPage)


def test_mapping_page_receives_project_map_documents(qtbot):
    project = ProjectDocument.new("Test")
    doc = PaleoMapDocument(
        name="ZJ2 Map",
        linked_target_horizon="ZJ2",
        facies_polygons=[{"type": "Feature", "properties": {"facies": "三角洲"}}],
        well_overlays=[{"name": "HZ26-7", "lng": 115.0, "lat": 25.0}],
    )
    project.paleomap_documents.append(doc)

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(7)

    assert isinstance(page.layer_tree, MapLayerTree)
    assert isinstance(page.edit_view, MapEditView)

    root = page.layer_tree.tree.topLevelItem(0)
    assert root.childCount() == 1
    assert root.child(0).text(0) == "ZJ2 Map"
    # Layers populated for active document
    assert root.child(0).childCount() == 4
    assert page.edit_view.scene() is not None
