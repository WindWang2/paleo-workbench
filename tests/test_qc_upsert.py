"""T-QC-01: QC upsert + dashboard issue counts do not inflate."""

from __future__ import annotations

from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument
from paleo_workbench.workflow.qc import active_quality_reports, run_basic_qc
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


def test_dashboard_qc_count_uses_active_not_all_history():
    project = ProjectDocument.new("QC")
    create_compilation_run(project, "Run", "H1", "scheme")
    doc = PaleoMapDocument(name="M", linked_target_horizon="H1")
    project.paleomap_documents.append(doc)
    # First run: no polygons → 1 warning
    run_basic_qc(project, doc.id)
    state1 = dashboard_state(project)
    assert state1["qc_issue_count"] == 1
    # Re-run still 1 report / same count
    run_basic_qc(project, doc.id)
    state2 = dashboard_state(project)
    assert state2["qc_issue_count"] == 1
    assert len(active_quality_reports(project)) == 1


def test_pass_when_map_complete():
    project = ProjectDocument.new("QC")
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H1",
        facies_polygons=[{"id": "f1", "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]]}],
    )
    project.paleomap_documents.append(doc)
    report = run_basic_qc(project, doc.id)
    assert report.status == "pass"
    assert report.issues == []
