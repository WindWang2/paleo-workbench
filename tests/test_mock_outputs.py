from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.workflow.factors import create_mock_factor_map


def test_mock_factor_map_is_deterministic():
    project_a = ProjectDocument.new("A")
    project_b = ProjectDocument.new("B")

    task_a = create_mock_factor_map(project_a, "ZJ2", "sand_thickness", seed=42)
    task_b = create_mock_factor_map(project_b, "ZJ2", "sand_thickness", seed=42)

    assert task_a.parameters["sample_points"] == task_b.parameters["sample_points"]
    assert task_a.input_snapshot_hash == task_b.input_snapshot_hash
    assert task_a.source_kind == "mock"


def test_mock_prediction_is_deterministic():
    project = ProjectDocument.new("Demo")
    factor = create_mock_factor_map(project, "ZJ2", "sand_thickness", seed=42)
    adapter = MockPredictionAdapter()

    first = adapter.run(project, [factor.id], seed=7)
    second = adapter.run(project, [factor.id], seed=7)

    assert first.result_summary == second.result_summary
    assert first.probability_summary == second.probability_summary
    assert first.adapter_schema_version == "1.0"
