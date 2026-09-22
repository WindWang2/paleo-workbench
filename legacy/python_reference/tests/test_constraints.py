"""ISS-DOM-02 / ISS-ALG-03: ConstraintLayers + break lines into IDW."""

from __future__ import annotations

from paleo_workbench.project.models import (
    ConstraintLayers,
    ConstraintLine,
    FactorMapTask,
    PaleoMapDocument,
    ProjectDocument,
)
from paleo_workbench.workflow.constraints import (
    active_lines,
    break_polylines_for_idw,
    constraint_line_from_map_feature,
    constraints_from_map_document,
    direction_line_params,
    line_features_from_constraints,
    upsert_constraint_layers,
)
from paleo_workbench.workflow.factor_interpolation import (
    apply_interpolation_to_task,
    interpolate_factor_grid,
)


def test_break_polylines_for_idw_filters_role_and_active():
    layers = ConstraintLayers(
        name="C6 constraints",
        target_horizon="C6",
        lines=[
            ConstraintLine(
                name="F1",
                role="break",
                coordinates=[[0, 0], [1, 1], [2, 0]],
                target_horizon="C6",
            ),
            ConstraintLine(
                name="inactive",
                role="break",
                coordinates=[[0, 1], [1, 2]],
                active=False,
            ),
            ConstraintLine(
                name="dir",
                role="direction",
                coordinates=[[0, 0], [0, 1]],
                azimuth_deg=0.0,
            ),
            ConstraintLine(
                name="other_h",
                role="break",
                coordinates=[[5, 5], [6, 6]],
                target_horizon="H9",
            ),
        ],
    )
    breaks = break_polylines_for_idw(layers, target_horizon="C6")
    assert len(breaks) == 1
    assert breaks[0][0] == (0.0, 0.0)
    assert breaks[0][-1] == (2.0, 0.0)

    dirs = direction_line_params(layers, target_horizon="C6")
    assert len(dirs) == 1
    assert dirs[0]["azimuth_deg"] == 0.0


def test_map_feature_roundtrip_role_stamp():
    feat = {
        "id": "L1",
        "name": "断层1",
        "role": "break",
        "coordinates": [[10, 10], [11, 12]],
        "properties": {"note": "demo"},
    }
    line = constraint_line_from_map_feature(feat)
    assert line is not None
    assert line.role == "break"
    assert line.name == "断层1"

    # Without role → not a constraint
    assert constraint_line_from_map_feature({"coordinates": [[0, 0], [1, 1]]}) is None

    layers = ConstraintLayers(lines=[line])
    exported = line_features_from_constraints(layers)
    assert exported[0]["role"] == "break"
    assert exported[0]["properties"]["constraint_role"] == "break"


def test_constraints_from_map_document():
    doc = PaleoMapDocument(
        name="Map",
        linked_target_horizon="C6",
        line_features=[
            {
                "id": "f1",
                "role": "break",
                "coordinates": [[0, 0], [1, 0]],
            },
            {"id": "plain", "coordinates": [[2, 2], [3, 3]]},
        ],
    )
    layers = constraints_from_map_document(doc)
    assert layers.target_horizon == "C6"
    assert len(layers.lines) == 1
    assert layers.lines[0].role == "break"


def test_upsert_constraint_layers_on_project():
    project = ProjectDocument.new("P")
    a = ConstraintLayers(name="A", lines=[])
    upsert_constraint_layers(project, a)
    assert len(project.constraint_layers) == 1
    a2 = a.model_copy(update={"name": "A2"})
    upsert_constraint_layers(project, a2)
    assert len(project.constraint_layers) == 1
    assert project.constraint_layers[0].name == "A2"


def test_project_serializes_constraint_layers():
    project = ProjectDocument.new("Ser")
    project.constraint_layers.append(
        ConstraintLayers(
            name="L",
            lines=[
                ConstraintLine(role="break", coordinates=[[0, 0], [1, 1]]),
            ],
        )
    )
    restored = ProjectDocument.model_validate(project.model_dump())
    assert restored.constraint_layers[0].lines[0].role == "break"


def test_interpolate_with_break_lines_records_count():
    points = [
        {"x": 0.0, "y": 0.0, "value": 1.0},
        {"x": 1.0, "y": 0.0, "value": 2.0},
        {"x": 0.0, "y": 1.0, "value": 3.0},
        {"x": 1.0, "y": 1.0, "value": 4.0},
    ]
    faults = [[(0.5, -0.5), (0.5, 1.5)]]
    result = interpolate_factor_grid(
        points, method="IDW", grid_n=6, fault_polylines=faults
    )
    assert result["n_break_lines"] == 1
    assert result["backend"] == "idw"


def test_apply_interpolation_pulls_breaks_from_project():
    project = ProjectDocument.new("Breaks")
    project.constraint_layers.append(
        ConstraintLayers(
            name="C",
            target_horizon="H1",
            lines=[
                ConstraintLine(
                    role="break",
                    coordinates=[[0.5, -1], [0.5, 2]],
                    target_horizon="H1",
                )
            ],
        )
    )
    task = FactorMapTask(
        name="厚度",
        target_horizon="H1",
        factor_type="地层厚度",
        method="IDW",
        parameters={
            "sample_points": [
                {"x": 0.0, "y": 0.0, "value": 1.0},
                {"x": 1.0, "y": 0.0, "value": 2.0},
                {"x": 0.0, "y": 1.0, "value": 3.0},
                {"x": 1.0, "y": 1.0, "value": 4.0},
            ]
        },
    )
    apply_interpolation_to_task(task, method="IDW", grid_n=8, project=project)
    assert task.status == "complete"
    assert task.parameters.get("n_break_lines") == 1
    assert len(task.parameters.get("break_polylines") or []) == 1


def test_active_lines_horizon_filter():
    layers = [
        ConstraintLayers(
            target_horizon="A",
            lines=[ConstraintLine(role="break", coordinates=[[0, 0], [1, 0]])],
        ),
        ConstraintLayers(
            target_horizon="B",
            lines=[ConstraintLine(role="break", coordinates=[[2, 2], [3, 3]])],
        ),
    ]
    only_a = active_lines(layers, role="break", target_horizon="A")
    assert len(only_a) == 1
    assert only_a[0].coordinates[0] == [0, 0]
