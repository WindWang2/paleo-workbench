from paleo_workbench.project.artifacts import record_export
from paleo_workbench.project.models import (
    FactorMapTask,
    PaleoMapDocument,
    PredictionTask,
    ProjectDocument,
    ResourceItem,
)
from paleo_workbench.workflow.qc import run_basic_qc
from paleo_workbench.workflow.service import (
    create_compilation_run,
    dashboard_state,
    home_workflow_steps,
    infer_workflow_step_status,
)


def test_create_compilation_run_adds_ordered_steps():
    project = ProjectDocument.new(name="Demo")

    run = create_compilation_run(
        project,
        name="ZJ2 编图",
        target_horizon="ZJ2",
        sequence_scheme="三级层序格架",
    )

    assert project.compilation_runs == [run]
    assert project.stratigraphy.target_horizon == "ZJ2"
    assert project.stratigraphy.systems_tract_scheme == "三级层序格架"
    assert [step.step_type for step in run.workflow_steps] == [
        "data_check",
        "factor_map",
        "prediction",
        "map_compile",
        "qc",
        "export",
    ]


def test_dashboard_state_reports_missing_and_available_resources():
    project = ProjectDocument.new(name="Demo")
    project.resources.extend(
        [
            ResourceItem(name="A1.Las", path="data/A1.Las", type="well_log", format="las"),
            ResourceItem(
                name="200P_seismic.sgy",
                path="data/200P_seismic.sgy",
                type="seismic",
                format="sgy",
            ),
        ]
    )
    create_compilation_run(project, "Run", "ZJ2", "三级层序格架")

    state = dashboard_state(project)

    assert state["active_target_horizon"] == "ZJ2"
    assert state["resource_counts"]["well_log"] == 1
    assert state["resource_counts"]["seismic"] == 1
    assert state["workflow_status"] == "draft"
    assert state["resource_readiness"] == {
        "required_types": ["well_log", "seismic", "horizon"],
        "available_counts": {"well_log": 1, "seismic": 1, "horizon": 0},
        "missing_types": ["horizon"],
        "ready": False,
    }


def test_qc_warns_when_map_has_no_polygons():
    project = ProjectDocument.new("Demo")
    doc = PaleoMapDocument(name="ZJ2 Map", linked_target_horizon="ZJ2")
    project.paleomap_documents.append(doc)

    report = run_basic_qc(project, doc.id)

    assert report.status == "warning"
    assert report.issues[0]["rule"] == "facies_polygons_present"


def test_record_export_adds_artifact():
    project = ProjectDocument.new("Demo")

    artifact = record_export(project, "map_1", "exports/map.geojson", "geojson", ["pred_1"])

    assert project.export_artifacts == [artifact]
    assert artifact.format == "geojson"
    assert artifact.source_task_ids == ["pred_1"]


def test_infer_workflow_steps_from_project_evidence():
    project = ProjectDocument.new("Demo")
    assert infer_workflow_step_status(project, "data_check") == "pending"

    project.resources.append(
        ResourceItem(name="A1.Las", path="a.las", type="well_log", format="las")
    )
    project.factor_map_tasks.append(
        FactorMapTask(
            name="sand",
            target_horizon="H1",
            factor_type="sand",
            method="IDW",
            status="complete",
        )
    )
    project.prediction_tasks.append(PredictionTask(name="p1", status="complete"))
    project.paleomap_documents.append(
        PaleoMapDocument(name="M1", linked_target_horizon="H1")
    )
    record_export(project, "map_1", "exports/map.geojson", "geojson", [])

    steps = home_workflow_steps(project)
    by_type = {step.step_type: step.status for step in steps}
    assert by_type["data_check"] == "complete"
    assert by_type["factor_map"] == "complete"
    assert by_type["prediction"] == "complete"
    assert by_type["map_compile"] == "complete"
    assert by_type["export"] == "complete"
    assert by_type["qc"] == "pending"

    state = dashboard_state(project)
    assert state["workflow_complete_count"] == 5
    assert state["map_document_count"] == 1


def test_home_workflow_steps_sync_into_active_run():
    project = ProjectDocument.new("Demo")
    run = create_compilation_run(project, "Run", "ZJ2", "scheme")
    assert all(step.status == "pending" for step in run.workflow_steps)

    project.resources.append(
        ResourceItem(name="A1.Las", path="a.las", type="well_log", format="las")
    )
    steps = home_workflow_steps(project)
    assert steps[0].step_type == "data_check"
    assert steps[0].status == "complete"
    assert run.workflow_steps[0].status == "complete"


def test_home_workflow_steps_complete_clears_persisted_warning():
    """#668: recovered evidence must overwrite a sticky warning/failed flag."""
    project = ProjectDocument.new("Demo")
    run = create_compilation_run(project, "Run", "ZJ2", "scheme")
    data_step = next(s for s in run.workflow_steps if s.step_type == "data_check")
    data_step.status = "warning"
    project.resources.append(
        ResourceItem(name="A1.Las", path="a.las", type="well_log", format="las")
    )
    steps = home_workflow_steps(project)
    assert steps[0].step_type == "data_check"
    assert steps[0].status == "complete"
    assert data_step.status == "complete"


def test_home_workflow_steps_persists_failed_against_weak_overlay():
    """#668/#851: the sticky branch must keep a persisted failed step.

    Without any new evidence the inference says ``pending``; the sticky branch
    (service.py home_workflow_steps) must NOT downgrade the persisted ``failed``
    to the weaker pending/stale overlay — and fresh evidence must still promote
    it back to complete. This is the half of #668 the warning test never
    guarded: deleting the sticky branch leaves this test red.
    """
    project = ProjectDocument.new("Demo")
    run = create_compilation_run(project, "Run", "ZJ2", "scheme")
    data_step = next(s for s in run.workflow_steps if s.step_type == "data_check")
    data_step.status = "failed"

    # No new evidence: inference would say pending; failed must stay failed.
    steps = home_workflow_steps(project)
    assert steps[0].step_type == "data_check"
    assert steps[0].status == "failed"
    assert data_step.status == "failed"

    # Fresh evidence promotes the step back to complete.
    project.resources.append(
        ResourceItem(name="A1.Las", path="a.las", type="well_log", format="las")
    )
    steps = home_workflow_steps(project)
    assert steps[0].status == "complete"
    assert data_step.status == "complete"
