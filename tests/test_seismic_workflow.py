"""T-SEIS-01: seismic facies workflow controls → SeismicView + run/send."""

from __future__ import annotations

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage
from paleo_workbench.workflow.seismic_prediction import (
    SEISMIC_ATTRIBUTE_LABELS,
    run_seismic_facies_prediction,
)


def test_run_seismic_facies_prediction_binds_assets_and_horizon():
    project = ProjectDocument.new("Seis")
    project.stratigraphy.target_horizon = "C6"
    project.resources.append(
        ResourceItem(
            name="cube.sgy",
            path="/tmp/cube.sgy",
            type="seismic",
            format="sgy",
        )
    )
    task = run_seismic_facies_prediction(project, seed=2)
    assert task.status == "complete"
    assert task.model_metadata.get("workflow") == "seismic_facies"
    assert task.model_metadata.get("target_horizon") == "C6"
    assert task.input_refs.get("seismic_resource_ids") == [project.resources[0].id]
    assert "C6" in task.name


def test_control_panel_emits_mode_and_attribute(qtbot):
    from paleo_workbench.ui.pages.seismic_control_panel import SeismicControlPanel

    panel = SeismicControlPanel()
    qtbot.addWidget(panel)
    modes: list[str] = []
    attrs: list[str] = []
    ties: list[bool] = []
    panel.display_mode_changed.connect(modes.append)
    panel.attribute_changed.connect(attrs.append)
    panel.well_tie_toggled.connect(ties.append)

    panel.mode_combo.setCurrentText("wiggle")
    panel.attribute_combo.setCurrentText(SEISMIC_ATTRIBUTE_LABELS[1])
    panel.well_tie_btn.setChecked(True)

    assert modes[-1] == "wiggle"
    assert attrs[-1] == SEISMIC_ATTRIBUTE_LABELS[1]
    assert ties[-1] is True


def test_view_panel_bridges_mode_and_attribute(qtbot):
    from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel
    import numpy as np

    panel = SeismicViewPanel()
    qtbot.addWidget(panel)
    volume = np.zeros((4, 5, 6), dtype=np.float32)
    panel._show_volume(volume)

    panel.set_display_mode("wiggle")
    assert panel.display_mode() == "wiggle"

    # Attribute combo may or may not include all labels depending on engine version
    ok = panel.set_attribute_label("包络") or panel.set_attribute_label("振幅")
    assert ok is True
    assert panel.attribute_label()


def test_page_run_creates_task_and_updates_view(qtbot):
    project = ProjectDocument.new("Run")
    project.stratigraphy.target_horizon = "H9"
    page = SeismicPredictionPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state([], project=project)

    page.control_panel.run_btn.click()

    assert len(project.prediction_tasks) == 1
    assert page.view_panel.volume_shape == (8, 10, 12)
    assert page.control_panel.horizon_value.text() == "H9"
    assert "H9" in page.task_panel.name_value.text()


def test_app_send_to_mapping_compiles_draft(qtbot):
    project = ProjectDocument.new("Send")
    project.stratigraphy.target_horizon = "ZJ2"
    run_seismic_facies_prediction(project, seed=1)

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.seismic_prediction_page_widget()
    assert isinstance(page, SeismicPredictionPage)

    before = len(window.project.paleomap_documents)
    page.control_panel.send_btn.click()

    assert len(window.project.paleomap_documents) == before + 1
    assert isinstance(window.project.paleomap_documents[-1], PaleoMapDocument)
