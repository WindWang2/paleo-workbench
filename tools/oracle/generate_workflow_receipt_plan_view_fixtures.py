#!/usr/bin/env python3
"""Oracle fixture generator for the CONV-32 receipt + plan_view C++ port.

Imports the REAL implementations (paleo_workbench.workflow.dag.receipt /
plan_view / model) and freezes their outputs to JSON so the C++ side in
libs/workflow_engine (src/receipt.cpp, src/plan_view.cpp) can be verified
against the Python chain. Regenerate with:

    python3 tools/oracle/generate_workflow_receipt_plan_view_fixtures.py

Determinism: the two injected seams of dag/receipt.py are monkeypatched to
frozen values — environment_identity() and time.time() — so every frozen
byte is reproducible on any machine. ActionResult fakes are built with
types.SimpleNamespace (the same projection the C++ ActionResultView
models). No numpy needed; run from the worktree root.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import paleo_workbench  # noqa: E402

assert str(paleo_workbench.__file__).startswith(str(REPO_ROOT)), (
    f"paleo_workbench resolved from {paleo_workbench.__file__}, "
    f"not this worktree ({REPO_ROOT}) — oracle must import the real tree"
)

from paleo_workbench.workflow.dag import plan_view as PV  # noqa: E402
from paleo_workbench.workflow.dag import receipt as R  # noqa: E402
from paleo_workbench.workflow.dag.model import (  # noqa: E402
    NodeRun,
    NodeSpec,
    NodeState,
    RunState,
    WorkflowRun,
    WorkflowSpec,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "workflow_engine"
    / "workflow_engine_tests"
    / "fixtures"
)

# Frozen environment seam (receipt.environment_identity) + clock seam
# (receipt.time.time). The C++ side injects the same values through
# EnvironmentProvider / Clock; parity is structural, not machine-equal.
FROZEN_ENV = {
    "python": "3.11.9",
    "platform": "Linux-6.9.0-x86_64",
    "workbench": "8.0.0",
}
FROZEN_NOW = 1700000000.0

R.environment_identity = lambda: dict(FROZEN_ENV)
R.time.time = lambda: FROZEN_NOW


def fake_result(**overrides) -> types.SimpleNamespace:
    """harness.executor.ActionResult projection consumed by build_receipt."""
    base = dict(
        status="success",
        outputs={},
        verification={},
        warnings=[],
        metrics={},
        error=None,
        elapsed_ms=0.0,
    )
    base.update(overrides)
    return types.SimpleNamespace(**base)


def build(result: types.SimpleNamespace, **kwargs) -> dict:
    """build_receipt + to_dict with the required kwargs defaulted minimal."""
    args = dict(
        node_id=None,
        workflow_run_id=None,
        action_id="",
        action_version="",
        description="",
        parameters={},
        input_version_ids=(),
    )
    args.update(kwargs)
    return R.build_receipt(result, **args).to_dict()


# ------------------------------------------------------------------ specs --

SPEC = WorkflowSpec(
    workflow_id="wf.litho",
    name="岩性制图",
    nodes=(
        NodeSpec(node_id="a", action_id="qc.validate_inputs",
                 description="输入检查"),
        NodeSpec(node_id="b", action_id="map.interpolate_idw",
                 description="插值", depends_on=("a",)),
        NodeSpec(node_id="c", action_id="map.render_composition",
                 description="编图", depends_on=("b",)),
    ),
)

SPEC8 = WorkflowSpec(
    workflow_id="wf.litho8",
    name="岩性制图",
    nodes=(
        NodeSpec(node_id="a", action_id="qc.validate_inputs",
                 description="输入检查"),
        NodeSpec(node_id="b", action_id="map.interpolate_idw",
                 description="插值", depends_on=("a",)),
        NodeSpec(node_id="c", action_id="qc.check_condition",
                 description="质检", depends_on=("a",)),
        NodeSpec(node_id="d", action_id="io.export_map",
                 description="导出", depends_on=("b",)),
    ),
)


def make_run(spec: WorkflowSpec, state: RunState,
             node_runs: dict) -> WorkflowRun:
    return WorkflowRun(run_id="run-0", workflow=spec, state=state,
                       node_runs=node_runs)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # Determinism self-check: both seams must be in force for every case.
    probe = R.build_receipt(
        fake_result(), node_id=None, workflow_run_id=None, action_id="",
        action_version="", description="", parameters={},
        input_version_ids=())
    assert probe.environment == FROZEN_ENV, "environment seam not frozen"
    assert probe.finished_at == FROZEN_NOW, "clock seam not frozen"

    # 1 — succeeded node, full to_dict (provenance, qc_metrics, summary,
    # unrounded duration_ms -> round(x, 3) half-to-even at the edge).
    case1 = build(
        fake_result(
            outputs={"count": 3, "path": "/tmp/x", "flag": True,
                     "none": None},
            metrics={"provenance": {"provider_id": "contour",
                                    "provider_version": "2.1",
                                    "run_id": "cat-7"},
                     "rows": 42},
            verification={"checks": 2, "passed": 2},
            elapsed_ms=1234.5678,
        ),
        node_id="interp",
        workflow_run_id="run-42",
        action_id="map.interpolate_idw",
        action_version="1.2.0",
        description="克里金插值",
        parameters={"method": "idw", "power": 2.0},
        input_version_ids=("dv-a", "dv-b"),
        estimated_resources={"cpu_seconds": 1.5},
        resource_category="compute",
        started_at=1699999999.5,
    )

    # 2 — degraded: "; ".join(warnings) or "verification warnings".
    case2 = {
        "with_warnings": build(
            fake_result(status="degraded",
                        warnings=["低精度插值", "边缘裁剪"],
                        elapsed_ms=10.0),
            node_id="n2", action_id="qc.check", action_version="0.3",
            description="质检",
        ),
        "empty_warnings": {
            "degraded_reason": build(
                fake_result(status="degraded", warnings=[]))["degraded_reason"],
            "status": "degraded",
        },
    }

    # 3 — empty outputs.
    empty = build(fake_result(elapsed_ms=0.5), node_id="n")
    case3 = {
        "outputs_summary": empty["outputs_summary"],
        "output_version_ids": empty["output_version_ids"],
    }

    # 4 — version id collection: dedupe keep-first, encounter order
    # artifacts -> version_ids -> singular. A plain-string artifact version
    # does NOT count (no version_id attribute).
    case4 = list(R._collect_output_version_ids(fake_result(outputs={
        "artifacts": [{"version": {"version_id": "v1"}},
                      {"version": "v1"},
                      {"version": {"version_id": "v2"}}],
        "version_ids": ["v2", "v3"],
        "version_id": "v4",
    })))

    # 5 — output redaction: artifact_count / "<N keys>" / "<N items>" /
    # scalars / the four "<in-process handle>" keys (any value type).
    case5 = {
        "redaction": R._summarize_outputs(
            {"artifacts": [1, 2, 3, 4, 5], "rows": {"a": 1, "b": 2},
             "flag": True}),
        "in_process_handles": R._summarize_outputs(
            {"values": [1, 2], "map_document": {"z": 1}, "document": "doc",
             "composition": 7}),
        "arrays_and_scalars": R._summarize_outputs(
            {"stops": [1, 2, 3], "ratio": 0.25, "empty": "", "zero": 0,
             "none": None, "txt": "ok"}),
    }

    # 6 — from_dict: round-trip of case 1, {} defaults, null tolerance
    # (str(None) == "None" for action_id/status; `x or {}` for dicts; the
    # optional passthroughs stay None). duration_ms/attempt nulls are NOT
    # frozen here: Python float(None)/int(None) raise.
    case6 = {
        "roundtrip": R.ExecutionReceipt.from_dict(case1).to_dict(),
        "defaults": R.ExecutionReceipt.from_dict({}).to_dict(),
        "null_tolerance": R.ExecutionReceipt.from_dict({
            "node_id": None, "workflow_run_id": None,
            "provider_id": None, "provider_version": None,
            "resource_category": None, "parameters": None,
            "estimated_resources": None, "input_version_ids": None,
            "output_version_ids": None, "outputs_summary": None,
            "verification": None, "qc_metrics": None, "warnings": None,
            "started_at": None, "finished_at": None,
            "degraded_reason": None, "error": None,
            "cache_identity": None, "environment": None,
            "action_id": None, "status": None,
        }).to_dict(),
    }

    # 7 — plan view mixed run: succeeded/running/pending -> ✓●○,
    # progress 0.333, current_node 插值, running row detail "33%".
    run7 = make_run(SPEC, RunState.RUNNING, {
        "a": NodeRun(node_id="a", state=NodeState.SUCCEEDED,
                     receipt={"status": "degraded"}),
        "b": NodeRun(node_id="b", state=NodeState.RUNNING),
        "c": NodeRun(node_id="c", state=NodeState.PENDING),
    })
    case7 = {
        "from_run": PV.WorkflowPlanView.from_run(run7).to_dict(),
        "from_spec": PV.WorkflowPlanView.from_spec(SPEC).to_dict(),
    }

    # 8 — checklist edges: skipped (condition false) vs skipped (upstream
    # failed) details verbatim; from_cache row; failed run label.
    run8 = make_run(SPEC8, RunState.FAILED, {
        "a": NodeRun(node_id="a", state=NodeState.SUCCEEDED,
                     from_cache=True, receipt={"status": "success"}),
        "b": NodeRun(node_id="b", state=NodeState.FAILED, error="插值失败"),
        "c": NodeRun(node_id="c", state=NodeState.SKIPPED,
                     skip_reason="条件未满足"),
        "d": NodeRun(node_id="d", state=NodeState.SKIPPED,
                     skip_reason="upstream b failed"),
    })
    case8 = PV.WorkflowPlanView.from_run(run8).to_dict()

    # 9 — from_summary: spec ordering + description-only labels + extra
    # summary node dropped when the spec is given; nodes-map insertion
    # order + info-label fallback without a spec; interrupted label.
    summary = {
        "workflow_id": "wf.litho",
        "name": "岩性制图",
        "state": "interrupted",
        "progress": 0.5,
        "nodes": {
            "a": {"state": "succeeded", "from_cache": True,
                  "receipt_status": "success"},
            "b": {"state": "running", "label": "自定义标签"},
            "x": {"state": "pending", "label": "幽灵节点"},
        },
    }
    case9 = {
        "with_spec": PV.WorkflowPlanView.from_summary(summary, spec=SPEC).to_dict(),
        "without_spec": PV.WorkflowPlanView.from_summary(summary).to_dict(),
    }

    # 10 — ordering restore: node_runs inserted REVERSED; update_from_run
    # stable-sorts items back to spec node order (a, b, c).
    run10 = make_run(SPEC, RunState.RUNNING, {
        "c": NodeRun(node_id="c", state=NodeState.SUCCEEDED),
        "b": NodeRun(node_id="b", state=NodeState.RUNNING),
        "a": NodeRun(node_id="a", state=NodeState.SUCCEEDED),
    })
    case10 = PV.WorkflowPlanView.from_run(run10).to_dict()

    # 11 — empty spec: progress 0.0, no items, current_node None.
    empty_spec = WorkflowSpec(workflow_id="wf.empty", name="空工作流", nodes=())
    case11 = PV.WorkflowPlanView.from_spec(empty_spec).to_dict()

    # 12 — run-state labels; unknown raw states RAISE in Python
    # (RunState("paused") ValueError) — the C++ view returns the raw
    # string instead (graceful panel contract), so the graceful value is
    # the raw state, recorded beside the frozen Python error text.
    case12 = {
        "labels": {
            state: PV.WorkflowPlanView(
                workflow_id="w", name="n", state=state).state_label()
            for state in ("running", "completed", "failed", "cancelled",
                          "interrupted")
        },
        "unknown_state": {"python_raises": None, "graceful": "paused"},
    }
    try:
        PV.WorkflowPlanView(workflow_id="w", name="n",
                            state="paused").state_label()
    except ValueError as exc:
        case12["unknown_state"]["python_raises"] = f"ValueError: {exc}"

    # 13 — node-state symbol map (declared order), full PlanItem dicts.
    case13 = {
        state.value: PV.PlanItem(node_id="n", label="行", state=state).to_dict()
        for state in NodeState
    }

    doc = {
        "frozen_environment": FROZEN_ENV,
        "succeeded_to_dict": case1,
        "degraded": case2,
        "empty_outputs": case3,
        "version_ids_dedupe": case4,
        "summarize": case5,
        "from_dict": case6,
        "plan_mixed_run": case7,
        "checklist_edges": case8,
        "from_summary": case9,
        "ordering_restore": case10,
        "empty_spec": case11,
        "state_labels": case12,
        "symbols": case13,
    }
    target = OUT / "workflow_receipt_plan_view_oracle.json"
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    print(f"wrote {target} ({target.stat().st_size} bytes, "
          f"{len(doc)} top-level case groups)")


if __name__ == "__main__":
    main()
