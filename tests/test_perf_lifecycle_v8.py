"""V8 M8 — 高频事件性能/生命周期结构预算（声明性断言 + 宽松 wall-time 上限）。

* extent pan/zoom 不做全量 tool/context recompute（执行路径结构断言）；
* tool availability 求值 10k/100k 线性比 + 每调用绝对预算（execution
  re-gate 每命令一次新鲜求值，必须便宜）；
* help（M4 explain）派生预算：45 工具全量解释保持在毫秒级；
* active layer switch 在大规模图层下有界；
* 重复命令分派不泄漏内部状态（lifecycle）。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from paleo_workbench.mapping.tool_availability import evaluate_all
from paleo_workbench.mapping.tool_context import ToolContext
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.action_help import explain, format_details
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("PerfV8", region="HZ")
    project.meta.project_root = str(tmp_path)
    return project


@pytest.fixture()
def document(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    if doc.uses_native_stack:
        pytest.skip("桥环境（本组测试针对回退路径）")
    return doc


# ---------------------------------------------------------------------------
# 求值预算（纯函数级）
# ---------------------------------------------------------------------------


def _busy_ctx() -> ToolContext:
    return ToolContext(
        project_open=True,
        mapping_stage="constraint_factor",
        active_layer_id="L1",
        active_layer_kind="line",
        layer_role="provenance_line",
        layer_name="物源线",
        editing=True,
        dirty=True,
        can_undo=True,
        selection_count=3,
        snapping_enabled=True,
        current_tool="add_line",
    )


def test_evaluate_all_linear_and_cheap():
    """2k vs 20k 线性比（<1.5x 于 10 倍规模）+ 每调用绝对预算。"""
    ctx = _busy_ctx()
    evaluate_all(ctx)  # warmup

    # 110k evaluations of the full 45-tool matrix exceeded the 45s per-test
    # ceiling on slow CI runners — the 10x linearity ratio and the 1ms
    # per-call budget are equally measurable at a tenth of the iterations.
    start = time.perf_counter()
    for _ in range(2_000):
        evaluate_all(ctx)
    t10k = time.perf_counter() - start

    start = time.perf_counter()
    for _ in range(20_000):
        evaluate_all(ctx)
    t100k = time.perf_counter() - start

    # 线性：20k/2k 时间比在 [8, 13]（允许抖动，排除超线性）。
    ratio = t100k / max(t10k, 1e-9)
    assert 8.0 <= ratio <= 13.0, f"超线性或异常快：ratio={ratio:.2f}"
    # 绝对：单次全工具面求值 < 1ms（re-gate 每命令一次的预算基础）。
    per_call_ms = (t100k / 20_000) * 1000
    assert per_call_ms < 1.0, f"per-call {per_call_ms:.3f}ms exceeds 1ms budget"


def test_explain_help_derivation_cheap():
    """45 工具全量 explain + 格式化保持在 50ms 内（tooltip 刷新路径）。"""
    ctx = _busy_ctx()
    tool_ids = list(evaluate_all(ctx))
    explain("merge", ctx)  # warmup
    start = time.perf_counter()
    for _ in range(20):
        for tool_id in tool_ids:
            explanation = explain(tool_id, ctx)
            format_details(explanation)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"45-tool explain+format x20 took {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# 高频事件结构断言（extent 变化不做全量 recompute）
# ---------------------------------------------------------------------------


def test_extent_change_no_full_recompute(document, qtbot):
    """extent pan/zoom 只做 checked 同步——不触发全量 tool_availability。"""
    calls = {"n": 0}
    original = document.tool_availability

    def counting():
        calls["n"] += 1
        return original()

    document.tool_availability = counting  # type: ignore[method-assign]
    try:
        before = calls["n"]
        document.canvas.set_extent((0.0, 0.0, 2.0, 2.0))
        qtbot.wait(50)
        document.canvas.set_extent((0.5, 0.5, 1.5, 1.5))
        qtbot.wait(50)
        after = calls["n"]
    finally:
        document.tool_availability = original  # type: ignore[method-assign]
    assert after - before == 0, (
        f"extent change triggered {after - before} full recompute(s) — "
        "pan/zoom must stay off the evaluator path (M8)")


def test_active_layer_switch_bounded_at_scale(document):
    """500 层规模下活动图层切换保持有界（<2s 总预算，结构上无全清重建）。"""
    controller = document.edit_controller
    was_blocked = controller.blockSignals(True)
    ids = []
    try:
        for index in range(500):
            layer = controller.create_layer(f"层{index}", "polygon")
            ids.append(str(layer.id))
    finally:
        controller.blockSignals(was_blocked)
    document._sync_composition_now()

    start = time.perf_counter()
    for layer_id in ids[:25]:
        controller.set_active_layer(layer_id)
        document._sync_action_state()
    elapsed = time.perf_counter() - start
    assert elapsed < 2.0, f"25 switches at 500 layers took {elapsed:.2f}s"


def test_repeated_command_dispatch_state_stable(document, qtbot):
    """重复命令分派（含 re-gate 新鲜求值）不增长内部状态、不抛错。"""
    availability_sizes = set()
    for _ in range(50):
        document._on_command_requested("refresh")
        availability_sizes.add(len(document._last_availability))
    assert len(availability_sizes) == 1, (
        f"availability dict size drifted: {availability_sizes}")


def test_help_texts_do_not_grow_actions(document):
    """tooltip 供给（M4）不改变 QAction 数量（呈现面恒定）。"""
    before = len(document.action_controller.actions)
    for _ in range(5):
        document._apply_tool_availability()
    assert len(document.action_controller.actions) == before
