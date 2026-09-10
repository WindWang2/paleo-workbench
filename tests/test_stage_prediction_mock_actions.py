"""智能预测阶段：两个 mock 生成按钮（fallback 画布 + 真 catalog）。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from paleo_workbench.catalog import CoreCatalogAdapter, DataCatalogService
from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.runtime import reset_catalog, set_catalog
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.project.domain import WellEntity, WorkArea
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.workstation.stage_actions import stage_context_actions

QApplication.instance() or QApplication([])


def _composite(qtbot, monkeypatch, project):
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)
    return doc


def _project() -> ProjectDocument:
    project = ProjectDocument.new("mock 预测")
    project.coordinate.project_crs = "EPSG:32650"
    project.workarea = WorkArea(
        name="工区",
        boundary=[[-2, -2], [12, -2], [12, 2], [-2, 2], [-2, -2]],
        project_crs="EPSG:32650",
        boundary_crs="EPSG:32650",
    )
    project.wells.extend([
        WellEntity(id="well_a", name="A", project_x=0.0, project_y=0.0, td=1200.0),
        WellEntity(id="well_b", name="B", project_x=10.0, project_y=0.0),
    ])
    project.resources.extend([
        ResourceItem(id="res_a", name="A", path="a.las", type="well_log", format="las"),
        ResourceItem(id="res_b", name="B", path="b.las", type="well_log", format="las"),
    ])
    project.stratigraphy.target_horizon = "Sq1"
    return project


@pytest.fixture
def catalog(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    try:
        yield service
    finally:
        reset_catalog()
        service.close()


def test_actions_listed_after_overlay_actions():
    ids = [action_id for action_id, _ in stage_context_actions("facies_calibration")]
    assert ids[:3] == [
        "add_seismic_prediction_overlay",
        "add_well_prediction_overlay",
        "well_prediction_point_to_surface",
    ]
    assert "run_well_facies_mock" in ids and "run_seismic_facies_mock" in ids


def test_dispatch_mock_requires_horizon(qtbot, monkeypatch, catalog):
    project = _project()
    project.stratigraphy.target_horizon = ""
    doc = _composite(qtbot, monkeypatch, project)
    messages = []
    doc.status_message.connect(messages.append)
    doc.stage_actions.dispatch("facies_calibration", "run_well_facies_mock")
    assert any("编图层位" in text for text in messages)
    assert not project.prediction_tasks


def test_run_well_facies_mock_end_to_end(qtbot, monkeypatch, catalog):
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "run_well_facies_mock")
    assert len(project.prediction_tasks) == 1
    task = project.prediction_tasks[0]
    assert task.adapter_kind == "mock"
    assert task.result_summary["is_mock"] is True
    assert task.result_summary["final_scientific_prediction"] is False
    regions = task.result_summary["predicted_regions"]
    assert len(regions) == 2
    assert {r["stratigraphic_unit"] for r in regions} == {"Sq1"}
    assert task.input_refs["well_log_resource_ids"] == ["res_a", "res_b"]
    # 血缘：run 完成且三向链接
    run = catalog.get_run(task.model_metadata["run_id"])
    assert run.status == "complete"
    assert run.parameters.get("_domain_task_id") == task.id
    assert task.model_metadata["prediction_version_id"] in run.output_version_ids
    # 中间文件：同 run 的 INTERMEDIATE 版本
    stages = {
        version.stage
        for version in catalog.document.versions
        if version.id in set(run.output_version_ids)
    }
    assert DataStage.DERIVED in stages and DataStage.INTERMEDIATE in stages
    # 自动叠加：井点层出现
    ids = doc.stage_controller.state.layers_with_role(LayerRole.WELL_FACIES_PREDICTION)
    assert ids


def test_run_seismic_facies_mock_end_to_end(qtbot, monkeypatch, catalog):
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "run_seismic_facies_mock")
    assert len(project.prediction_tasks) == 1
    task = project.prediction_tasks[0]
    spatial = task.result_summary.get("spatial") or {}
    assert spatial.get("type") == "VECTOR_POLYGONS"
    features = spatial.get("features") or []
    assert features
    for feature in features:
        for ring in feature["geometry"]["coordinates"]:
            for x, y in ring:
                assert -3 <= x <= 13 and -3 <= y <= 3  # 工区 bbox 附近
    run = catalog.get_run(task.model_metadata["run_id"])
    stages = {
        version.stage
        for version in catalog.document.versions
        if version.id in set(run.output_version_ids)
    }
    assert DataStage.DERIVED in stages and DataStage.INTERMEDIATE in stages
    ids = doc.stage_controller.state.layers_with_role(
        LayerRole.SEISMIC_FACIES_PREDICTION)
    assert ids


def test_repeat_runs_create_distinct_tasks(qtbot, monkeypatch, catalog):
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    doc.stage_actions.dispatch("facies_calibration", "run_well_facies_mock")
    doc.stage_actions.dispatch("facies_calibration", "run_well_facies_mock")
    assert len(project.prediction_tasks) == 2
    assert project.prediction_tasks[0].id != project.prediction_tasks[1].id


def test_run_mock_without_catalog_graceful(qtbot, monkeypatch):
    reset_catalog()
    project = _project()
    doc = _composite(qtbot, monkeypatch, project)
    messages = []
    doc.status_message.connect(messages.append)
    doc.stage_actions.dispatch("facies_calibration", "run_well_facies_mock")
    assert not project.prediction_tasks
    assert any("编目" in text for text in messages)
