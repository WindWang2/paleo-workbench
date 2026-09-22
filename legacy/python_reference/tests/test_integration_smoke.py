from pathlib import Path
import json

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.artifacts import record_export
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument
from paleo_workbench.resources.scanner import scan_resources
from paleo_workbench.workflow.factors import create_mock_factor_map
from paleo_workbench.workflow.qc import run_basic_qc
from paleo_workbench.workflow.service import create_compilation_run, dashboard_state


def test_app_shell_window_shows_project_name(qtbot):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.app import PaleoWorkbenchWindow

    project = ProjectDocument.new("HZ26 Demo")
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    # AppShell replaces WorkflowDashboard; project name appears in status bar
    assert "HZ26 Demo" in window.app_shell.status_bar.status_label.text()


def test_full_mvp_loop_recovers_dashboard_state(tmp_path: Path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / "A1.Las").write_text("~Version\n", encoding="utf-8")
    project_path = tmp_path / "demo.paleo.json"

    project = ProjectDocument.new("Demo")
    project.resources = scan_resources(data_root, project_path=project_path)
    run = create_compilation_run(project, "ZJ2 Run", "ZJ2", "三级层序格架")
    factor = create_mock_factor_map(project, "ZJ2", "sand_thickness", seed=42)
    pred = MockPredictionAdapter().run(project, [factor.id], seed=7)
    doc = PaleoMapDocument(name="ZJ2 Map", linked_target_horizon="ZJ2", linked_prediction_task_id=pred.id)
    project.paleomap_documents.append(doc)
    qc = run_basic_qc(project, doc.id)

    export_path = tmp_path / "demo.artifacts" / "exports" / "map.geojson"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8"
    )
    artifact = record_export(project, doc.id, str(export_path), "geojson", [pred.id, qc.id])
    run.active_factor_map_task_ids = [factor.id]
    run.active_prediction_task_id = pred.id
    run.active_paleomap_document_id = doc.id
    run.active_quality_report_id = qc.id
    run.export_artifact_ids = [artifact.id]

    ProjectManager(project_path).save(project)
    loaded = ProjectManager(project_path).load()
    state = dashboard_state(loaded)

    assert state["project_name"] == "Demo"
    assert state["active_target_horizon"] == "ZJ2"
    assert state["factor_map_count"] == 1
    assert state["prediction_count"] == 1
    assert state["export_count"] == 1