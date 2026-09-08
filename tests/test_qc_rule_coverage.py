"""V8 M11 — QC rule coverage: evaluated vs skipped can never masquerade as
pass, and skipped rules surface at the publish gate."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.project.models import (
    PaleoMapDocument,
    ProjectDocument,
    ProjectMeta,
)
from paleo_workbench.workflow.map_qa_rules import extended_rule_coverage
from paleo_workbench.workflow.qc import BASIC_QC_RULES, run_map_qc


@pytest.fixture()
def project() -> ProjectDocument:
    doc = ProjectDocument(meta=ProjectMeta(name="m11"))
    doc.paleomap_documents.append(PaleoMapDocument(id="map1", name="M", linked_target_horizon="H1"))
    return doc


class TestRuleCoverage:
    def test_no_inputs_marks_rules_skipped_with_reasons(self):
        coverage = extended_rule_coverage()
        assert coverage["out_of_bound_feature"]["evaluated"] is False
        assert "map_extent" in coverage["out_of_bound_feature"]["reason"]
        assert coverage["low_confidence"]["evaluated"] is False
        assert coverage["export_fallback"]["evaluated"] is False
        assert coverage["crs_undeclared"]["evaluated"] is True

    def test_with_inputs_all_evaluated(self):
        coverage = extended_rule_coverage(
            map_extent=(0.0, 0.0, 1.0, 1.0),
            fusion_confidence={"mean": 0.8},
            export_report={"path": "x.pdf"},
        )
        assert all(entry["evaluated"] for entry in coverage.values())

    def test_report_carries_coverage(self, project):
        report = run_map_qc(project, "map1", bind_active_run=False)
        assert set(BASIC_QC_RULES).issubset(report.rule_status)
        assert report.rule_status["low_confidence"]["evaluated"] is False
        assert report.coverage["skipped"] >= 3
        assert report.coverage["evaluated"] >= len(BASIC_QC_RULES)
        # skipped rules emit no issues — the coverage map is the ONLY honest
        # signal that they never ran
        low_conf_issues = [
            i for i in report.issues if i.get("rule") == "low_confidence"
        ]
        assert low_conf_issues == []

    def test_full_inputs_report_has_no_skips(self, project):
        report = run_map_qc(
            project,
            "map1",
            map_extent=(0.0, 0.0, 1.0, 1.0),
            fusion_confidence={"mean": 0.9, "min": 0.9},
            export_report={"path": "x.pdf", "fallback_used": False},
            bind_active_run=False,
        )
        assert report.coverage["skipped"] == 0
        assert report.coverage["evaluated"] == len(report.rule_status)


class TestPublishGateSkippedVisibility:
    def test_publish_warns_on_skipped_rules(self, project):
        from paleo_workbench.workflow.map_product import (
            MapProductRecord,
            publish_map_product,
        )

        report = run_map_qc(project, "map1", bind_active_run=False)
        project.active_quality_report_id = report.id
        record = MapProductRecord(
            product_name="P1",
            factor_task_ids=[],
        )
        project.map_products.append(record)
        with pytest.raises(ValueError) as excinfo:
            publish_map_product(record, project, accept_warnings=False)
        message = str(excinfo.value)
        # the gate refuses via warnings when accept_warnings=False; skipped
        # QC coverage is among the named reasons
        assert "QC skipped" in message or "skipped" in message
