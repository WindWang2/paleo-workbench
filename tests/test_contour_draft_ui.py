"""ISS-MAP-01: ContourDraft UI wiring on preparation + mapping pages."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import FactorMapTask, ProjectDocument
from paleo_workbench.ui.pages.factor_task_panel import FactorTaskPanel
from paleo_workbench.ui.pages.map_factor_shelf import MapFactorShelf
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.ui.pages.preparation_page import PreparationPage
from paleo_workbench.workflow.factor_interpolation import apply_interpolation_to_task


def test_factor_task_panel_has_contour_button(qtbot):
    panel = FactorTaskPanel()
    qtbot.addWidget(panel)
    assert panel.contour_draft_btn.text() == "生成等值线初稿"
    received = []
    panel.contour_draft_requested.connect(lambda: received.append(True))
    panel.contour_draft_btn.click()
    assert received == [True]


def test_map_factor_shelf_emits_contour_request(qtbot):
    shelf = MapFactorShelf()
    qtbot.addWidget(shelf)
    got = []
    shelf.contour_draft_requested.connect(lambda: got.append(1))
    shelf.contour_draft_btn.click()
    assert got == [1]


def test_preparation_page_generates_contour_drafts(qtbot, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    project = ProjectDocument.new("PrepContour")
    task = FactorMapTask(
        name="厚度",
        target_horizon="H1",
        factor_type="地层厚度",
        method="IDW",
        parameters={
            "sample_points": [
                {"x": 0.0, "y": 0.0, "value": 1.0},
                {"x": 1.0, "y": 0.0, "value": 2.0},
                {"x": 0.0, "y": 1.0, "value": 3.0},
                {"x": 1.0, "y": 1.0, "value": 4.0},
            ]
        },
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=8)
    project.factor_map_tasks.append(task)

    page = PreparationPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state(project.factor_map_tasks)

    events = []
    page.contour_drafts_updated.connect(lambda: events.append("ok"))
    page.task_panel.contour_draft_btn.click()

    assert events == ["ok"]
    assert project.contour_drafts
    assert project.paleomap_documents
    assert any(
        f.get("role") == "contour"
        for f in project.paleomap_documents[0].line_features
    )


def test_mapping_page_contour_from_factor_shelf(qtbot, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    project = ProjectDocument.new("MapContour")
    task = FactorMapTask(
        name="砂地比",
        target_horizon="C6",
        factor_type="砂地比",
        method="IDW",
        parameters={
            "sample_points": [
                {"x": 0.0, "y": 0.0, "value": 0.1},
                {"x": 1.0, "y": 0.0, "value": 0.2},
                {"x": 0.0, "y": 1.0, "value": 0.3},
                {"x": 1.0, "y": 1.0, "value": 0.4},
            ]
        },
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=8)
    project.factor_map_tasks.append(task)

    page = MappingPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state(
        project.paleomap_documents,
        factor_tasks=project.factor_map_tasks,
    )
    events = []
    page.contour_drafts_updated.connect(lambda: events.append(True))
    page.bottom_workbench.factor_shelf.contour_draft_btn.click()

    assert events == [True]
    assert project.contour_drafts
    assert page.active_document() is not None
    assert any(
        f.get("role") == "contour"
        for f in page.active_document().line_features
    )


def test_app_wires_preparation_contour_signal(qtbot, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    project = ProjectDocument.new("AppWire")
    task = FactorMapTask(
        name="厚度",
        target_horizon="H1",
        factor_type="地层厚度",
        method="IDW",
        parameters={
            "sample_points": [
                {"x": 0.0, "y": 0.0, "value": 1.0},
                {"x": 1.0, "y": 0.0, "value": 2.0},
                {"x": 0.0, "y": 1.0, "value": 3.0},
                {"x": 1.0, "y": 1.0, "value": 4.0},
            ]
        },
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=6)
    project.factor_map_tasks.append(task)

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    prep = window.app_shell.preparation_page_widget()
    assert isinstance(prep, PreparationPage)
    prep.task_panel.contour_draft_btn.click()
    assert window.project.contour_drafts
    mapping = window.app_shell.mapping_page_widget()
    assert isinstance(mapping, MappingPage)
    assert mapping._project is window.project
