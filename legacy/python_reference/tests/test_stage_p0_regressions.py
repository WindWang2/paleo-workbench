"""v7 P0 regressions: factor-task status vocabulary + MapProduct payload staging.

P0-1: ``FactorMapTask.status`` is written ``"complete"`` by the interpolation
authority; ``stage_actions``/``readiness`` historically compared ``"completed"``,
silently disabling factor overlays, evidence listing, and readiness checks.

P0-2: the workstation ``assemble_map_product`` action passed the ``.artifacts``
directory where the assembler requires a staged payload FILE, so Stage-3
assembly always failed; producers now stage via ``write_product_manifest``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from paleo_workbench.mapping_workspace.readiness import (
    check_evidence_available,
    check_factors_complete,
)
from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.project.models import (
    FACTOR_TASK_STATUS_COMPLETE,
    FactorMapTask,
    ProjectDocument,
)
from paleo_workbench.workflow.map_product import (
    assemble_map_product,
    write_product_manifest,
)

REPO = Path(__file__).resolve().parent.parent


def _task(status: str) -> FactorMapTask:
    return FactorMapTask(
        name="砂地比", target_horizon="T2", factor_type="sand_ratio", method="idw",
        status=status,
    )


def test_status_vocabulary_constants_are_the_single_authority():
    assert FACTOR_TASK_STATUS_COMPLETE == "complete"
    assert FactorMapTask(
        name="t", target_horizon="T", factor_type="f", method="idw",
    ).status == "pending"


def test_readiness_counts_complete_tasks():
    document = SimpleNamespace(factor_map_tasks=[_task("complete"), _task("pending")])
    item = check_factors_complete(document)
    assert item.check_id == "factors_complete"
    assert item.status.value == "warning"
    assert "1/2" in item.title

    document_all = SimpleNamespace(factor_map_tasks=[_task("complete")])
    assert check_factors_complete(document_all).status.value == "ok"
    evidence = check_evidence_available(document_all)
    assert evidence.status.value == "ok"


def test_no_completed_literal_drift_against_task_status():
    """Source guard: task-status readers must use the canonical constant."""
    patterns = [
        (REPO / "paleo_workbench/ui/workstation/stage_actions.py"),
        (REPO / "paleo_workbench/mapping_workspace/readiness.py"),
        (REPO / "paleo_workbench/workflow/map_qa_rules.py"),
    ]
    drift = re.compile(r'task[^=\n]*status[^=\n]*==\s*"completed"')
    for path in patterns:
        assert path.is_file(), path
        offenders = [
            (path.name, i + 1, line.strip())
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines())
            if drift.search(line)
        ]
        assert not offenders, (
            f"status vocabulary drift (use FACTOR_TASK_STATUS_COMPLETE): {offenders}"
        )


def test_stage2_readiness_profile_recognizes_complete_tasks():
    document = SimpleNamespace(
        factor_map_tasks=[_task("complete")],
        constraint_layers=[],
    )
    from paleo_workbench.mapping_workspace.readiness import evaluate_stage_readiness

    readiness = evaluate_stage_readiness(MappingStage.CONSTRAINT_FACTOR, document)
    by_id = {item.check_id: item for item in readiness.items}
    assert by_id["factors_complete"].status.value == "ok"

    readiness3 = evaluate_stage_readiness(
        MappingStage.INTEGRATED_COMPILATION, document)
    by_id3 = {item.check_id: item for item in readiness3.items}
    if "evidence_available" in by_id3:
        assert by_id3["evidence_available"].status.value == "ok"


# ---------------------------------------------------------------------------
# P0-2 — payload staging


def _document_with_real_factor(tmp_path: Path) -> tuple[ProjectDocument, FactorMapTask]:
    task = FactorMapTask(
        name="砂地比", target_horizon="T2", factor_type="sand_ratio", method="idw",
        status=FACTOR_TASK_STATUS_COMPLETE, source_kind="real",
        grid_artifact_version_id="ver-1", grid_artifact_path="g.npz",
    )
    from paleo_workbench.project.models import ProjectMeta

    document = ProjectDocument(id="p1", name="X", meta=ProjectMeta(name="X"))
    document.factor_map_tasks.append(task)
    return document, task


def test_write_product_manifest_stages_a_file(tmp_path):
    document, task = _document_with_real_factor(tmp_path)
    staged = write_product_manifest(
        document, product_name="综合编图 X", factor_task_ids=[str(task.id)],
    )
    try:
        assert staged.is_file()
        manifest = json.loads(staged.read_text(encoding="utf-8"))
        assert manifest["product_name"] == "综合编图 X"
        assert manifest["factor_tasks"][0]["grid_version"] == "ver-1"
        assert manifest["factor_tasks"][0]["id"] == str(task.id)
    finally:
        staged.unlink(missing_ok=True)


def test_assemble_refuses_directory_payload(tmp_path):
    """Documents the contract the v5 wiring violated."""
    document, task = _document_with_real_factor(tmp_path)
    from paleo_workbench.workflow.map_product import MapProductAssembly

    with pytest.raises(ValueError, match="requires the data catalog"):
        assemble_map_product(
            document,
            assembly=MapProductAssembly(
                product_name="p", factor_task_ids=[str(task.id)]),
            catalog=None,
            payload_path=tmp_path,
        )
    # With a catalog present the directory payload must still be refused
    # (fail-closed), never silently treated as an empty product.
    with pytest.raises(ValueError, match="staged payload file"):
        assemble_map_product(
            document,
            assembly=MapProductAssembly(
                product_name="p", factor_task_ids=[str(task.id)]),
            catalog=object(),  # non-None stands in for a live catalog
            payload_path=tmp_path,
        )


def test_stage_action_sources_use_manifest_helper():
    """The workstation action must not re-stage directories."""
    source = (
        REPO / "paleo_workbench" / "ui" / "workstation" / "stage_actions.py"
    ).read_text(encoding="utf-8")
    assert ".artifacts" not in source, (
        "stage action must not pass the .artifacts directory as payload"
    )
    assert "write_product_manifest" in source
