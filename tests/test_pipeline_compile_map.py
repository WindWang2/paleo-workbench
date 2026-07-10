"""Pure tests for 18c compile_map_draft."""

from __future__ import annotations

from paleo_workbench.pipeline.compile_map import compile_map_draft
from paleo_workbench.project.models import (
    CompilationRun,
    FactorMapTask,
    PredictionTask,
    ProjectDocument,
    ResourceItem,
)


def test_compile_map_draft_from_prediction_regions():
    doc = ProjectDocument.new("T")
    doc.stratigraphy.target_horizon = "C6"
    task = PredictionTask(
        name="p",
        status="complete",
        result_summary={
            "predicted_regions": [
                {"region_id": "r1", "facies": "砂", "probability": 0.9},
                {"region_id": "r2", "facies": "泥", "probability": 0.6},
            ],
            "is_mock": True,
        },
    )
    doc.prediction_tasks.append(task)

    m = compile_map_draft(doc, seed=0)

    assert m in doc.paleomap_documents
    assert m.linked_target_horizon == "C6"
    assert m.linked_prediction_task_id == task.id
    assert len(m.facies_polygons) == 2
    assert m.facies_polygons[0]["properties"]["facies"] == "砂"
    assert m.facies_polygons[1]["properties"]["facies"] == "泥"
    assert m.view_state["is_demo_draft"] is True
    assert m.view_state["generator"] == "deterministic-map-draft-v1"
    assert m.view_state["seed"] == 0
    assert m.map_chrome["title"] == "C6 相带草稿"
    assert m.map_chrome["legend_facies"] == ["砂", "泥"]
    assert m.name == "C6 相带草稿"

    # Closed unit square at seed=0 base
    ring0 = m.facies_polygons[0]["geometry"]["coordinates"][0]
    assert ring0[0] == [114.0, 22.5]
    assert ring0[-1] == ring0[0]
    ring1 = m.facies_polygons[1]["geometry"]["coordinates"][0]
    assert ring1[0] == [114.05, 22.5]

    m2 = compile_map_draft(doc, seed=0)
    assert m2 in doc.paleomap_documents
    assert len(doc.paleomap_documents) == 2
    assert m.facies_polygons[0]["geometry"] == m2.facies_polygons[0]["geometry"]
    assert m.facies_polygons[1]["geometry"] == m2.facies_polygons[1]["geometry"]


def test_compile_map_draft_determinism_same_seed():
    doc = ProjectDocument.new("Det")
    task = PredictionTask(
        name="p",
        status="complete",
        result_summary={
            "predicted_regions": [
                {"region_id": "a", "facies": "砂", "probability": 0.8},
            ],
        },
    )
    doc.prediction_tasks.append(task)

    a = compile_map_draft(doc, seed=3)
    b = compile_map_draft(doc, seed=3)
    c = compile_map_draft(doc, seed=7)

    assert a.facies_polygons[0]["geometry"] == b.facies_polygons[0]["geometry"]
    # seed % 10 offsets base_x
    assert a.facies_polygons[0]["geometry"] != c.facies_polygons[0]["geometry"]
    base_a = a.facies_polygons[0]["geometry"]["coordinates"][0][0][0]
    base_c = c.facies_polygons[0]["geometry"]["coordinates"][0][0][0]
    assert base_a == 114.0 + (3 % 10) * 0.001
    assert base_c == 114.0 + (7 % 10) * 0.001


def test_compile_map_draft_with_factor_wells():
    doc = ProjectDocument.new("W")
    doc.stratigraphy.target_horizon = "C6"
    doc.factor_map_tasks.append(
        FactorMapTask(
            name="f",
            target_horizon="C6",
            factor_type="thickness",
            method="demo",
            parameters={
                "sample_points": [
                    {"well": "A1", "x": 114.1, "y": 22.7},
                    {"well": "A2", "x": 114.2, "y": 22.8},
                ],
            },
        )
    )
    m = compile_map_draft(doc, seed=0)
    assert len(m.well_overlays) == 2
    assert m.well_overlays[0] == {
        "name": "A1",
        "lng": 114.1,
        "lat": 22.7,
        "x": 114.1,
        "y": 22.7,
    }
    assert m.well_overlays[1] == {
        "name": "A2",
        "lng": 114.2,
        "lat": 22.8,
        "x": 114.2,
        "y": 22.8,
    }


def test_compile_map_draft_synthetic_wells_from_applicable():
    doc = ProjectDocument.new("Syn")
    doc.stratigraphy.applicable_wells = ["W1", "W2"]
    m = compile_map_draft(doc, seed=0)
    assert m.well_overlays == [
        {"name": "W1", "lng": 114.0, "lat": 22.6, "x": 114.0, "y": 22.6},
        {"name": "W2", "lng": 114.02, "lat": 22.61, "x": 114.02, "y": 22.61},
    ]


def test_compile_map_draft_synthetic_wells_from_well_log_stems():
    doc = ProjectDocument.new("Logs")
    doc.resources.extend(
        [
            ResourceItem(name="A10.Las", path="a", type="well_log", format="las"),
            ResourceItem(name="A1.Las", path="b", type="well_log", format="las"),
        ]
    )
    m = compile_map_draft(doc, seed=0)
    names = [w["name"] for w in m.well_overlays]
    assert names == ["A1", "A10"]


def test_compile_map_draft_always_produces_with_empty_project():
    doc = ProjectDocument.new("Empty")
    m = compile_map_draft(doc, seed=0)
    assert m in doc.paleomap_documents
    assert m.linked_target_horizon == "未指定层位"
    assert m.linked_prediction_task_id is None
    assert len(m.facies_polygons) == 1
    assert m.facies_polygons[0]["properties"]["facies"] == "未分类"
    assert m.well_overlays == []
    assert m.view_state["is_demo_draft"] is True
    assert m.map_chrome["legend_facies"] == ["未分类"]


def test_compile_map_draft_horizon_priority_and_active_run():
    doc = ProjectDocument.new("H")
    doc.stratigraphy.target_horizon = "from_strati"
    doc.compilation_runs.append(
        CompilationRun(name="run", target_horizon="from_run", status="draft")
    )
    # arg wins
    m1 = compile_map_draft(doc, target_horizon="from_arg", seed=0)
    assert m1.linked_target_horizon == "from_arg"
    assert doc.compilation_runs[-1].active_paleomap_document_id == m1.id

    # without arg: last run
    m2 = compile_map_draft(doc, seed=0)
    assert m2.linked_target_horizon == "from_run"
    assert doc.compilation_runs[-1].active_paleomap_document_id == m2.id


def test_compile_map_draft_prediction_task_by_id():
    doc = ProjectDocument.new("P")
    older = PredictionTask(
        name="old",
        status="complete",
        result_summary={
            "predicted_regions": [{"facies": "old_facies", "probability": 0.1}],
        },
    )
    newer = PredictionTask(
        name="new",
        status="complete",
        result_summary={
            "predicted_regions": [{"facies": "new_facies", "probability": 0.9}],
        },
    )
    doc.prediction_tasks.extend([older, newer])

    m_latest = compile_map_draft(doc, seed=0)
    assert m_latest.linked_prediction_task_id == newer.id
    assert m_latest.facies_polygons[0]["properties"]["facies"] == "new_facies"

    m_old = compile_map_draft(doc, prediction_task_id=older.id, seed=0)
    assert m_old.linked_prediction_task_id == older.id
    assert m_old.facies_polygons[0]["properties"]["facies"] == "old_facies"
