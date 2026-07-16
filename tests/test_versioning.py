"""ISS-DOM-04: VersionSet expert finalization."""

from __future__ import annotations

from paleo_workbench.project.models import (
    CompilationRun,
    ContourDraft,
    ContourSegment,
    PaleoMapDocument,
    ProjectDocument,
    QualityReport,
)
from paleo_workbench.workflow.qc import run_basic_qc
from paleo_workbench.workflow.versioning import (
    active_final_snapshot,
    finalize_map_version,
    version_set_summary,
)


def test_finalize_creates_version_set_and_snapshot():
    project = ProjectDocument.new("V")
    project.compilation_runs.append(
        CompilationRun(name="run", target_horizon="C6", status="draft")
    )
    doc = PaleoMapDocument(
        name="C6 图",
        linked_target_horizon="C6",
        facies_polygons=[{"id": "f1", "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]]}],
        line_features=[{"id": "l1", "role": "contour", "coordinates": [[0, 0], [1, 1]]}],
    )
    project.paleomap_documents.append(doc)
    draft = ContourDraft(
        name="draft",
        target_horizon="C6",
        linked_map_document_id=doc.id,
        segments=[ContourSegment(level=1.0, coordinates=[[0, 0], [1, 1]])],
        status="editing",
    )
    doc.linked_contour_draft_id = draft.id
    project.contour_drafts.append(draft)
    run_basic_qc(project, doc.id)

    vset = finalize_map_version(project, doc.id, note="OK", operator="alice")
    assert vset.status == "final"
    assert vset.finalized_by == "alice"
    assert len(vset.snapshots) == 1
    snap = vset.snapshots[0]
    assert snap.map_document_id == doc.id
    assert snap.contour_draft_id == draft.id
    assert snap.facies_count == 1
    assert snap.line_feature_count == 1
    assert snap.contour_segment_count == 1
    assert snap.content_fingerprint
    assert draft.status == "final"
    assert project.compilation_runs[-1].status == "export_ready"
    assert active_final_snapshot(project, target_horizon="C6") is snap


def test_finalize_supersedes_previous_final():
    project = ProjectDocument.new("S")
    d1 = PaleoMapDocument(name="M1", linked_target_horizon="H1")
    d2 = PaleoMapDocument(name="M2", linked_target_horizon="H1")
    project.paleomap_documents.extend([d1, d2])
    finalize_map_version(project, d1.id, operator="a")
    finalize_map_version(project, d2.id, operator="b")
    finals = [vs for vs in project.version_sets if vs.status == "final"]
    superseded = [vs for vs in project.version_sets if vs.status == "superseded"]
    assert len(finals) == 1
    assert finals[0].snapshots[-1].map_document_id == d2.id
    assert len(superseded) >= 1


def test_require_qc_pass_blocks_without_report():
    project = ProjectDocument.new("Q")
    doc = PaleoMapDocument(name="M", linked_target_horizon="H")
    project.paleomap_documents.append(doc)
    try:
        finalize_map_version(project, doc.id, require_qc_pass=True)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "质检" in str(exc)


def test_version_set_summary_and_serialize():
    project = ProjectDocument.new("Sum")
    doc = PaleoMapDocument(name="M", linked_target_horizon="Z")
    project.paleomap_documents.append(doc)
    finalize_map_version(project, doc.id)
    summary = version_set_summary(project)
    assert summary["final_count"] == 1
    assert summary["latest_final_horizon"] == "Z"
    restored = ProjectDocument.model_validate(project.model_dump())
    assert restored.version_sets[0].status == "final"


def test_review_page_finalize_button(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from paleo_workbench.ui.pages.review_export_page import ReviewExportPage

    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **k: QMessageBox.StandardButton.Ok
    )
    project = ProjectDocument.new("UI")
    doc = PaleoMapDocument(
        name="图A",
        linked_target_horizon="H9",
        facies_polygons=[{"id": "f", "coordinates": [[0, 0], [1, 0], [0, 1], [0, 0]]}],
    )
    project.paleomap_documents.append(doc)
    page = ReviewExportPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state([], project.paleomap_documents, [])
    events = []
    page.version_finalized.connect(lambda: events.append(True))
    page.action_header.finalize_btn.click()
    assert events == [True]
    assert project.version_sets
    assert project.version_sets[-1].status == "final"
