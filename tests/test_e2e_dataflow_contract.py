"""T-FLOW-01: End-to-end data-object handoff contracts (no GUI).

Validates producer → consumer shape across the core pipeline:
resources → factor → prediction → map → qc → export → dashboard.
"""

from __future__ import annotations

from pathlib import Path
import json

from paleo_workbench.pipeline.compile_map import compile_map_draft
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.resources.export_service import export_project_inventory
from paleo_workbench.resources.import_service import import_files
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.workflow.export import record_export
from paleo_workbench.workflow.factors import create_mock_factor_map
from paleo_workbench.workflow.qc import run_basic_qc
from paleo_workbench.workflow.service import create_compilation_run, dashboard_state


def _write_minimal_las(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                " WRAP. NO:",
                "~WELL INFORMATION",
                " STRT.M 0.0:",
                " STOP.M 2.0:",
                " STEP.M 1.0:",
                " NULL. -999.25:",
                " WELL. A1:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                "~ASCII",
                "0.0 10.0",
                "1.0 20.0",
                "2.0 30.0",
            ]
        ),
        encoding="utf-8",
    )


def test_e2e_dataflow_contract_roundtrip(tmp_path: Path):
    project_path = tmp_path / "flow.paleo.json"
    wells = tmp_path / "data"
    wells.mkdir()
    las = wells / "A1.Las"
    _write_minimal_las(las)

    project = ProjectDocument.new("FlowDemo")
    project.meta.project_root = str(tmp_path)

    # 1) Data import → ResourceItem
    report = import_files([las], [], project_path=project_path)
    assert report.added_count == 1
    project.resources.extend(report.added)
    resource = project.resources[0]
    assert resource.type == "well_log"
    assert resource.artifact_role == "input"

    # 2) Compilation run + stratigraphy binding
    run = create_compilation_run(project, "Flow Run", "D53", "三级层序")
    assert project.stratigraphy.target_horizon == "D53"
    assert len(run.workflow_steps) == 6

    # 3) Factor map task produced
    factor = create_mock_factor_map(project, "D53", "sand_thickness", seed=1)
    assert factor.id in {t.id for t in project.factor_map_tasks}
    run.active_factor_map_task_ids = [factor.id]

    # 4) Prediction consumes factor ids
    pred = MockPredictionAdapter().run(project, [factor.id], seed=2)
    assert pred.id in {t.id for t in project.prediction_tasks}
    run.active_prediction_task_id = pred.id

    # 5) VizAdapter can open LAS resource
    ref = VizAdapter().ref_from_resource(resource)
    assert ref is not None and ref.kind == "well_log"
    payload = VizAdapter().resolve(ref, project)
    assert payload.kind == "well_log"
    assert payload.well_log is not None

    # 6) Map draft from pipeline
    compile_map_draft(project, seed=3)
    assert project.paleomap_documents
    doc = project.paleomap_documents[-1]
    run.active_paleomap_document_id = doc.id
    # Horizon should be consumable by QC
    if not doc.linked_target_horizon:
        doc.linked_target_horizon = project.stratigraphy.target_horizon

    # 7) QC upsert + bind run
    qc1 = run_basic_qc(project, doc.id)
    qc2 = run_basic_qc(project, doc.id)
    assert qc1.id == qc2.id
    assert len(project.quality_reports) == 1
    assert run.active_quality_report_id == qc2.id

    # 8) Export inventory + adapter geojson
    inv_path = tmp_path / "inv.json"
    inv = export_project_inventory(
        project, inv_path, project_path=project_path, register=True
    )
    assert inv.success
    geo_path = tmp_path / "map.geojson"
    geo_path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": list(doc.facies_polygons or []),
            }
        ),
        encoding="utf-8",
    )
    art = record_export(project, doc.id, str(geo_path), "geojson", [pred.id, qc2.id])
    run.export_artifact_ids = [art.id]

    # 9) Persist and reload — contracts survive
    ProjectManager(project_path).save(project)
    loaded = ProjectManager(project_path).load()
    state = dashboard_state(loaded)

    assert state["project_name"] == "FlowDemo"
    assert state["active_target_horizon"] == "D53"
    assert state["factor_map_count"] == 1
    assert state["prediction_count"] == 1
    assert state["export_count"] >= 1
    # QC count does not explode after double run_basic_qc
    assert state["qc_issue_count"] == len(qc2.issues)

    # Resource path still resolvable after load
    assert any(r.type == "well_log" for r in loaded.resources)
    assert loaded.compilation_runs[-1].active_quality_report_id == qc2.id
