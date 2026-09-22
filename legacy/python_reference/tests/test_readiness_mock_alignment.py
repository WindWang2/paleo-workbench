"""就绪度与 mock/空白相对齐：mock 任务诚实标注，工区默认空白相算初始相图存在。

纯领域单测（无 Qt）：ProjectDocument.new + 构造 PredictionTask/WorkArea。
"""
from __future__ import annotations

from paleo_workbench.mapping_workspace.readiness import (
    ReadinessItemStatus,
    check_initial_facies_present,
    check_seismic_prediction_confidence,
    check_well_prediction_linked,
)
from paleo_workbench.project.domain import WorkArea
from paleo_workbench.project.models import (
    PaleoMapDocument,
    PredictionTask,
    ProjectDocument,
)


def _workarea() -> WorkArea:
    return WorkArea(
        name="工区",
        boundary=[[-2, -2], [12, -2], [12, 2], [-2, 2], [-2, -2]],
        project_crs="EPSG:32650",
        boundary_crs="EPSG:32650",
    )


def _polygon_feature() -> dict:
    return {
        "facies": "砂岩",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]],
        },
        "properties": {"facies": "砂岩"},
    }


# -- well ---------------------------------------------------------------------


def test_well_real_task_keeps_original_copy():
    project = ProjectDocument.new("readiness")
    project.prediction_tasks.append(PredictionTask(
        name="测井相预测", adapter_kind="local",
        input_refs={"well_log_resource_ids": ["res_a"]},
    ))
    item = check_well_prediction_linked(project)
    assert item.status is ReadinessItemStatus.OK
    assert item.title == "测井预测已关联"
    assert item.detail == "1 个预测任务"


def test_well_mock_only_is_ok_with_honest_label():
    project = ProjectDocument.new("readiness")
    project.prediction_tasks.append(PredictionTask(
        name="测井相预测（mock）", adapter_kind="mock",
        input_refs={"well_log_resource_ids": ["res_a"]},
    ))
    item = check_well_prediction_linked(project)
    assert item.status is ReadinessItemStatus.OK
    assert "mock 演示" in item.detail


def test_well_no_tasks_stays_warning():
    project = ProjectDocument.new("readiness")
    item = check_well_prediction_linked(project)
    assert item.status is ReadinessItemStatus.WARNING


# -- seismic ------------------------------------------------------------------


def test_seismic_all_mock_is_ok_without_confidence_stats():
    project = ProjectDocument.new("readiness")
    project.prediction_tasks.append(PredictionTask(
        name="地震相面预测（mock）", adapter_kind="mock",
        probability_summary={"mean_probability": 0.7},
    ))
    item = check_seismic_prediction_confidence(project)
    assert item.status is ReadinessItemStatus.OK
    assert "概率未标定" in item.detail


def test_seismic_with_real_low_confidence_keeps_warning_copy():
    project = ProjectDocument.new("readiness")
    project.prediction_tasks.append(PredictionTask(
        name="地震相预测", adapter_kind="local",
        probability_summary={"low_confidence_regions": 2},
    ))
    project.prediction_tasks.append(PredictionTask(
        name="地震相面预测（mock）", adapter_kind="mock",
        probability_summary={"mean_probability": 0.7},
    ))
    item = check_seismic_prediction_confidence(project)
    assert item.status is ReadinessItemStatus.WARNING
    assert "低置信度" in item.title


def test_seismic_no_tasks_stays_warning():
    project = ProjectDocument.new("readiness")
    item = check_seismic_prediction_confidence(project)
    assert item.status is ReadinessItemStatus.WARNING


# -- initial facies ------------------------------------------------------------


def test_initial_facies_with_document_stays_ok():
    project = ProjectDocument.new("readiness")
    project.paleomap_documents.append(PaleoMapDocument(
        name="已有相图", linked_target_horizon="Sq1",
        facies_polygons=[_polygon_feature()],
    ))
    item = check_initial_facies_present(project)
    assert item.status is ReadinessItemStatus.OK


def test_initial_facies_without_document_but_workarea_is_ok():
    project = ProjectDocument.new("readiness")
    project.workarea = _workarea()
    item = check_initial_facies_present(project)
    assert item.status is ReadinessItemStatus.OK
    assert "空白相" in item.title


def test_initial_facies_missing_everything_stays_error():
    project = ProjectDocument.new("readiness")
    item = check_initial_facies_present(project)
    assert item.status is ReadinessItemStatus.ERROR
