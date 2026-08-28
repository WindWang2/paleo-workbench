"""Tests for the cross-page well-name sync (3D page -> WellLog page).

Stage-3 requirement: at least one cross-page linkage. Picking a well on the 3D
page emits ``well_selected(str)``; the workflow controller forwards it to
``WellLogPredictionPage.set_selected_well``.
"""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtWidgets import QListWidget, QWidget


class _FakeTaskPanel:
    """Minimal stand-in for PredictionTaskPanel exposing ``task_list``."""

    def __init__(self):
        self.task_list = QListWidget()


def test_welllog_set_selected_well_matches_and_selects(qtbot):
    from paleo_workbench.ui.pages.well_log_prediction_page import (
        WellLogPredictionPage,
    )

    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    # Populate with three named tasks (update_state builds the list rows).
    tasks = [
        SimpleNamespace(name="A1"),
        SimpleNamespace(name="B2"),
        SimpleNamespace(name="C3"),
    ]
    page.update_state(tasks)
    assert page.task_panel.task_list.count() == 3

    assert page.set_selected_well("B2") is True
    # The semantic selection state is applied synchronously.
    assert page._selected_index == 1
    assert page._current_task() is tasks[1]


def test_welllog_set_selected_well_returns_false_for_unknown(qtbot):
    from paleo_workbench.ui.pages.well_log_prediction_page import (
        WellLogPredictionPage,
    )

    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    page.update_state([SimpleNamespace(name="A1")])
    assert page.set_selected_well("ZZZ") is False
    assert page.set_selected_well("") is False


def test_geomodel_page_emits_well_selected_on_pick(qtbot):
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )

    page = GeologicalModeling3DPage()
    qtbot.addWidget(page)
    received: list[str] = []
    page.well_selected.connect(lambda name: received.append(name))
    page._handle_joint_well_pick("A1")
    assert received == ["A1"]
    page._handle_joint_well_pick("B2")
    assert received == ["A1", "B2"]


def test_workflow_controller_forwards_well_to_welllog(qtbot):
    """End-to-end (coordination glue): geomodel well_selected -> context ->
    welllog setter. The old page→page wire through WorkflowController was
    replaced by the shared SelectionContext (#1029)."""
    from paleo_workbench.ui.pages.well_log_prediction_page import (
        WellLogPredictionPage,
    )
    from paleo_workbench.ui.pages.geological_modeling_3d_page import (
        GeologicalModeling3DPage,
    )
    from paleo_workbench.ui.view_coordination import ViewCoordinationController
    from paleo_workbench.viz.coordinate_hub import CoordinateTransformHub
    from paleo_workbench.viz.selection_context import SelectionContext

    geomodel = GeologicalModeling3DPage()
    welllog = WellLogPredictionPage()
    qtbot.addWidget(geomodel)
    qtbot.addWidget(welllog)
    welllog.update_state([SimpleNamespace(name="A1")])

    context = SelectionContext()
    hub = CoordinateTransformHub()
    coordination = ViewCoordinationController(context, hub)
    coordination.attach_well_log_page(welllog)
    if hasattr(geomodel, "well_selected"):
        geomodel.well_selected.connect(
            lambda well_id: coordination.publish_well_selection(
                well_id, source=ViewCoordinationController.SOURCE_3D
            )
        )

    geomodel.well_selected.emit("A1")
    assert context.snapshot().active_well_id == "A1"
    assert welllog._selected_index == 0
