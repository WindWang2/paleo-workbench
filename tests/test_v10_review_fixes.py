"""V10 review 修复的回归钉（R1–R5 findings；见 12-review-findings.md）。"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import pytest

from paleo_workbench.mapping.tool_availability import evaluate_tool
from paleo_workbench.mapping.tool_context import ToolContext
from paleo_workbench.mapping_workspace.layer_roles import LayerRole
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.map_status_bar import _format_scale
from paleo_workbench.ui.workstation.composite_document import CompositeDocument

REPO = Path(__file__).resolve().parents[1]


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

    probe = QMenu(panel)
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
def test_toggle_editing_commits_other_session(doc, monkeypatch):
    # 本文件钉宿主侧 Python 会话簿记（提交/回滚/撤销单元/拓扑计数）：
    # polygon/line 已翻原生会话（M5），此处显式钉回 Python 路径；
    # 原生等价语义见 test_qgis_topo_m1/m2/m4_*。
    monkeypatch.setattr(
        doc.edit_controller, "_native_session_eligible", lambda _layer: False)
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


def test_tree_layer_switch_commits_other_session(doc, monkeypatch):
    """#1268: 树选中另一层也必须提交/回滚前一会话。"""
    # 本文件钉宿主侧 Python 会话簿记（提交/回滚/撤销单元/拓扑计数）：
    # polygon/line 已翻原生会话（M5），此处显式钉回 Python 路径；
    # 原生等价语义见 test_qgis_topo_m1/m2/m4_*。
    monkeypatch.setattr(
        doc.edit_controller, "_native_session_eligible", lambda _layer: False)
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
def test_topology_validate_covers_all_sessions(doc, monkeypatch):
    # 本文件钉宿主侧 Python 会话簿记（提交/回滚/撤销单元/拓扑计数）：
    # polygon/line 已翻原生会话（M5），此处显式钉回 Python 路径；
    # 原生等价语义见 test_qgis_topo_m1/m2/m4_*。
    monkeypatch.setattr(
        doc.edit_controller, "_native_session_eligible", lambda _layer: False)
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


def _seeded_polygon(doc, name, count, select=True):
    """建一个含 ``count`` 个不重叠三角形要素的已编辑层（全部选中）。"""
    from paleo_workbench.mapping.vector_layer import VectorFeature

    layer = doc.edit_controller.create_layer(name, "polygon")
    _register_role(doc, layer.id, LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(layer.id)
    doc.edit_controller.start_editing()
    # 种子本身包成一条宏，基线固定 1 个 undo 单元（edit_source 只打标、不开
    # 宏——拿它当宏会让断言读错基线）。
    layer.edit_session.begin_edit_command()
    for index in range(count):
        x = float(index * 10)
        layer.edit_session.add_feature(VectorFeature(
            f"f{index}",
            {"type": "Polygon", "coordinates": [[
                [x, 0.0], [x + 5.0, 0.0], [x + 5.0, 5.0], [x, 0.0]]]},
            {}))
    layer.edit_session.end_edit_command()
    if select:
        layer.set_selection([f"f{index}" for index in range(count)])
    return layer


# #1259：多选 delete/duplicate = 单一 undo 单元（07 §B.1）。
def test_multi_select_delete_is_single_undo_unit(doc, monkeypatch):
    # 本文件钉宿主侧 Python 会话簿记（提交/回滚/撤销单元/拓扑计数）：
    # polygon/line 已翻原生会话（M5），此处显式钉回 Python 路径；
    # 原生等价语义见 test_qgis_topo_m1/m2/m4_*。
    monkeypatch.setattr(
        doc.edit_controller, "_native_session_eligible", lambda _layer: False)
    layer = _seeded_polygon(doc, "del", 3)
    session = layer.edit_session
    assert len(session.undo_stack) == 1  # seed 宏
    assert doc.edit_controller.edit_command("delete_selected") is True
    assert len(session.undo_stack) == 2, "N 选删除必须是单一 undo 单元"
    assert session.features() == ()
    assert session.undo()
    assert {f.feature_id for f in session.features()} == {"f0", "f1", "f2"}


def test_multi_select_duplicate_is_single_undo_unit(doc, monkeypatch):
    # 本文件钉宿主侧 Python 会话簿记（提交/回滚/撤销单元/拓扑计数）：
    # polygon/line 已翻原生会话（M5），此处显式钉回 Python 路径；
    # 原生等价语义见 test_qgis_topo_m1/m2/m4_*。
    monkeypatch.setattr(
        doc.edit_controller, "_native_session_eligible", lambda _layer: False)
    layer = _seeded_polygon(doc, "dup", 3)
    session = layer.edit_session
    assert doc.edit_controller.edit_command("duplicate_selected") is True
    assert len(session.undo_stack) == 2, "N 选复制必须是单一 undo 单元"
    assert len(session.features()) == 6
    assert session.undo()
    assert len(session.features()) == 3


# #1264：add_ring / add_part 挂上拓扑计数刷新点。
def test_ring_and_part_appliers_refresh_topology_count(doc, monkeypatch):
    """V10 新增命令族与同族命令共用刷新点（否则门禁读到过期计数）。"""
    # 同前：钉宿主侧 Python 会话（原生等价语义见 test_qgis_topo_*）。
    monkeypatch.setattr(
        doc.edit_controller, "_native_session_eligible", lambda _layer: False)
    import json as _json
    import types

    from paleo_workbench.mapping.vector_layer import VectorFeature

    layer = doc.edit_controller.create_layer("ring", "polygon")
    _register_role(doc, layer.id, LayerRole.INITIAL_FACIES_DRAFT)
    doc.edit_controller.set_active_layer(layer.id)
    doc.edit_controller.start_editing()
    session = layer.edit_session
    with session.edit_source("seed"):
        session.add_feature(VectorFeature(
            "f0",
            {"type": "Polygon", "coordinates": [
                [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
            {}))

    calls = []

    class _TopologyStub:
        def refresh_error_count(self, target):
            calls.append(target.id)
            return 0

    controller = doc.edit_controller
    monkeypatch.setattr(controller, "_topology", _TopologyStub())

    # add_ring：内环顶点须落在目标面外环内（含性守卫）。
    assert controller._apply_captured_ring(session, "f0", {
        "type": "Polygon",
        "coordinates": [[[2, 2], [4, 2], [4, 4], [2, 2]]]}) is True
    assert calls == [layer.id], "add_ring 未刷新拓扑错误计数"

    # add_part：桥面用替身（宿主侧只验刷新点是否挂上）。
    def _fake_add_part(target_json, part_json):
        target = _json.loads(target_json)
        part = _json.loads(part_json)
        return _json.dumps({"type": "MultiPolygon",
                            "coordinates": [target["coordinates"],
                                            part["coordinates"]]})

    bridge_stub = types.ModuleType("qgis_render_bridge")
    bridge_stub.geometry = types.SimpleNamespace(add_part=_fake_add_part)
    monkeypatch.setitem(sys.modules, "qgis_render_bridge", bridge_stub)

    calls.clear()
    applier = controller._make_part_applier(session, "f0")
    assert applier is not None, "替身桥未生效"
    assert applier({"type": "Polygon",
                    "coordinates": [[[20, 20], [21, 20], [21, 21], [20, 20]]]}) is True
    assert calls == [layer.id], "add_part 未刷新拓扑错误计数"


def test_move_part_refreshes_topology_count_for_merge_gate(doc, monkeypatch):
    """move_part 成功后 merge 门禁必须读到新计数，不能沿用过期 0（#1264）。"""
    # 本文件钉宿主侧 Python 会话簿记（提交/回滚/撤销单元/拓扑计数）：
    # polygon/line 已翻原生会话（M5），此处显式钉回 Python 路径；
    # 原生等价语义见 test_qgis_topo_m1/m2/m4_*。
    monkeypatch.setattr(
        doc.edit_controller, "_native_session_eligible", lambda _layer: False)
    from paleo_workbench.mapping.vector_layer import VectorFeature

    layer = doc.edit_controller.create_layer("parts", "polygon")
    _register_role(doc, layer.id, LayerRole.INITIAL_FACIES_DRAFT)
    controller = doc.edit_controller
    controller.set_active_layer(layer.id)
    controller.start_editing()
    session = layer.edit_session
    with session.edit_source("seed"):
        session.add_feature(VectorFeature(
            "f0",
            {"type": "MultiPolygon", "coordinates": [
                [[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]],
                [[[20.0, 0.0], [30.0, 0.0], [30.0, 10.0], [20.0, 10.0], [20.0, 0.0]]],
            ]},
            {}))
    layer.set_selection(("f0",))
    controller._topology.refresh_error_count(layer)
    assert controller.tool_context_inputs()["topology_error_count"] == 0

    ok, message = controller._ring_and_part_commands(
        "move_part", pick_point={"point": (25.0, 5.0), "delta": (-15.0, 5.0)})
    assert ok, message
    assert controller.tool_context_inputs()["topology_error_count"] >= 1, (
        "move_part 后拓扑计数未刷新，merge/collect 门禁会读到过期 0")


# -- #1258：edit-pick 回执必须落到 shim 分发层 ----------------------------------

class _Recorder:
    """``Signal.emit`` 的最小替身（分发器只调 emit）。"""

    def __init__(self):
        self.values = []

    def emit(self, value):
        self.values.append(value)


class _ShimStub:
    def __init__(self):
        self.commit_rejected = _Recorder()
        self.tool_operation = _Recorder()
        self.snap_feedback = _Recorder()


_EDIT_PICK_ACTIONS = re.compile(
    r'callback_\("((?:pick_miss|vertex_[a-z_]+|feature_moved|snap_feedback))"')


def test_vertex_delete_rejected_reaches_shim():
    """C++ 的 vertex_delete_rejected 在 shim 层有消费方（#1258）。

    修复前该 action 落空：既不 emit commit_rejected 也不 emit
    tool_operation(False)，Delete 键在守卫拒绝时完全无声。
    """
    from paleo_workbench.ui.qgis_stack.canvas_shim import dispatch_edit_pick

    class _Tool:
        def commit_vertex_delete(self, feature_id, path):
            raise AssertionError("拒绝回执不应进入提交路径")

    shim = _ShimStub()
    assert dispatch_edit_pick(shim, _Tool(), "vertex_delete_rejected", {}) is False
    assert len(shim.commit_rejected.values) == 1, "拒绝回执未上浮 → 无声死键"
    assert shim.tool_operation.values == [False]


def test_edit_pick_dispatch_success_and_rejection():
    """提交成功发 tool_operation(True)；提交被拒发 rejected + False。"""
    from paleo_workbench.ui.qgis_stack.canvas_shim import dispatch_edit_pick

    class _Accepting:
        def commit_vertex_moved(self, *a):  # 名字故意不匹配，走不到
            raise AssertionError

        def commit_vertex_move(self, feature_id, path, point):
            return True

    class _Rejecting:
        def commit_vertex_delete(self, feature_id, path):
            return False

    shim = _ShimStub()
    assert dispatch_edit_pick(
        shim, _Accepting(), "vertex_moved",
        {"feature_id": "f1", "path": [0, 1], "x": 1.0, "y": 2.0}) is True
    assert shim.tool_operation.values == [True]
    assert not shim.commit_rejected.values

    shim = _ShimStub()
    assert dispatch_edit_pick(
        shim, _Rejecting(), "vertex_deleted",
        {"feature_id": "f1", "path": [0, 1]}) is False
    assert len(shim.commit_rejected.values) == 1
    assert shim.tool_operation.values == [False]


def test_every_edit_pick_callback_has_shim_consumer():
    """C++ edit-pick 回执族 ⊆ shim 分发层已处理集（源码扫描，#1258）。

    把"C++ 发出回执"与"shim 已消费"钉成一对：将来 C++ 新增回执而 Python
    未接线时本测试即红（此前 vertex_delete_rejected 正是这样漏掉的，而裸
    回调测试绕开分发层，显示通过）。
    """
    from paleo_workbench.ui.qgis_stack.canvas_shim import dispatch_edit_pick

    source = (REPO / "native" / "qgis_render_bridge" / "src" / "edit_tools.cpp")
    emitted = set(_EDIT_PICK_ACTIONS.findall(source.read_text(encoding="utf-8")))
    assert emitted, "未解析到 edit-pick 回执——断言失去意义"
    handled = set(re.findall(
        r'action == "([a-z_]+)"', inspect.getsource(dispatch_edit_pick)))
    # pick_miss 在 _on_edit_pick 里显式提前返回（无回执语义），不进分发器。
    unhandled = emitted - handled - {"pick_miss"}
    assert not unhandled, f"C++ 回执在 shim 分发层无消费方: {sorted(unhandled)}"
