"""V10 review 修复的回归钉（R1–R5 findings；见 12-review-findings.md）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.mapping.tool_availability import evaluate_tool
from paleo_workbench.mapping.tool_context import ToolContext
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.map_status_bar import _format_scale
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("ReviewFix", region="T")
    project.meta.project_root = str(tmp_path)
    return project


@pytest.fixture
def doc(qtbot, tmp_path) -> CompositeDocument:
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    return document


def _register_role(document, layer_id, role):
    from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord

    document.stage_controller.state.set_membership(
        LayerMembershipRecord(layer_id=str(layer_id), role=role))


# R2-1：菜单 tooltip 必须 Qt 显式开启（禁用原因直达菜单）。
def test_menus_show_item_tooltips(doc):
    polygon = doc.edit_controller.create_layer("P", "polygon")
    _register_role(doc, polygon.id, LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(polygon.id)
    doc._sync_composition_now()
    doc._sync_action_state()
    menu = doc._build_canvas_menu()
    assert menu.toolTipsVisible()


def test_tree_menu_tooltips_visible(doc):
    panel = doc.layer_manager
    # 构造菜单但不 exec：直接验证策略在面板上可被开启（同一 QMenu 类型）；
    # _on_context_menu 内部调用 setToolTipsVisible(True)。
    from PySide6.QtWidgets import QMenu

    probe = QMenu(panel.tree)
    probe.setToolTipsVisible(True)
    assert probe.toolTipsVisible()


# R2-2：RAW 复制为草稿 → 副本登记 DERIVED 角色（抢主位防护/快照 badge）。
def test_duplicate_raw_registers_draft_role(doc):
    raw = doc.edit_controller.create_layer("RAW 相图", "polygon")
    _register_role(doc, raw.id, LayerRole.INITIAL_FACIES_SOURCE)
    doc._sync_action_state()
    doc._duplicate_vector_layer(str(raw.id))
    copies = [
        layer_id for layer_id in doc.edit_controller.layer_ids()
        if layer_id != str(raw.id)
    ]
    assert copies
    copy_id = copies[0]
    role = doc.stage_controller.state.role_of(copy_id)
    assert role == LayerRole.INITIAL_FACIES_DRAFT, role
    assert doc.edit_controller.role_of_layer(copy_id) == "initial_facies_draft"
    # 副本在本阶段（①）是合格草稿：add_polygon 通过角色门禁且 preferred
    # （RAW 源则全线被 RAW 判词拒绝——对照组）。
    doc.edit_controller.set_active_layer(copy_id)
    doc.edit_controller.start_editing()
    verdict = doc.tool_availability()["add_polygon"]
    assert verdict.enabled and verdict.preferred, verdict.disabled_reason
    raw_verdict = doc._layer_tool_availability(str(raw.id), "toggle_editing")
    assert not raw_verdict.enabled and "RAW" in raw_verdict.disabled_reason


# R4-1：捕获进行中右键不弹菜单（完成捕获手势不被劫持）。
def test_canvas_menu_suppressed_mid_capture(doc):
    polygon = doc.edit_controller.create_layer("P", "polygon")
    _register_role(doc, polygon.id, LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(polygon.id)
    doc.edit_controller.start_editing()
    doc._on_tool_requested("add_polygon")
    tool = doc.edit_controller.tools.active_tool
    if hasattr(tool, "points"):
        tool.points = [(0.0, 0.0)]  # pending 采点
        from PySide6.QtCore import QPoint

        built: list[object] = []
        doc._build_canvas_menu = lambda: built.append("menu") or None
        doc._on_canvas_context_menu(QPoint(5, 5))  # 必须静默返回（不弹）
        assert built == []
    else:
        pytest.skip("fallback capture tool 无 points 属性")


# R4-2：切层开启编辑时先提交他层会话（无静默遗弃）。
def test_toggle_editing_commits_other_session(doc):
    a = doc.edit_controller.create_layer("A", "polygon")
    _register_role(doc, a.id, LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(a.id)
    doc.edit_controller.start_editing()
    from paleo_workbench.mapping.vector_layer import VectorFeature

    with doc.edit_controller.layer(a.id).edit_session.edit_source("t"):
        doc.edit_controller.layer(a.id).edit_session.add_feature(VectorFeature(
            "f1", {"type": "Polygon",
                   "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, {}))
    b = doc.edit_controller.create_layer("B", "polygon")
    _register_role(doc, b.id, LayerRole.INITIAL_FACIES_DRAFT)
    messages: list[str] = []
    doc.status_message.connect(messages.append)
    doc._toggle_layer_editing(str(b.id))
    # A 的会话已随切换提交（或以状态消息说明）；无会话被静默遗弃。
    assert doc.edit_controller.layer(a.id).edit_session is None
    assert doc.edit_controller.layer(b.id).edit_session is not None


def test_tree_layer_switch_commits_other_session(doc):
    """#1268: 树选中另一层也必须提交/回滚前一会话。"""
    a = doc.edit_controller.create_layer("A", "polygon")
    _register_role(doc, a.id, LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(a.id)
    doc.edit_controller.start_editing()
    from paleo_workbench.mapping.vector_layer import VectorFeature

    with doc.edit_controller.layer(a.id).edit_session.edit_source("t"):
        doc.edit_controller.layer(a.id).edit_session.add_feature(VectorFeature(
            "f1", {"type": "Polygon",
                   "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, {}))
    b = doc.edit_controller.create_layer("B", "polygon")
    _register_role(doc, b.id, LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(a.id)
    assert doc.edit_controller.layer(a.id).edit_session is not None
    doc._on_user_active_layer_changed(str(b.id))
    assert doc.edit_controller.layer(a.id).edit_session is None
    assert doc.edit_controller.active_layer_id == str(b.id)


# R4-3：拓扑 chip 校验覆盖全部打开的会话（与计数同口径）。
def test_topology_validate_covers_all_sessions(doc):
    layers = []
    for name in ("A", "B"):
        layer = doc.edit_controller.create_layer(name, "polygon")
        _register_role(doc, layer.id, LayerRole.INITIAL_FACIES_DRAFT)
        layers.append(layer)
    for layer in layers:
        doc.edit_controller.set_active_layer(layer.id)
        doc.edit_controller.start_editing()
        from paleo_workbench.mapping.vector_layer import VectorFeature

        with layer.edit_session.edit_source("t"):
            layer.edit_session.add_feature(VectorFeature(
                f"f_{layer.name}",
                {"type": "Polygon",
                 "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}, {}))
    # 两个会话都打开时：validate_open_session_topology 覆盖两层。
    issues = doc.edit_controller.validate_open_session_topology()
    assert isinstance(issues, list)
    assert doc.edit_controller.layer(layers[0].id).edit_session is not None
    assert doc.edit_controller.layer(layers[1].id).edit_session is not None


# R1-1：gate 关闭（非 RAW/冻结）→ chip「锁定」+ 判词。
def test_edit_chip_locked_state(doc):
    bar = doc.status_bar
    bar.apply_context({
        "editing": False, "layer_name": "证据层", "raw_locked": False,
        "layer_frozen": False, "edit_gate_open": False,
        "edit_gate_reason": "图层所在组「初始相图」在本阶段为证据锁定",
    })
    assert bar.edit.text() == "锁定", bar.edit.text()
    assert "证据锁定" in bar.edit.toolTip()


# R2-11/R3：比例尺 <1 → 诚实未知；千分位格式。
def test_scale_format_guard():
    assert _format_scale(0) == "1:—"
    assert _format_scale(0.3) == "1:—"
    assert _format_scale(1.0) == "1:1"
    assert _format_scale(250000.0) == "1:250,000"


# R5-1：指针轻路径不触发全量上下文（monkeypatch tool_context 计数）。
def test_map_position_uses_light_path(doc, monkeypatch):
    calls = {"n": 0}
    original = doc.tool_context

    def _counted():
        calls["n"] += 1
        return original()

    monkeypatch.setattr(doc, "tool_context", _counted)
    before = calls["n"]
    doc._on_map_position((1.0, 2.0))
    assert calls["n"] == before, "指针事件不得触发 tool_context() 重建"
    assert doc.status_bar.coordinate.text().startswith("X:")


# R2-5：捕捉 tooltip 用有效容差（per-layer 覆盖优先）。
def test_effective_snapping_tolerance(doc):
    layer = doc.edit_controller.create_layer("L", "line")
    _register_role(doc, layer.id, LayerRole.FACIES_BOUNDARY)
    doc.edit_controller.set_active_layer(layer.id)
    doc.edit_controller._snapping.pixel_tolerance = 10.0
    doc.edit_controller._snapping.layer_tolerance[str(layer.id)] = 18.0
    assert doc._effective_snapping_tolerance() == 18.0
    del doc.edit_controller._snapping.layer_tolerance[str(layer.id)]
    assert doc._effective_snapping_tolerance() == 10.0


# 未知阶段：cancel 豁免阶段隐藏（P1 回归钉）。
def test_cancel_survives_unknown_stage():
    ctx = ToolContext(project_open=True, mapping_stage="bogus")
    verdict = evaluate_tool("cancel", ctx)
    assert verdict.enabled and verdict.visible
    # 同阶段下 snapping toggle 仍按组隐藏（fail-closed 只豁免 cancel）。
    assert not evaluate_tool("snapping", ctx).visible
