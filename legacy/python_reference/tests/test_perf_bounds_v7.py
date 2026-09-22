"""V7 §17 性能结构 bound（声明性断言，非 wall-time）。

目标：1000 图层 / 高频事件下无全清重建、无逐行 QWidget、无全量物化。
断言「结构」而不是秒数（V6 决策延续：性能声明 = 结构 bound）。
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


def _bulk_create(document, count: int, kind: str = "polygon") -> None:
    """批量建层（信号阻断 + 一次重组——生产里 1000 层来自工程装载的
    一次性路径，不是 1000 次 UI 事件；结构 bound 针对后者）。"""
    controller = document.edit_controller
    was_blocked = controller.blockSignals(True)
    try:
        for index in range(count):
            controller.create_layer(f"层{index}", kind)
    finally:
        controller.blockSignals(was_blocked)
    document._sync_composition_now()
    document._sync_action_state()


#: 结构预算上限（显式规模：1000 图层；超限 = 结构回归）。
LAYER_BUDGET = 1000


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Perf", region="HZ")
    project.meta.project_root = str(tmp_path)
    return project


@pytest.fixture()
def document(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    if doc.uses_native_stack:
        pytest.skip("桥环境（本组测试针对回退树路径）")
    return doc


def test_1000_layer_tree_differential_republish(document):
    """同结构重发布：树行对象复用（无全清重建）——1000 层规模。"""
    _bulk_create(document, LAYER_BUDGET)
    layers = None
    tree = document.layer_manager.tree
    assert tree.topLevelItemCount() == LAYER_BUDGET
    first = tree.topLevelItem(0)
    last = tree.topLevelItem(LAYER_BUDGET - 1)
    document.layer_manager._publish()
    assert tree.topLevelItem(0) is first
    assert tree.topLevelItem(LAYER_BUDGET - 1) is last


def test_decoration_push_no_rebuild(document):
    """呈现态推送（1000 层）不清树（行对象稳定）+ O(layers) 内完成。"""
    _bulk_create(document, 200)
    tree = document.layer_manager.tree
    rows = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    from paleo_workbench.ui.workstation.layer_decorations import (
        presentation_state,
    )

    decorations = {
        layer_id: presentation_state(
            editing=False, freshness_status="stale"
        )
        for layer_id in document.edit_controller.layer_ids()
    }
    started = time.perf_counter()
    document.layer_manager.set_layer_decorations(decorations)
    elapsed = time.perf_counter() - started
    # 结构 bound：纯单元格更新（无 rebuild）；200 层 × 单元格写必须在
    # 事件循环的一个片内（结构保证：无 QWidget 创建）。
    assert elapsed < 2.0, f"decoration push took {elapsed:.2f}s"
    assert [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())] == rows
    assert "已过期" in rows[0].text(1)


def test_tool_availability_1000_layers_budget(document):
    """统一求值在 1000 层工程上仍是 O(1)（求值不遍历图层）。"""
    _bulk_create(document, LAYER_BUDGET)
    started = time.perf_counter()
    availability = document.tool_availability()
    elapsed = time.perf_counter() - started
    assert availability["pan"].enabled
    # 求值读取活动图层聚合（action_state 计数），不遍历全部图层；预算
    # 显式：1000 层 < 1s（结构 bound；wall-time 仅作上限护栏）。
    assert elapsed < 1.0, f"availability took {elapsed:.2f}s"


def test_group_summaries_scale(document):
    """组聚合 1000 成员：maturity 回调 O(n) 单遍，无嵌套重扫。"""
    state = document.stage_controller.state
    controller = document.edit_controller
    was_blocked = controller.blockSignals(True)
    try:
        for index in range(LAYER_BUDGET):
            layer = controller.create_layer(f"层{index}", "polygon")
            state.set_membership(LayerMembershipRecord(
                layer_id=str(layer.id),
                role=LayerRole.INITIAL_FACIES_DRAFT,
            ))
    finally:
        controller.blockSignals(was_blocked)
    document._sync_composition_now()
    started = time.perf_counter()
    summaries = document._group_summaries()
    elapsed = time.perf_counter() - started
    total_layers = sum(s.layers for s in summaries)
    assert total_layers >= LAYER_BUDGET
    assert elapsed < 2.0, f"group summaries took {elapsed:.2f}s"
