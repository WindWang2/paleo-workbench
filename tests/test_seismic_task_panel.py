from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.seismic_task_panel import SeismicTaskPanel


def test_seismic_task_panel_empty_state(qtbot):
    panel = SeismicTaskPanel()
    qtbot.addWidget(panel)

    panel.update_state([])

    assert panel.objectName() == "SeismicTaskPanel"
    assert panel.name_value.text() == "未选择预测任务"
    assert panel.status_value.text() == "待开始"
    assert panel.mean_probability_value.text() == "—"


def test_seismic_task_panel_update_state(qtbot):
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=3)
    panel = SeismicTaskPanel()
    qtbot.addWidget(panel)

    panel.update_state(project.prediction_tasks)

    assert panel.name_value.text() == task.name
    assert panel.adapter_value.text() == "mock"
    assert panel.status_value.text() == "complete"
    assert panel.task_list.count() == 1
