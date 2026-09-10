"""V9 — 统一 staleness 词汇 + lineage 期望 ops + 任务状态（CANCELLING/DEGRADED）。"""
from __future__ import annotations

import time

from paleo_workbench.runtime.task_scheduler import (
    TERMINAL_TASK_STATES,
    TaskScheduler,
    TaskSpec,
    TaskState,
)
from paleo_workbench.workflow.freshness import _LINEAGE_EXPECTED_OPS
from paleo_workbench.workflow.interpretation.staleness import (
    StalenessVerdict,
    VERDICT_IS_PROBLEM,
    evaluate_verdict,
    from_constraint_pin,
    from_run_freshness,
    from_workspace_status,
    propagate_to_products,
)
from paleo_workbench.workflow.recompute_plan import OPERATION_LABELS_ZH


# --------------------------------------------------------- verdict 词汇


def test_verdict_vocabulary_unknown_never_current():
    assert from_constraint_pin("unpinned") is StalenessVerdict.UNKNOWN
    assert from_constraint_pin("unknown") is StalenessVerdict.UNKNOWN
    assert from_constraint_pin("bogus") is StalenessVerdict.UNKNOWN  # 未知不猜
    assert from_constraint_pin("current") is StalenessVerdict.CURRENT
    assert from_constraint_pin("stale_content") is StalenessVerdict.STALE_CONTENT
    assert from_constraint_pin("stale_version") is StalenessVerdict.STALE_VERSION
    assert from_constraint_pin("missing") is StalenessVerdict.MISSING_INPUT


def test_workspace_and_run_adapters():
    assert from_workspace_status("current") is StalenessVerdict.CURRENT
    assert from_workspace_status("missing_input") is StalenessVerdict.MISSING_INPUT
    assert from_workspace_status("superseded") is StalenessVerdict.SUPERSEDED
    assert from_run_freshness("fresh") is StalenessVerdict.CURRENT
    assert from_run_freshness("running") is StalenessVerdict.UNKNOWN
    assert from_run_freshness("failed") is StalenessVerdict.UNKNOWN
    # UNKNOWN 是问题态（不可签发）。
    assert VERDICT_IS_PROBLEM[StalenessVerdict.UNKNOWN] is True
    assert VERDICT_IS_PROBLEM[StalenessVerdict.CURRENT] is False


def test_evaluate_verdict_unknown_for_missing_key():
    from paleo_workbench.project.models import ProjectDocument

    doc = ProjectDocument.new("t")
    verdict = evaluate_verdict(doc, "factor:nope")
    assert verdict.verdict is StalenessVerdict.UNKNOWN
    assert verdict.is_problem
    # 传播到产品：无产品 → 空表（不编造）。
    assert propagate_to_products(doc) == {}


# --------------------------------------------------------- lineage ops


def test_lineage_expected_ops_cover_v9_operations():
    for op in ("factor_fusion", "factor_fusion:confidence",
               "factor_fusion:variance", "constraint_commit",
               "map_product_assembly", "integrated_interpretation"):
        assert op in _LINEAGE_EXPECTED_OPS, op
        assert op in OPERATION_LABELS_ZH, op


# --------------------------------------------------------- 任务状态


def test_scheduler_degraded_terminal_state():
    scheduler = TaskScheduler(max_workers=1, work_root=None)
    try:
        handle = scheduler.submit(TaskSpec(
            callable=lambda ctx: {"registration": "failed"},
            kind="io",
            title="科学任务",
            degraded_when=lambda result: result.get("registration") != "ok",
        ))
        deadline = time.monotonic() + 10
        while handle.state not in TERMINAL_TASK_STATES and time.monotonic() < deadline:
            time.sleep(0.02)
        assert handle.state is TaskState.DEGRADED
        assert handle.state in TERMINAL_TASK_STATES
    finally:
        scheduler.shutdown()


def test_scheduler_done_when_not_degraded():
    scheduler = TaskScheduler(max_workers=1, work_root=None)
    try:
        handle = scheduler.submit(TaskSpec(
            callable=lambda ctx: {"registration": "ok"},
            degraded_when=lambda result: result.get("registration") != "ok",
        ))
        deadline = time.monotonic() + 10
        while handle.state not in TERMINAL_TASK_STATES and time.monotonic() < deadline:
            time.sleep(0.02)
        assert handle.state is TaskState.DONE
    finally:
        scheduler.shutdown()


def test_scheduler_cancelling_visible_then_cancelled():
    scheduler = TaskScheduler(max_workers=1, work_root=None)
    try:
        import threading

        started = threading.Event()

        def slow_task(ctx):
            started.set()
            ctx.sleep_interruptible(5.0)
            return "late"

        handle = scheduler.submit(TaskSpec(callable=slow_task, kind="io"))
        assert started.wait(5), "task never started"
        # 等待任务进入 RUNNING。
        deadline = time.monotonic() + 5
        while handle.state is not TaskState.RUNNING and time.monotonic() < deadline:
            time.sleep(0.01)
        assert scheduler.cancel(handle.task_id) is True
        assert handle.state is TaskState.CANCELLING  # 可见的取消等待期
        deadline = time.monotonic() + 10
        while handle.state not in TERMINAL_TASK_STATES and time.monotonic() < deadline:
            time.sleep(0.02)
        assert handle.state is TaskState.CANCELLED  # 晚到结果被丢弃
        assert handle.result in (None, "late")  # 不作为完成消费
    finally:
        scheduler.shutdown()
