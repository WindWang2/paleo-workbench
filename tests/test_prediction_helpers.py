from geoviz import WellLogData

from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.pages.prediction_helpers import (
    active_prediction_task,
    well_log_data_from_prediction,
)


def test_active_prediction_task_selects_latest():
    project = ProjectDocument.new("Test")
    first = MockPredictionAdapter().run(project, [], seed=1)
    second = MockPredictionAdapter().run(project, [], seed=2)

    assert active_prediction_task(project.prediction_tasks) is second
    assert active_prediction_task([]) is None


def test_well_log_data_from_prediction_builds_probability_curve_and_facies():
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=1)

    data = well_log_data_from_prediction(task)

    assert isinstance(data, WellLogData)
    assert data.well_name == task.name
    assert data.top_depth == 0.0
    assert data.bottom_depth == 100.0
    assert data.curves[0].name == "预测概率"
    assert len(data.curves[0].depth) == 4
    assert data.curves[0].color == "#6f47cf"
    assert len(data.facies) == 4
    assert type(data.facies[0]).__name__ == "FaciesInterval"
    assert data.facies[0].top == 0.0
    assert data.facies[0].bottom == 25.0
    assert data.facies[0].facies == task.result_summary["predicted_regions"][0]["facies"]
    assert data.facies[0].sub_facies == ""
    assert data.facies[0].micro_facies == ""
