from paleo_workbench.ui.pages.workflow_progress import WorkflowProgress
from paleo_workbench.ui import tokens


def test_workflow_progress_has_six_steps(qtbot):
    widget = WorkflowProgress()
    qtbot.addWidget(widget)
    assert len(widget.step_widgets) == 6


def test_workflow_progress_step_labels(qtbot):
    widget = WorkflowProgress()
    qtbot.addWidget(widget)
    labels = [sw["label"].text() for sw in widget.step_widgets]
    assert labels == tokens.STEP_LABELS


def test_workflow_progress_default_all_pending(qtbot):
    widget = WorkflowProgress()
    qtbot.addWidget(widget)
    for sw in widget.step_widgets:
        assert "待开始" in sw["status"].text()


def test_workflow_progress_update_steps(qtbot):
    widget = WorkflowProgress()
    qtbot.addWidget(widget)
    steps = [
        type("S", (), {"step_type": "data_check", "status": "complete"}),
        type("S", (), {"step_type": "factor_map", "status": "running"}),
        type("S", (), {"step_type": "prediction", "status": "pending"}),
        type("S", (), {"step_type": "map_compile", "status": "pending"}),
        type("S", (), {"step_type": "qc", "status": "pending"}),
        type("S", (), {"step_type": "export", "status": "pending"}),
    ]
    widget.update_steps(steps)
    assert "完成" in widget.step_widgets[0]["status"].text()
    assert "进行中" in widget.step_widgets[1]["status"].text()
    assert "待开始" in widget.step_widgets[2]["status"].text()
