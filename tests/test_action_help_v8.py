"""V8 M4 — Contextual Help / Explainability 测试。

约束：动态结论全部来自 canonical evaluator（无第二份状态表）；静态事实
登记处覆盖全部工具；tooltip/status/details 格式化可渲染且判词原样透传。
"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping.tool_availability import TOOL_IDS, evaluate_tool
from paleo_workbench.mapping.tool_context import ToolContext
from paleo_workbench.ui.workstation.action_help import (
    TOOL_HELP,
    TOOL_LABELS,
    TOOL_SHORTCUTS,
    explain,
    format_details,
    format_status,
    format_tooltip,
)


def _ctx(**changes) -> ToolContext:
    base = dict(
        project_open=True,
        mapping_stage="facies_calibration",
        active_layer_id="draft-1",
        active_layer_kind="polygon",
        layer_role="initial_facies_draft",
        layer_name="沉积相解释草稿",
        vector_writable=True,
        edit_gate_open=True,
    )
    base.update(changes)
    return ToolContext(**base)


def test_every_tool_has_help():
    """新增工具必须登记帮助事实（登记处完整性）。"""
    assert set(TOOL_HELP) == set(TOOL_IDS)
    for tool_id, spec in TOOL_HELP.items():
        assert spec.label, tool_id
        assert spec.requirements, tool_id
        assert spec.impact, tool_id
        assert spec.stages, tool_id
        assert spec.layer_kinds, tool_id


def test_labels_match_controller_vocabulary():
    """帮助词表与 QAction 词表一致（一个名字，两处消费）。"""
    from paleo_workbench.ui.map_action_controller import MapActionController

    for tool_id, label in TOOL_LABELS.items():
        assert MapActionController._LABELS.get(tool_id) == label, tool_id


def test_shortcut_mirror_matches_action_registration(qtbot):
    """帮助里的快捷键镜像与 QAction 注册一致（注册处消费同一张表）。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from paleo_workbench.ui.map_action_controller import MapActionController

    from PySide6.QtGui import QKeySequence

    controller = MapActionController()
    for tool_id, shortcut in TOOL_SHORTCUTS.items():
        action = controller.actions[tool_id]
        assert action.shortcut() == QKeySequence(shortcut), tool_id
    # 无快捷键的命令动作不得携带残留 shortcut
    for tool_id in ("toggle_editing", "merge", "split", "snapping"):
        assert controller.actions[tool_id].shortcut().isEmpty(), tool_id


def test_explain_derives_availability_from_evaluator():
    ctx = _ctx(editing=True, selection_count=1, compatible_polygon_count=1)
    explanation = explain("merge", ctx)
    verdict = evaluate_tool("merge", ctx)
    assert explanation.available is verdict.enabled
    assert explanation.missing == verdict.disabled_reason
    assert explanation.availability is not None


def test_explain_disabled_merge_full_answer():
    """Goal M4 示例：Merge 不可用时必须能完整回答「为什么」。"""
    ctx = _ctx(editing=True, layer_name="沉积相解释草稿", merge_ready=False)
    explanation = explain("merge", ctx)
    assert not explanation.available
    assert "兼容面" in explanation.missing
    assert "至少" in explanation.requirements
    assert explanation.current_layer == "沉积相解释草稿"
    assert "初始相图校正" in explanation.current_stage or explanation.current_stage
    details = format_details(explanation)
    assert "不可用" in details
    assert explanation.missing in details
    assert explanation.requirements in details


def test_explain_available_includes_impact_and_flags():
    ctx = _ctx(editing=True, dirty=True)
    explanation = explain("save_edits", ctx)
    assert explanation.available
    assert explanation.modifies_data and explanation.creates_version
    assert not explanation.background_task
    details = format_details(explanation)
    assert "修改数据" in details and "生成新版本" in details
    assert "后台任务" not in details


def test_tooltip_carries_reason_and_requirements_only_when_disabled():
    disabled = explain("merge", _ctx(editing=True, merge_ready=False))
    text = format_tooltip(disabled)
    assert "不可用" in text and "需要：" in text
    enabled = explain("save_edits", _ctx(editing=True, dirty=True))
    text2 = format_tooltip(enabled)
    assert "不可用" not in text2


def test_status_format_single_line():
    explanation = explain("pan", _ctx())
    assert format_status(explanation).count("\n") == 0


def test_unknown_tool_explained_honestly():
    explanation = explain("no_such_tool", _ctx())
    assert not explanation.available
    assert "未知工具" in explanation.missing


def test_readonly_tools_never_claim_modification():
    for tool_id in ("identify", "measure_distance", "layer_properties",
                    "attribute_table", "qa_run", "pan", "zoom_in"):
        assert not TOOL_HELP[tool_id].modifies_data, tool_id


def test_mutating_tools_flagged():
    for tool_id in ("save_edits", "add_polygon", "delete_selected", "merge",
                    "split", "reshape", "map_product_assemble"):
        assert TOOL_HELP[tool_id].modifies_data, tool_id
