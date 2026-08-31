from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from paleo_workbench import tokens
from paleo_workbench.ui.workflow_stepper import WorkflowStepper


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_workflow_stepper_initialization(qapp):
    stepper = WorkflowStepper()
    assert stepper.objectName() == "WorkflowStepper"
    # Slim 28px bar sized for the command header row.
    assert stepper.height() == 28 or stepper.maximumHeight() == 28
    assert len(stepper.stage_buttons) == 4
    assert stepper.active_stage_index == 0
    assert stepper.stage_buttons[0].property("active") is True
    assert stepper.stage_buttons[1].property("active") is False
    # Progressive connectors between the 4 stages, unfilled at stage 1.
    assert len(stepper._connectors) == 3
    assert tokens.BORDER_STRONG in stepper._connectors[0].styleSheet()
    # Legacy token-sheet QFrame#WorkflowStepper border is neutralized (r1
    # p2-2): the bar lives inside the header row and must not paint a
    # second border-bottom line under it.
    assert "border: none" in stepper.styleSheet()


def test_workflow_stepper_connectors_fill_with_progress(qapp):
    stepper = WorkflowStepper()
    stepper.set_active_stage(3)
    for connector in stepper._connectors:
        assert tokens.PRIMARY in connector.styleSheet()
    stepper.set_active_stage(0)
    for connector in stepper._connectors:
        assert tokens.BORDER_STRONG in connector.styleSheet()


def test_workflow_stepper_click_emits_signal(qapp):
    stepper = WorkflowStepper()
    emitted = []
    stepper.stage_changed.connect(lambda idx: emitted.append(idx))

    # Click Stage 2 (Index 2)
    stepper.stage_buttons[2].click()
    assert emitted == [2]
    assert stepper.active_stage_index == 2
    assert stepper.stage_buttons[0].property("active") is False
    assert stepper.stage_buttons[2].property("active") is True


def test_workflow_stepper_set_active_stage(qapp):
    stepper = WorkflowStepper()
    stepper.set_active_stage(3)
    assert stepper.active_stage_index == 3
    assert stepper.stage_buttons[3].property("active") is True
    assert stepper.stage_buttons[0].property("active") is False
