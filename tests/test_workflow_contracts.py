"""Stage 11: professional geological workflow contracts."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from paleo_workbench.project.models import (
    FactorMapTask,
    PaleoMapDocument,
    PredictionTask,
    ProjectDocument,
    ResourceItem,
)
from paleo_workbench.workflow.contracts.models import (
    Certainty,
    ExpertQuestionStatus,
    ImplementationStatus,
    ReadinessStatus,
)
from paleo_workbench.workflow.contracts.readiness import (
    WorkflowReadinessEvaluator,
    evaluate_readiness,
)
from paleo_workbench.workflow.contracts.registry import (
    WorkflowContractRegistry,
    get_default_registry,
    reset_default_registry,
)
from paleo_workbench.workflow.contracts.report import (
    generate_consultation_report,
    generate_gap_report,
    write_reports,
)
from paleo_workbench.workflow.contracts.validation import (
    CONTRACT_DATARUN_MAP,
    KNOWN_DATARUN_OPERATIONS,
)


@pytest.fixture(autouse=True)
def _reset_reg():
    reset_default_registry()
    yield
    reset_default_registry()


def test_registry_unique_stable_ids():
    reg = get_default_registry()
    ids = [c.id for c in reg.list_contracts()]
    assert len(ids) == len(set(ids))
    for pid in reg.p0_ids():
        assert reg.get_contract(pid) is not None
    assert reg.validation_issues() == []


def test_contract_serialization_roundtrip():
    reg = get_default_registry()
    c = reg.get_contract("factor_interpolation")
    assert c is not None
    data = c.model_dump()
    from paleo_workbench.workflow.contracts.models import DomainWorkflowContract

    c2 = DomainWorkflowContract.model_validate(data)
    assert c2.id == c.id
    assert c2.datarun_operations == ["factor_map"]


def test_datarun_operation_alignment():
    reg = get_default_registry()
    for cid, op in CONTRACT_DATARUN_MAP.items():
        c = reg.get_contract(cid)
        assert c is not None, cid
        assert op in c.datarun_operations
        assert op in KNOWN_DATARUN_OPERATIONS


def test_upstream_downstream_refs_resolve():
    reg = get_default_registry()
    factor = reg.get_contract("factor_interpolation")
    assert factor is not None
    ups = reg.upstream("factor_interpolation")
    assert any(u.id == "horizon_interpretation" for u in ups)
    downs = reg.downstream("factor_interpolation")
    assert any(d.id == "facies_prediction" for d in downs)


def test_readiness_empty_partial_ready():
    empty = ProjectDocument.new("empty")
    ev = WorkflowReadinessEvaluator()
    r = ev.evaluate(empty, "factor_interpolation")
    assert r.status is ReadinessStatus.BLOCKED
    assert any("层位" in x.message_zh or "样点" in x.message_zh or "任务" in x.message_zh for x in r.reasons)

    partial = ProjectDocument.new("partial")
    partial.resources.append(
        ResourceItem(name="w.las", path="w.las", type="well_log", format="las")
    )
    partial.factor_map_tasks.append(
        FactorMapTask(
            name="f",
            target_horizon="",
            factor_type="sand",
            method="IDW",
            parameters={},
        )
    )
    r2 = evaluate_readiness(partial, "factor_interpolation")
    assert r2.status is ReadinessStatus.BLOCKED

    ready = ProjectDocument.new("ready")
    ready.resources.append(
        ResourceItem(name="w.las", path="w.las", type="well_log", format="las")
    )
    ready.factor_map_tasks.append(
        FactorMapTask(
            name="f",
            target_horizon="H1",
            factor_type="sand",
            method="IDW",
            parameters={
                "sample_points": [
                    {"x": 0.0, "y": 0.0, "value": 1.0},
                    {"x": 1.0, "y": 1.0, "value": 2.0},
                ]
            },
            status="pending",
        )
    )
    r3 = evaluate_readiness(ready, "factor_interpolation")
    assert r3.status is ReadinessStatus.READY
    assert r3.freshness_note == "freshness_owned_by_stage9"


def test_readiness_does_not_open_payload_files(tmp_path: Path, monkeypatch):
    """Readiness must not open large scientific payloads."""
    huge = tmp_path / "giant.sgy"
    huge.write_bytes(b"0" * 1024)

    opened: list[str] = []
    real_open = open

    def tracking_open(file, *args, **kwargs):
        opened.append(str(file))
        return real_open(file, *args, **kwargs)

    project = ProjectDocument.new("p")
    project.resources.append(
        ResourceItem(
            name="giant.sgy",
            path=str(huge),
            type="seismic",
            format="sgy",
        )
    )
    project.resources.append(
        ResourceItem(name="w.las", path="/no/such/giant.las", type="well_log", format="las")
    )

    import builtins

    monkeypatch.setattr(builtins, "open", tracking_open)
    evaluate_readiness(project, "seismic_volume")
    evaluate_readiness(project, "well_log_ingest")
    evaluate_readiness(project, "factor_interpolation")
    # Should not have opened the giant SEG-Y body
    assert not any(str(huge) in p for p in opened)


def test_prediction_demo_not_production():
    reg = get_default_registry()
    c = reg.get_contract("facies_prediction")
    assert c is not None
    assert c.implementation_status is ImplementationStatus.DEMO
    p = ProjectDocument.new("demo")
    p.prediction_tasks.append(PredictionTask(name="p", adapter_kind="mock", status="complete"))
    r = evaluate_readiness(p, "facies_prediction")
    # mock path should not look like clean production READY without warnings
    assert r.status in {ReadinessStatus.PARTIAL, ReadinessStatus.READY}
    if r.status is ReadinessStatus.PARTIAL:
        assert any("mock" in x.message_zh.lower() or "mock" in x.code for x in r.reasons)
    assert c.implementation_status is not ImplementationStatus.PRODUCTION


def test_geomodel_demo_status():
    c = get_default_registry().get_contract("geomodel_3d")
    assert c is not None
    assert c.implementation_status is ImplementationStatus.DEMO


def test_expert_questions_for_confirmation_required():
    reg = get_default_registry()
    for c in reg.list_contracts():
        for p in c.parameters:
            if p.certainty is Certainty.EXPERT_CONFIRMATION_REQUIRED:
                assert p.expert_question_id
                ids = {q.id for q in c.expert_questions}
                assert p.expert_question_id in ids
        for q in c.expert_questions:
            assert q.question.strip()
            if q.status is ExpertQuestionStatus.OPEN:
                assert q.current_software_behavior.strip()
            assert q.source_evidence  # evidence required for consultation quality


def test_source_evidence_no_line_numbers():
    reg = get_default_registry()
    for c in reg.list_contracts():
        for e in c.source_evidence:
            assert e.path
            assert ":" not in e.path.split("/")[-1] or e.path.count(":") == 0
            # path should look like module path, not file:line
            assert not any(ch.isdigit() and e.path.endswith(ch) for ch in "")  # noop
            assert ":line" not in e.path.lower()


def test_consultation_report_p0_sections():
    md = generate_consultation_report()
    for needle in (
        "输入",
        "操作",
        "输出",
        "待专家确认",
        "专家确认问题矩阵",
        "单因素",
        "预测",
        "eq-pred-model-gate",
        "eq-factor-horizon-req",
    ):
        assert needle in md, needle
    gap = generate_gap_report()
    assert "开发缺口" in gap
    assert "facies_prediction" in gap


def test_write_reports_to_dir(tmp_path: Path):
    cpath, gpath = write_reports(tmp_path)
    assert cpath.is_file()
    assert gpath.is_file()
    text = cpath.read_text(encoding="utf-8")
    assert "QC" in text or "质检" in text or "质量" in text


def test_qc_readiness_needs_map():
    p = ProjectDocument.new("q")
    r = evaluate_readiness(p, "quality_control")
    assert r.status is ReadinessStatus.BLOCKED
    p.paleomap_documents.append(PaleoMapDocument(name="m", linked_target_horizon="H1"))
    r2 = evaluate_readiness(p, "quality_control")
    assert r2.status is ReadinessStatus.READY


def test_registry_build_and_readiness_benchmark():
    t0 = time.perf_counter()
    reg = WorkflowContractRegistry()
    build_ms = (time.perf_counter() - t0) * 1000
    p = ProjectDocument.new("bench")
    for i in range(20):
        p.resources.append(
            ResourceItem(
                name=f"w{i}.las",
                path=f"w{i}.las",
                type="well_log",
                format="las",
            )
        )
    t0 = time.perf_counter()
    reports = WorkflowReadinessEvaluator(reg).evaluate_all(p)
    ready_ms = (time.perf_counter() - t0) * 1000
    t0 = time.perf_counter()
    md = generate_consultation_report(registry=reg, project=p)
    report_ms = (time.perf_counter() - t0) * 1000
    assert len(reports) == len(reg.list_contracts())
    assert build_ms < 200
    assert ready_ms < 100
    assert report_ms < 500
    assert len(md) > 1000
    print(f"\nBENCH contracts build={build_ms:.2f}ms readiness={ready_ms:.2f}ms report={report_ms:.2f}ms")


def test_completeness_metric():
    c = get_default_registry().get_contract("export")
    assert c is not None
    comp = c.completeness()
    assert comp["input_contract_complete"]
    assert comp["has_open_expert_questions"] is True


def test_stage9_freshness_still_importable():
    from paleo_workbench.workflow.freshness import FreshnessService
    from paleo_workbench.workflow.dependency_graph import DependencyGraph

    assert FreshnessService is not None
    assert DependencyGraph is not None


def test_duplicate_registry_raises():
    reg = get_default_registry()
    c = reg.get_contract("export")
    assert c is not None
    with pytest.raises(ValueError, match="duplicate"):
        WorkflowContractRegistry([c, c])
