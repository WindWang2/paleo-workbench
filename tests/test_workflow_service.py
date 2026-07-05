from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument, ResourceItem
from paleo_workbench.workflow.export import record_export
from paleo_workbench.workflow.qc import run_basic_qc
from paleo_workbench.workflow.service import create_compilation_run, dashboard_state


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
