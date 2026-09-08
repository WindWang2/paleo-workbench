"""V7 §7 图层树呈现态集成测试（回退树状态列 + 组聚合 + 差分重载）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel
from paleo_workbench.ui.workstation.composite_document import CompositeDocument
from paleo_workbench.ui.workstation.layer_decorations import GroupPresentationSummary


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    return project


@pytest.fixture()
def document(qtbot, tmp_path):
    doc = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(doc)
    if doc.uses_native_stack:
        pytest.skip("桥环境（本组测试针对回退树面板）")
    return doc


def _add_layer_with_role(document, kind, role, name="图层"):
    layer = document.edit_controller.create_layer(name, kind)
    document.stage_controller.state.set_membership(LayerMembershipRecord(
        layer_id=str(layer.id), role=role,
    ))
    document.edit_controller.set_active_layer(str(layer.id))
    document._sync_action_state()
    return layer


def _row(document, layer_id):
    from PySide6.QtCore import Qt

    for row in range(document.layer_manager.tree.topLevelItemCount()):
        item = document.layer_manager.tree.topLevelItem(row)
        if str(item.data(0, Qt.ItemDataRole.UserRole)) == str(layer_id):
            return item
    return None


# ---------------------------------------------------------------------------
# 图层级装饰（goal §7 状态词汇）
# ---------------------------------------------------------------------------


def test_frozen_layer_shows_status_column_and_tooltip(document):
    layer = _add_layer_with_role(document, "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    document.stage_controller.state.set_maturity(
        f"phase1_draft:{layer.id}", "frozen")
    document._sync_action_state()
    item = _row(document, layer.id)
    assert item is not None
    assert "冻结" in item.text(1)
    assert "❄" in item.text(1)
    assert "冻结" in item.toolTip(0)


def test_stale_layer_shows_freshness_status(document):
    layer = _add_layer_with_role(document, "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    # 直接注入呈现态（新鲜度链路在 V6 测试已覆盖；此处验证树渲染）。
    from paleo_workbench.ui.workstation.layer_decorations import (
        presentation_state,
    )

    document.layer_manager.set_layer_decorations({
        str(layer.id): presentation_state(
            editing=True, session_undo_depth=2, freshness_status="stale",
        ),
    })
    item = _row(document, layer.id)
    # dirty 优先于 stale（未保存修改是更高优先级信号）。
    assert "未保存" in item.text(1)
    assert "未保存" in item.toolTip(0) and "已过期" in item.toolTip(0)


def test_clean_layer_has_empty_status(document):
    layer = _add_layer_with_role(document, "line", LayerRole.PROVENANCE_LINE)
    document._sync_action_state()
    item = _row(document, layer.id)
    assert item.text(1) == ""


def test_editing_session_marks_layer_dirty(document):
    layer = _add_layer_with_role(document, "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    document._on_command_requested("toggle_editing")
    document._sync_action_state()
    item = _row(document, layer.id)
    assert "编辑中" in item.text(1)


# ---------------------------------------------------------------------------
# 差分重载 + 状态保持（goal §7「阶段切换不破坏展开/滚动/选择」）
# ---------------------------------------------------------------------------


def test_snapshot_republish_keeps_tree_items_differential(document):
    layer = _add_layer_with_role(document, "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    first = _row(document, layer.id)
    # 同结构再发布：行对象应复用（差分），不清树。
    document.layer_manager._publish()
    second = _row(document, layer.id)
    assert first is second


def test_stage_switch_preserves_selection(document):
    layer_a = _add_layer_with_role(document, "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    layer_b = document.edit_controller.create_layer("第二层", "polygon")
    document.stage_controller.state.set_membership(LayerMembershipRecord(
        layer_id=str(layer_b.id), role=LayerRole.INTERPRETATION_ANNOTATION))
    document._sync_action_state()
    document.layer_manager.select_layer(str(layer_a.id))
    assert document.layer_manager.tree.currentItem() is _row(document, layer_a.id)
    document.stage_controller.set_stage("constraint_factor")
    document._sync_action_state()
    current = document.layer_manager.tree.currentItem()
    assert current is _row(document, layer_a.id), "阶段切换不得破坏树选择"


def test_scroll_position_preserved_across_republish(document):
    for index in range(8):
        document.edit_controller.create_layer(f"层{index}", "polygon")
    document._sync_action_state()
    scrollbar = document.layer_manager.tree.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())
    before = scrollbar.value()
    document.layer_manager._publish()
    assert scrollbar.value() == before


# ---------------------------------------------------------------------------
# 组聚合（goal §7 组级真实聚合）
# ---------------------------------------------------------------------------


def test_group_summary_includes_maturity_counts(document):
    layer = _add_layer_with_role(document, "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    document.stage_controller.state.set_maturity(
        f"phase1_draft:{layer.id}", "published")
    # 组聚合在组合同步（120ms debounce 的立即路径）后填充。
    document._sync_composition_now()
    summaries = {s.group_id: s for s in document._group_summaries()}
    gc = document.stage_controller.group_controller
    placement = gc.placement_of(str(layer.id))
    assert placement in summaries
    assert summaries[placement].published >= 1


def test_native_panel_group_summary_strip_without_bridge(qtbot):
    """原生面板无桥也可构造：组摘要行如实渲染（接口同构性）。"""
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.set_group_summaries([
        GroupPresentationSummary(
            group_id="phase2.factors", title="单因素", layers=6, stale=2, errors=1,
        ),
        GroupPresentationSummary(group_id="g2", title="干净组", layers=3),
    ])
    text = panel.group_status_label.text()
    assert "单因素" in text and "✕ 1" in text and "↻ 2" in text
    # 干净组不进问题摘要。
    panel.set_group_summaries([
        GroupPresentationSummary(group_id="g2", title="干净组", layers=3),
    ])
    assert "组状态正常" in panel.group_status_label.text()


def test_double_click_locate_emits_zoom_signal(document, qtbot):
    layer = _add_layer_with_role(document, "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    with qtbot.waitSignal(
        document.layer_manager.zoom_to_layer_requested, timeout=2000
    ) as blocker:
        item = _row(document, layer.id)
        document.layer_manager.tree.itemDoubleClicked.emit(item, 0)
    assert blocker.args == [str(layer.id)]
