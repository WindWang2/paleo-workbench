from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import (
    PaleoMapDocument,
    PredictionTask,
    ProjectDocument,
)
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


def test_generate_demo_map_draft_from_prediction_regions(qtbot):
    project = ProjectDocument.new("Demo Draft")
    project.stratigraphy.target_horizon = "C6"
    project.prediction_tasks.append(
        PredictionTask(
            name="p",
            status="complete",
            result_summary={
                "predicted_regions": [
                    {"region_id": "r1", "facies": "砂", "probability": 0.9},
                    {"region_id": "r2", "facies": "泥", "probability": 0.6},
                ],
                "is_mock": True,
            },
        )
    )

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)

    assert window.project.paleomap_documents == []

    page = window.app_shell.mapping_page_widget()
    assert isinstance(page, MappingPage)
    page.generate_demo_draft_requested.emit()

    assert len(window.project.paleomap_documents) == 1
    doc = window.project.paleomap_documents[0]
    assert doc.view_state.get("is_demo_draft") is True
    assert len(doc.facies_polygons) == 2

    refreshed = window.app_shell.mapping_page_widget()
    assert isinstance(refreshed, MappingPage)
    assert refreshed.active_document() is not None
    assert refreshed.active_document().id == doc.id
    root = refreshed.layer_tree.tree.topLevelItem(0)
    assert root.childCount() == 1
    assert "相带草稿" in root.child(0).text(0)
