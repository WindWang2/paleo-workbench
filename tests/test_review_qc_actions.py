"""T-QC-02: review page run QC + export report actions."""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument
from paleo_workbench.ui.pages.review_export_page import ReviewExportPage
from paleo_workbench.workflow.qc import run_basic_qc
from paleo_workbench.workflow.qc_report_export import export_quality_report_json


def test_export_quality_report_json_registers_artifact(tmp_path: Path):
    project = ProjectDocument.new("QC")
    doc = PaleoMapDocument(name="M", linked_target_horizon="H1")
    project.paleomap_documents.append(doc)
    report = run_basic_qc(project, doc.id)
    out = tmp_path / "qc.json"
    export_quality_report_json(report, out, project=project, register=True)
    assert out.exists()
    assert "facies_polygons_present" in out.read_text(encoding="utf-8")
    assert any(a.format == "qc_json" for a in project.export_artifacts)


def test_review_page_run_qc_creates_reports(qtbot, monkeypatch):
    project = ProjectDocument.new("RunQC")
    project.paleomap_documents.append(
        PaleoMapDocument(name="Empty Map", linked_target_horizon="")
    )
    page = ReviewExportPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state([], project.paleomap_documents, [])

    monkeypatch.setattr(
        "paleo_workbench.ui.pages.review_export_page.QMessageBox.information",
        lambda *a, **k: None,
    )
    page.run_qc()

    assert len(project.quality_reports) == 1
    assert project.quality_reports[0].status in {"warning", "error"}
    assert page.action_header.export_btn.isEnabled() is True


def test_app_review_page_wired(qtbot):
    project = ProjectDocument.new("AppQC")
    project.paleomap_documents.append(
        PaleoMapDocument(
            name="Map",
            linked_target_horizon="ZJ2",
            facies_polygons=[{"id": "f1", "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]]}],
        )
    )
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.review_export_page_widget()
    assert isinstance(page, ReviewExportPage)
    assert page._project is window.project


def test_export_quality_report_json_is_atomic_and_nan_free(tmp_path, monkeypatch):
    """ERR-5: failed export leaves the old file intact; NaN metrics serialize as null."""
    import json

    from paleo_workbench.project.models import QualityReport
    from paleo_workbench.workflow import qc_report_export

    out = tmp_path / "qc.json"
    report = QualityReport(
        linked_map_document_id="m1",
        issues=[{"metric": float("nan"), "score": float("inf"), "ok": 1.5}],
    )
    export_quality_report_json(report, out)
    parsed = json.loads(out.read_text(encoding="utf-8"), parse_constant=_reject_const)
    assert parsed["issues"][0]["metric"] is None
    assert parsed["issues"][0]["score"] is None

    # A write failure must leave the previously exported content untouched.
    before = out.read_text(encoding="utf-8")

    real_replace = Path.replace

    def failing_replace(self, target, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", failing_replace)
    try:
        export_quality_report_json(report, out)
    except OSError:
        pass
    else:
        raise AssertionError("expected OSError to propagate")
    monkeypatch.setattr(Path, "replace", real_replace)
    assert out.read_text(encoding="utf-8") == before
    assert not [p for p in tmp_path.iterdir() if p.name.startswith(".qc.json")]


def _reject_const(name):
    raise ValueError(f"non-standard JSON constant: {name}")
