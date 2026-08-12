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


def test_workflow_progress_badges_expose_step_colors(qtbot):
    widget = WorkflowProgress()
    qtbot.addWidget(widget)
    for index, step_widget in enumerate(widget.step_widgets):
        badge = step_widget["badge"]
        assert badge.objectName() == "WorkflowStepBadge"
        assert badge.property("stepColor") == tokens.STEP_COLORS[index]
        assert f"background: {tokens.STEP_COLORS[index]}" in badge.styleSheet()


def test_workflow_progress_default_all_pending(qtbot):
    widget = WorkflowProgress()
    qtbot.addWidget(widget)
    pending = tokens.STATUS_TEXT["pending"]
    for sw in widget.step_widgets:
        assert pending in sw["status"].text()


def test_workflow_progress_update_steps(qtbot):
    widget = WorkflowProgress()
    qtbot.addWidget(widget)
    steps = [
        type("S", (), {"step_type": "data_check", "status": "complete"}),
        type("S", (), {"step_type": "factor_map", "status": "running"}),
        type("S", (), {"step_type": "prediction", "status": "pending"}),
        type("S", (), {"step_type": "map_compile", "status": "stale"}),
        type("S", (), {"step_type": "qc", "status": "pending"}),
        type("S", (), {"step_type": "export", "status": "pending"}),
    ]
    widget.update_steps(steps)
    assert tokens.STATUS_TEXT["complete"] in widget.step_widgets[0]["status"].text()
    assert tokens.STATUS_TEXT["running"] in widget.step_widgets[1]["status"].text()
    assert tokens.STATUS_TEXT["pending"] in widget.step_widgets[2]["status"].text()
    assert tokens.STATUS_TEXT["stale"] in widget.step_widgets[3]["status"].text()
    # Button is shown when any step is stale (may still be False if parent not shown)
    assert not widget.recompute_button.isHidden()
    assert "需更新" in widget.plan_label.text() or widget.plan_label.text() != ""
