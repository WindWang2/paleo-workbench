from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.prediction_task_panel import PredictionTaskPanel


def test_prediction_task_panel_empty_state(qtbot):
    panel = PredictionTaskPanel()
    qtbot.addWidget(panel)

    panel.update_state([])

    assert panel.objectName() == "PredictionTaskPanel"
    assert panel.name_value.text() == "未选择预测任务"
    assert panel.status_value.text() == "待开始"
    assert panel.mean_probability_value.text() == "—"
    assert panel.review_count_value.text() == "0 个"


def test_prediction_task_panel_update_state(qtbot):
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=1)
    panel = PredictionTaskPanel()
    qtbot.addWidget(panel)

    panel.update_state(project.prediction_tasks)

    assert panel.name_value.text() == task.name
    assert panel.adapter_value.text() == "mock"
    assert panel.status_value.text() == "complete"
    assert panel.mean_probability_value.text() == str(task.probability_summary["mean_probability"])
    assert panel.task_list.count() == 1
