"""V10 对抗性交互：乱序操作不崩溃、不错执、不静默失败（Goal §29）。

每条用例都对应一类真实用户的乱操作：快速切换、编辑中删层、捕获中关
工程、backend 失效后点原生工具、配置窗口开着删层……断言三件事：
不抛异常（qtbot 兜底）、状态机不漂移（evaluator = QAction 面）、
被拒动作有可读原因（不静默）。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.mapping_workspace.stages import MappingStage
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.composite_document import CompositeDocument


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Adv", region="T")
    project.meta.project_root = str(tmp_path)
    return project


@pytest.fixture
def doc(qtbot, tmp_path) -> CompositeDocument:
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    return document


@pytest.fixture
def fallback_doc(qtbot, tmp_path, monkeypatch) -> CompositeDocument:
    """回退画布文档（后端缺失的机器形态；本机桥在场需显式制造失败）。"""
    from paleo_workbench.ui.workstation import composite_document as cd

    class _NoBridgeShim(cd.QgisCanvasShim):
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("桥不可用（测试强制回退画布）")

    monkeypatch.setattr(cd, "QgisCanvasShim", _NoBridgeShim)
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    return document


def _add_layer(document, name, kind, role) -> str:
    layer = document.edit_controller.create_layer(name, kind)
    from paleo_workbench.mapping_workspace.stage_state import LayerMembershipRecord

    document.stage_controller.state.set_membership(
        LayerMembershipRecord(layer_id=str(layer.id), role=role))
    return str(layer.id)


def _messages(document) -> list[str]:
    log: list[str] = []
    document.status_message.connect(log.append)
    return log


def test_rapid_layer_switching_20x(doc):
    """快速切换 20 次图层：可用性面即时跟随，无漂移无崩溃。"""
    ids = [_add_layer(doc, f"L{i}", "line" if i % 2 else "polygon",
                      LayerRole.FACIES_BOUNDARY if i % 2 else LayerRole.INITIAL_FACIES_DRAFT)
           for i in range(20)]
    for layer_id in ids * 2:  # 40 次切换
        doc.edit_controller.set_active_layer(layer_id)
    doc._sync_action_state()
    availability = doc.tool_availability()
    # 阶段①语义：add_polygon 受治理（草稿角色允许）；add_line 是②阶段动作
    # 在①整条隐藏（阶段判词）。无会话时可见者因「需要先开始编辑」禁用。
    for tool_id in ("add_line", "add_polygon"):
        verdict = availability[tool_id]
        assert not verdict.enabled
        assert verdict.disabled_reason  # 有判词（阶段或会话语义）
    # QAction 面与 evaluator 一致（乱切后无漂移）
    for tool_id in ("add_line", "add_polygon", "toggle_editing"):
        assert doc.action_controller.actions[tool_id].isEnabled() == \
            availability[tool_id].enabled
        assert doc.action_controller.actions[tool_id].isVisible() == \
            availability[tool_id].visible


def test_rapid_tool_switching(doc):
    polygon_id = _add_layer(doc, "P", "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(polygon_id)
    doc.edit_controller.start_editing()
    doc._sync_action_state()
    log = _messages(doc)
    for tool_id in ("add_polygon", "vertex", "move_feature", "pan",
                    "identify", "add_polygon") * 4:
        doc._on_tool_requested(tool_id)
    # 收敛：最终工具 checked 与 current_tool 一致
    doc._sync_action_state()
    current = doc.edit_controller.tools.active_tool.tool_id
    checked = [
        tool_id for tool_id in ("pan", "add_polygon", "vertex", "move_feature", "identify")
        if doc.action_controller.actions[tool_id].isChecked()
    ]
    assert checked == [current] or (not checked and current not in (
        "pan", "add_polygon", "vertex", "move_feature", "identify"))


def test_delete_layer_while_editing(doc):
    """编辑会话中删除图层：会话终结、可用性回落、无孤儿引用。"""
    layer_id = _add_layer(doc, "D", "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(layer_id)
    doc.edit_controller.start_editing()
    assert doc.edit_controller.editing
    doc._remove_vector_layer(layer_id)
    doc._sync_action_state()
    assert doc.edit_controller.layer(layer_id) is None
    availability = doc.tool_availability()
    assert not availability["add_polygon"].enabled
    assert doc.action_controller.actions["add_polygon"].isEnabled() is False


def test_stage_switch_while_editing(doc):
    """编辑中切阶段：会话语义保持一致（阶段锁生效或会话仍在——不崩溃不漂移）。"""
    layer_id = _add_layer(doc, "S", "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(layer_id)
    doc.stage_controller.set_stage(MappingStage.FACIES_CALIBRATION)
    doc.edit_controller.start_editing()
    for stage in (MappingStage.CONSTRAINT_FACTOR,
                  MappingStage.INTEGRATED_COMPILATION,
                  MappingStage.FACIES_CALIBRATION):
        doc.apply_stage_tool_profile(stage.value)
    doc._sync_action_state()
    # 阶段①草稿角色：切到②后 add_polygon 受阶段过滤（隐藏或禁用——
    # 结论与 QAction 一致即可）
    availability = doc.tool_availability()
    assert doc.action_controller.actions["add_polygon"].isVisible() == \
        availability["add_polygon"].visible


def test_tool_switch_mid_capture(doc):
    """捕获进行中切换工具：上一个工具的 pending capture 不得写入错误图层。"""
    layer_id = _add_layer(doc, "C", "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(layer_id)
    doc.edit_controller.start_editing()
    doc._on_tool_requested("add_polygon")
    tool = doc.edit_controller.tools.active_tool
    if hasattr(tool, "points"):
        tool.points = [(0.0, 0.0), (5.0, 5.0)]  # 模拟半程捕获
    doc._on_tool_requested("pan")  # 中途弃捕
    doc._on_command_requested("cancel")
    layer = doc.edit_controller.layer(layer_id)
    count = len(layer.edit_session.features()) if layer.edit_session else 0
    assert count == 0, "中途弃捕不得落任何要素"


def test_close_project_mid_capture(doc, qtbot):
    """捕获中关闭工程（卸载）：无异常、状态回落。"""
    layer_id = _add_layer(doc, "X", "line", LayerRole.FACIES_BOUNDARY)
    doc.edit_controller.set_active_layer(layer_id)
    doc.edit_controller.start_editing()
    doc._on_tool_requested("add_line")
    tool = doc.edit_controller.tools.active_tool
    if hasattr(tool, "points"):
        tool.points = [(1.0, 1.0)]
    doc.set_project(None)  # 工程关闭
    doc._sync_action_state()
    availability = doc.tool_availability()
    assert not availability["add_line"].enabled


def test_backend_drop_before_reshape(fallback_doc):
    """backend 失效后点 reshape：能力门禁拒绝（无回退实现不得假可用）。"""
    # "backend 失效" = 无原生栈的回退画布（本机桥在场，用 fallback_doc
    # 显式制造）；原生画布上的 reshape 见 test_qgis_topo_m1_*。
    doc = fallback_doc
    assert not doc.uses_native_stack, "本用例钉的是后端缺失形态"
    layer_id = _add_layer(doc, "R", "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(layer_id)
    doc.edit_controller.start_editing()
    layer = doc.edit_controller.layer(layer_id)
    from paleo_workbench.mapping.vector_layer import VectorFeature

    with layer.edit_session.edit_source("setup"):
        layer.edit_session.add_feature(VectorFeature(
            "f1", {"type": "Polygon",
                   "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]]}, {}))
    layer.set_selection(("f1",))
    doc._sync_action_state()
    verdict = doc.tool_availability()["reshape"]
    assert not verdict.enabled
    assert "原生" in verdict.disabled_reason
    log = _messages(doc)
    doc._on_tool_requested("reshape")
    assert any("不可用" in m for m in log), "原生门禁拒绝必须有可读原因"


def test_delete_layer_while_snapping_dialog_open(doc, qtbot):
    """捕捉设置窗口持有层列表时删除目标层：对话框不崩、引用诚实。"""
    layer_id = _add_layer(doc, "N", "line", LayerRole.FACIES_BOUNDARY)
    doc._sync_composition_now()
    from paleo_workbench.ui.workstation.composite_panels import SnappingSettingsDialog

    dialog = SnappingSettingsDialog(doc.edit_controller, parent=doc)
    qtbot.addWidget(dialog)
    dialog.show()
    doc._remove_vector_layer(layer_id)
    doc._sync_composition_now()
    assert doc.edit_controller.layer(layer_id) is None
    # 对话框仍可接受（关闭不崩）
    dialog.reject()
    assert not dialog.isVisible()


def test_restore_layout_then_stage_switch(doc):
    """面板布局恢复后立刻切阶段：无异常（布局权威与阶段权威正交）。"""
    doc.stage_controller.set_stage(MappingStage.FACIES_CALIBRATION)
    doc.apply_stage_tool_profile(MappingStage.CONSTRAINT_FACTOR.value)
    availability = doc.tool_availability()
    # ②阶段：factor 组可见（stage_group_visibility 单点推导）
    assert stage_groups(doc)["factor"] is True
    doc.apply_stage_tool_profile(MappingStage.INTEGRATED_COMPILATION.value)
    assert stage_groups(doc)["factor"] is False
    availability = doc.tool_availability()
    assert availability["factor_workbench"].visible is False


def stage_groups(document):
    from paleo_workbench.mapping.tool_availability import stage_group_visibility

    stage = document.stage_controller.current_stage
    return stage_group_visibility(stage.value if stage else None)


def test_selection_change_then_merge_rapid(doc, monkeypatch):
    """选择变化后立刻 merge（无刷新间隙）：merge_ready 以新鲜求值拦截。"""
    # Python 会话路径的 merge 前置判定（原生合并见 test_qgis_topo_m3_*）。
    monkeypatch.setattr(
        doc.edit_controller, "_native_session_eligible", lambda _layer: False)
    layer_id = _add_layer(doc, "M", "polygon", LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(layer_id)
    doc.edit_controller.start_editing()
    layer = doc.edit_controller.layer(layer_id)
    from paleo_workbench.mapping.vector_layer import VectorFeature

    with layer.edit_session.edit_source("setup"):
        for index in range(3):
            layer.edit_session.add_feature(VectorFeature(
                f"f{index}",
                {"type": "Polygon", "coordinates": [
                    [[float(index), 0], [float(index) + 1, 0],
                     [float(index) + 1, 1], [float(index), 0]]]}, {}))
    layer.set_selection(("f0", "f1"))
    doc._sync_action_state()
    assert doc.tool_availability()["merge"].enabled
    layer.set_selection(("f2",))  # 只剩 1 个 —— merge_ready 变 False
    log = _messages(doc)
    doc._on_command_requested("merge")  # 不刷新直接执行
    assert any("不可用" in m for m in log)
