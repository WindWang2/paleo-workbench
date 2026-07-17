"""T-QC-01 / ISS-QC-01: QC upsert + expanded rule set."""

from __future__ import annotations

from paleo_workbench.project.models import (
    PaleoMapDocument,
    ProjectDocument,
    WellTable,
    WellTableRow,
)
from paleo_workbench.workflow.qc import (
    BASIC_QC_RULES,
    active_quality_reports,
    run_basic_qc,
)
from paleo_workbench.workflow.service import create_compilation_run, dashboard_state


def test_run_basic_qc_upserts_same_map():
    project = ProjectDocument.new("QC")
    create_compilation_run(project, "Run", "H1", "scheme")
    doc = PaleoMapDocument(name="M", linked_target_horizon="")
    project.paleomap_documents.append(doc)

    r1 = run_basic_qc(project, doc.id)
    r2 = run_basic_qc(project, doc.id)
    assert len(project.quality_reports) == 1
    assert r1.id == r2.id
    assert project.compilation_runs[-1].active_quality_report_id == r2.id
    assert set(r2.rules) == set(BASIC_QC_RULES)


def test_dashboard_qc_count_uses_active_not_all_history():
    project = ProjectDocument.new("QC")
    create_compilation_run(project, "Run", "H1", "scheme")
    doc = PaleoMapDocument(name="M", linked_target_horizon="H1")
    project.paleomap_documents.append(doc)
    # Incomplete map → multiple warnings (facies, wells, contour)
    run_basic_qc(project, doc.id)
    state1 = dashboard_state(project)
    assert state1["qc_issue_count"] >= 1
    # Re-run still 1 report / same count (no inflation)
    run_basic_qc(project, doc.id)
    state2 = dashboard_state(project)
    assert state2["qc_issue_count"] == state1["qc_issue_count"]
    assert len(active_quality_reports(project)) == 1


def test_pass_when_map_complete():
    project = ProjectDocument.new("QC")
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H1",
        facies_polygons=[{
            "id": "f1",
            "coordinates": [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
        }],
        well_overlays=[{"id": "w1", "name": "A1", "x": 0.5, "y": 0.5}],
        line_features=[{
            "id": "c1",
            "role": "contour",
            "coordinates": [[0, 0.5], [1, 0.5]],
            "properties": {"role": "contour", "level": 1.0},
        }],
    )
    project.paleomap_documents.append(doc)
    report = run_basic_qc(project, doc.id)
    assert report.status == "pass"
    assert report.issues == []


def test_facies_geometry_self_intersection_is_error():
    project = ProjectDocument.new("QC-Geom")
    # Bow-tie self-intersecting quad
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H1",
        facies_polygons=[{
            "id": "f_bad",
            "coordinates": [[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]],
        }],
        well_overlays=[{"id": "w1", "x": 0.2, "y": 0.2}],
        line_features=[{"id": "c1", "role": "contour", "coordinates": [[0, 0], [1, 0]]}],
    )
    project.paleomap_documents.append(doc)
    report = run_basic_qc(project, doc.id)
    rules = {i["rule"] for i in report.issues}
    assert "facies_geometry_valid" in rules
    assert report.status == "error"


def test_well_table_flags_raise_warning():
    project = ProjectDocument.new("QC-WT")
    project.well_tables.append(
        WellTable(
            name="t",
            target_horizon="H1",
            rows=[
                WellTableRow(name="A", x=0, y=0, z=1.0, qc_flag="ok"),
                WellTableRow(name="B", x=1, y=0, z=100.0, qc_flag="outlier"),
            ],
        )
    )
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H1",
        facies_polygons=[{
            "id": "f1",
            "coordinates": [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
        }],
        well_overlays=[{"id": "w1", "x": 0, "y": 0}],
        line_features=[{"id": "c1", "role": "contour", "coordinates": [[0, 0], [1, 1]]}],
    )
    project.paleomap_documents.append(doc)
    report = run_basic_qc(project, doc.id)
    by_rule = {i["rule"]: i for i in report.issues}
    assert "well_table_qc_clean" in by_rule
    assert by_rule["well_table_qc_clean"]["severity"] == "warning"
    assert report.status == "warning"


def test_missing_horizon_is_error():
    project = ProjectDocument.new("QC-H")
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="",
        facies_polygons=[{
            "id": "f1",
            "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]],
        }],
    )
    project.paleomap_documents.append(doc)
    report = run_basic_qc(project, doc.id)
    assert any(i["rule"] == "target_horizon_present" for i in report.issues)
    assert report.status == "error"
