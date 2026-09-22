import numpy as np

from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.viz.seismic_prediction_helpers import seismic_volume_from_prediction


def test_seismic_volume_from_prediction_is_deterministic():
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=4)

    first = seismic_volume_from_prediction(task)
    second = seismic_volume_from_prediction(task)

    assert first.shape == (8, 10, 12)
    assert first.dtype == np.float32
    assert np.array_equal(first, second)


def test_seismic_volume_from_prediction_changes_with_seed():
    project = ProjectDocument.new("Test")
    first_task = MockPredictionAdapter().run(project, [], seed=4)
    second_task = MockPredictionAdapter().run(project, [], seed=5)

    assert not np.array_equal(
        seismic_volume_from_prediction(first_task),
        seismic_volume_from_prediction(second_task),
    )
