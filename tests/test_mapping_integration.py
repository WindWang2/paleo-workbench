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
    page = window.app_shell.page_stack.widget(8)
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
    page = window.app_shell.page_stack.widget(8)

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


def test_generate_demo_map_draft_cancel_when_dirty(qtbot, monkeypatch):
    """Cancel on dirty confirm must not append a demo draft."""
    from PySide6.QtWidgets import QMessageBox

    project = ProjectDocument.new("Dirty Cancel")
    existing = PaleoMapDocument(
        name="Existing",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [2, 0], [2, 2], [0, 0]],
        }],
    )
    project.paleomap_documents.append(existing)

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.mapping_page_widget()
    page.edit_view.scene().translate_features(["f1"], 1.0, 0.0)
    assert page.is_dirty()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Cancel,
    )
    page.generate_demo_draft_requested.emit()

    assert len(window.project.paleomap_documents) == 1
    assert window.project.paleomap_documents[0].id == existing.id
    assert page.is_dirty()


def test_generate_demo_map_draft_discard_when_dirty(qtbot, monkeypatch):
    """Discard proceeds with compile even if scene was dirty."""
    from PySide6.QtWidgets import QMessageBox

    project = ProjectDocument.new("Dirty Discard")
    existing = PaleoMapDocument(
        name="Existing",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [2, 0], [2, 2], [0, 0]],
        }],
    )
    project.paleomap_documents.append(existing)

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.mapping_page_widget()
    page.edit_view.scene().translate_features(["f1"], 1.0, 0.0)
    assert page.is_dirty()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
    )
    page.generate_demo_draft_requested.emit()

    assert len(window.project.paleomap_documents) == 2
    assert window.project.paleomap_documents[-1].view_state.get("is_demo_draft") is True


def test_generate_demo_map_draft_save_when_dirty(qtbot, monkeypatch):
    """Save flushes geometry then compiles demo draft."""
    from PySide6.QtWidgets import QMessageBox

    project = ProjectDocument.new("Dirty Save")
    existing = PaleoMapDocument(
        name="Existing",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [2, 0], [2, 2], [0, 0]],
        }],
    )
    project.paleomap_documents.append(existing)

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.mapping_page_widget()
    page.edit_view.scene().translate_features(["f1"], 3.0, 0.0)
    assert page.is_dirty()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Save,
    )
    page.generate_demo_draft_requested.emit()

    # Original doc should have flushed geometry (x+3) and a demo draft appended
    assert existing.facies_polygons[0]["coordinates"][0][0] == 3.0
    assert len(window.project.paleomap_documents) == 2
    assert window.project.paleomap_documents[-1].view_state.get("is_demo_draft") is True
