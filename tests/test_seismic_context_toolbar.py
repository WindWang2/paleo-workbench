from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.seismic_context_toolbar import SeismicContextToolbar


def test_context_toolbar_displays_active_context_and_emits_run(qtbot):
    task = MockPredictionAdapter().run(ProjectDocument.new("Test"), [], seed=3)
    toolbar = SeismicContextToolbar()
    qtbot.addWidget(toolbar)
    runs: list[bool] = []
    toolbar.run_requested.connect(lambda: runs.append(True))

    toolbar.set_context(task, "C6", "包络", "wiggle")
    toolbar.run_btn.click()

    assert toolbar.objectName() == "SeismicContextToolbar"
    assert toolbar.task_value.text() == task.name
    assert toolbar.horizon_value.text() == "C6"
    assert toolbar.attribute_value.text() == "包络"
    assert toolbar.mode_value.text() == "wiggle"
    assert runs == [True]
