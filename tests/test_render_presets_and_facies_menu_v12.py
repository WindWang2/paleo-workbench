# -*- coding: utf-8 -*-
"""V12 任务2/3：渲染预设与相带右键换相。

任务2：矢量类型渲染预设——模板/类型 → 符号 + 标注默认；可一键恢复。
任务3：相带要素右键 → 相选择列表 → 写入并刷新分类样式。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


# ---------------------------------------------------------------------------
# 任务2：渲染预设
# ---------------------------------------------------------------------------

def test_style_library_presets_carry_labels():
    """预设库的核心类型自带标注默认（井名/断层名/相名/范围名）。"""
    from paleo_workbench.mapping.map_styles import STYLE_LIBRARY

    expectations = {
        "well": "name",
        "fault": "name",
        "facies": "facies",
        "formation_boundary": "name",
    }
    for key, field in expectations.items():
        style = STYLE_LIBRARY[key]
        assert style.labels is not None, f"{key} 预设缺标注"
        assert style.labels.field == field


def test_templates_reference_preset_styles():
    """模板样式引用预设库（改预设 = 改该类型所有新图的默认渲染）。"""
    from paleo_workbench.mapping.map_styles import STYLE_LIBRARY
    from paleo_workbench.ui.workstation.composite_editing import GEO_TEMPLATES

    by_key = {t.key: t for t in GEO_TEMPLATES}
    assert by_key["fault"].style.to_dict() == STYLE_LIBRARY["fault"].to_dict()
    assert (by_key["extent"].style.to_dict()
            == STYLE_LIBRARY["formation_boundary"].to_dict())


def test_apply_render_preset_restores_template_style(qapp):
    """改坏样式后一键恢复：符号 + 标注回到模板预设。"""
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("t"))
    controller = doc.edit_controller
    layer = controller.create_layer("断层线", "line", template="fault")

    # 模板创建即带预设（含标注）。
    assert layer.style.get("labels"), "模板创建的断层层缺标注预设"
    assert layer.style.get("line_pattern") is not None

    # 用户改坏 → 一键恢复。
    controller.set_layer_style(layer.id, {"stroke": "#123456", "stroke_width": 9.0})
    assert "labels" not in layer.style
    ok, reason = controller.apply_render_preset(layer.id)
    assert ok, reason
    assert layer.style.get("labels", {}).get("field") == "name"
    assert layer.style.get("line_pattern") is not None


@pytest.mark.qgis
def test_facies_preset_is_categorized(qtbot):
    """相带层的预设是分类样式（随要素重算），不是单符号底样。"""
    from paleo_workbench.mapping.vector_layer import VectorFeature
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("t"))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带（相图）", "polygon", template="facies")
    controller.import_layer_features(layer.id, [
        VectorFeature(feature_id="f1",
                      geometry={"type": "Polygon", "coordinates": [[
                          (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0),
                          (0.0, 0.0)]]},
                      attributes={"facies": "砂岩"}),
        VectorFeature(feature_id="f2",
                      geometry={"type": "Polygon", "coordinates": [[
                          (1.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0),
                          (1.0, 0.0)]]},
                      attributes={"facies": "泥岩"}),
    ])
    doc._apply_render_preset(layer.id)
    refreshed = controller.layer(layer.id)
    assert refreshed.style.get("renderer") == "categorized"
    assert refreshed.style.get("labels", {}).get("field") == "facies"


# ---------------------------------------------------------------------------
# 任务3：相带右键换相
# ---------------------------------------------------------------------------

def _facies_document(qtbot):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping.vector_layer import VectorFeature

    doc = CompositeDocument(ProjectDocument.new("t"))
    qtbot.addWidget(doc)
    controller = doc.edit_controller
    layer = controller.create_layer("相带（相图）", "polygon", template="facies")
    controller.import_layer_features(layer.id, [
        VectorFeature(feature_id="f1",
                      geometry={"type": "Polygon", "coordinates": [[
                          (0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0),
                          (0.0, 0.0)]]},
                      attributes={"facies": "砂岩"}),
    ])
    doc._sync_composition_now()
    return doc, controller, layer


@pytest.mark.qgis
def test_context_menu_lists_taxonomy_facies(qtbot):
    """相选择列表 = 词表一级相；当前相勾选。"""
    doc, controller, layer = _facies_document(qtbot)
    menu, actions = doc._build_facies_context_menu(layer.id, "f1")
    names = [name for name in actions.values() if name is not None]
    assert names, "相列表为空——词表未接入"
    taxonomy = doc.facies_taxonomy()
    assert all(name in taxonomy.names("facies") for name in names)
    assert any(v is None for v in actions.values()), "缺级联选择入口"


@pytest.mark.qgis
def test_context_menu_pick_writes_attribute_and_refreshes(qtbot):
    """选相 → 属性写入（自动开会话）→ 分类样式刷新。"""
    doc, controller, layer = _facies_document(qtbot)
    assert doc._apply_context_menu_facies(layer.id, "f1", "泥岩") is True
    refreshed = controller.layer(layer.id)
    session = refreshed.edit_session
    source = session.features() if session is not None else refreshed.features()
    feature = next(f for f in source if f.feature_id == "f1")
    assert feature.attributes.get("facies") == "泥岩"
    assert refreshed.style.get("renderer") == "categorized", "换相后分类样式未刷新"


@pytest.mark.qgis
def test_context_menu_missing_feature_opens_nothing(qtbot):
    """光标未命中要素：不弹菜单、不写入。"""
    doc, controller, layer = _facies_document(qtbot)
    assert doc._on_canvas_context_menu((50.0, 50.0), None) is None
    feature = next(f for f in layer.features() if f.feature_id == "f1")
    assert feature.attributes.get("facies") == "砂岩", "未命中也要零写入"


# ---------------------------------------------------------------------------
# M4-2：geotopo 交互工具面（断层切割 / 共边重塑）
# ---------------------------------------------------------------------------

def test_geotopo_tools_registered_and_gated():
    from paleo_workbench.mapping.action_registry import ACTION_SPECS
    from paleo_workbench.mapping.tool_availability import (
        TOOL_GROUPS, evaluate_tool,
    )
    from paleo_workbench.mapping.tool_help import TOOL_HELP, TOOL_LABELS
    from paleo_workbench.mapping.tool_context import ToolContext

    for tool_id in ("fault_cut", "boundary_reshape"):
        assert tool_id in TOOL_GROUPS["geometry"]
        assert tool_id in TOOL_LABELS and tool_id in TOOL_HELP
        spec = ACTION_SPECS[tool_id]
        assert spec.canvas_interaction and spec.requires_native

    # 非面层 → 拒绝并给原因。
    ctx = ToolContext(
        project_open=True, active_layer_id="L1", active_layer_kind="line",
        editing=True, native_canvas_available=True,
    )
    verdict = evaluate_tool("fault_cut", ctx)
    assert verdict.enabled is False and "面图层" in verdict.disabled_reason

    # 面层 + 编辑会话 + 原生 + 桥 kind 声明 → 可用（flags 取真桥 manifest，
    # 顺带钉住 C++ 清单确实声明了 faultCut/boundaryReshape）。
    import qgis_render_bridge as bridge
    native_tools = set(bridge.capability_manifest()["native_tools"])
    flags = {f"qgis.native_tool.{kind}" for kind in native_tools}
    assert "qgis.native_tool.faultCut" in flags
    assert "qgis.native_tool.boundaryReshape" in flags
    ok_ctx = ToolContext(
        project_open=True, active_layer_id="L1", active_layer_kind="polygon",
        editing=True, native_canvas_available=True, capability_flags=flags,
    )
    assert evaluate_tool("fault_cut", ok_ctx).enabled is True
    assert evaluate_tool("boundary_reshape", ok_ctx).enabled is True



# ---------------------------------------------------------------------------
# M5-A1/A2：环/部件交互删除 + 选择集几何算子
# ---------------------------------------------------------------------------

def test_m5_commands_registered():
    from paleo_workbench.mapping.action_registry import ACTION_SPECS
    from paleo_workbench.mapping.tool_availability import TOOL_GROUPS
    from paleo_workbench.mapping.tool_help import TOOL_HELP, TOOL_LABELS

    for tool_id in ("delete_ring", "delete_part", "reverse_line",
                    "simplify_feature", "smooth_feature", "offset_curve"):
        assert tool_id in TOOL_GROUPS["geometry"]
        assert tool_id in TOOL_LABELS and tool_id in TOOL_HELP
        assert ACTION_SPECS[tool_id].group == "geometry"


def test_selection_geometry_op_reverse_line(qapp):
    """选择集反转方向：坐标序列倒序。"""
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping.vector_layer import VectorFeature

    doc = CompositeDocument(ProjectDocument.new("t"))
    controller = doc.edit_controller
    layer = controller.create_layer("线", "line")
    controller.import_layer_features(layer.id, [
        VectorFeature(feature_id="f1",
                      geometry={"type": "LineString", "coordinates": [
                          [0.0, 0.0], [1.0, 1.0], [2.0, 0.0]]},
                      attributes={}),
    ])
    layer.set_selection({"f1"})
    controller._open_session(layer)
    ok, _msg = controller.selection_geometry_op("reverse_line")
    assert ok
    session = layer.edit_session
    feature = next(f for f in session.features() if f.feature_id == "f1")
    coords = feature.geometry["coordinates"]
    assert coords[0][0] == 2.0 and coords[-1][0] == 0.0, f"未反转: {coords}"


def test_selection_geometry_op_simplify(qapp):
    """简化要素：密度容差抽稀。"""
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping.vector_layer import VectorFeature

    doc = CompositeDocument(ProjectDocument.new("t"))
    controller = doc.edit_controller
    layer = controller.create_layer("线", "line")
    dense = [[float(i) / 20.0, (i % 2) * 0.01] for i in range(21)]
    controller.import_layer_features(layer.id, [
        VectorFeature(feature_id="f1",
                      geometry={"type": "LineString", "coordinates": dense},
                      attributes={}),
    ])
    layer.set_selection({"f1"})
    controller._open_session(layer)
    ok, _msg = controller.selection_geometry_op("simplify_feature", tolerance=0.5)
    assert ok
    session = layer.edit_session
    feature = next(f for f in session.features() if f.feature_id == "f1")
    assert len(feature.geometry["coordinates"]) < len(dense), "未抽稀"


# ---------------------------------------------------------------------------
# M5-B：旋转/缩放 + 剪切/复制/粘贴
# ---------------------------------------------------------------------------

def test_transform_selection_rotate(qapp):
    import math

    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping.vector_layer import VectorFeature

    doc = CompositeDocument(ProjectDocument.new("t"))
    controller = doc.edit_controller
    layer = controller.create_layer("线", "line")
    controller.import_layer_features(layer.id, [
        VectorFeature(feature_id="f1",
                      geometry={"type": "LineString", "coordinates": [
                          [0.0, 0.0], [4.0, 0.0]]},
                      attributes={}),
    ])
    layer.set_selection({"f1"})
    controller._open_session(layer)
    ok, _msg = controller.transform_selection("rotate_feature", angle_degrees=90.0)
    assert ok
    session = layer.edit_session
    feature = next(f for f in session.features() if f.feature_id == "f1")
    coords = feature.geometry["coordinates"]
    # 质心 (2,0) 旋转 90° 逆时针 → 线竖起来：x≈2、y 对称分布。
    xs = [c[0] for c in coords]
    assert max(xs) - min(xs) < 1e-6, f"未竖起: {coords}"


def test_clipboard_copy_paste_with_field_mapping(qapp):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping.vector_layer import VectorFeature

    doc = CompositeDocument(ProjectDocument.new("t"))
    controller = doc.edit_controller
    source = controller.create_layer("源线", "line")
    controller.import_layer_features(source.id, [
        VectorFeature(feature_id="f1",
                      geometry={"type": "LineString", "coordinates": [
                          [0.0, 0.0], [1.0, 1.0]]},
                      attributes={"name": "N1", "throw": "10", "extra": "x"}),
    ])
    controller.set_active_layer(source.id)
    source.set_selection({"f1"})
    ok, _msg = controller.clipboard_copy_selection(cut=False)
    assert ok

    target = controller.create_layer("目标线", "line")
    controller.set_active_layer(target.id)
    controller._open_session(target)
    ok, message = controller.clipboard_paste()
    assert ok, message
    session = target.edit_session
    pasted = [f for f in session.features() if f.feature_id != "f1"]
    assert pasted, "无粘贴要素"
    assert pasted[0].geometry["coordinates"][0][0] == 0.0


def test_clipboard_paste_refuses_crs_mismatch(qapp):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping.vector_layer import VectorFeature

    doc = CompositeDocument(ProjectDocument.new("t"))
    controller = doc.edit_controller
    source = controller.create_layer("源", "line")
    source.crs = "EPSG:4326"
    controller.import_layer_features(source.id, [
        VectorFeature(feature_id="f1",
                      geometry={"type": "LineString", "coordinates": [
                          [0.0, 0.0], [1.0, 1.0]]},
                      attributes={}),
    ])
    controller.set_active_layer(source.id)
    source.set_selection({"f1"})
    controller.clipboard_copy_selection(cut=False)

    target = controller.create_layer("目标", "line")
    target.crs = "EPSG:3857"
    controller.set_active_layer(target.id)
    controller._open_session(target)
    ok, message = controller.clipboard_paste()
    assert ok is False and "坐标系" in message


# ---------------------------------------------------------------------------
# M5-A1 shape + 批量吸附（矩形/圆：两步交互；snap_geometries：选集吸附）
# ---------------------------------------------------------------------------

def test_shape_tools_registered_in_capture_group():
    from paleo_workbench.mapping.action_registry import ACTION_SPECS
    from paleo_workbench.mapping.tool_availability import TOOL_GROUPS
    from paleo_workbench.mapping.tool_help import TOOL_HELP, TOOL_LABELS

    for tool_id in ("add_rectangle", "add_circle", "snap_geometries"):
        assert tool_id in (TOOL_GROUPS["capture"] + TOOL_GROUPS["geometry"])
        assert tool_id in TOOL_LABELS and tool_id in TOOL_HELP
        assert ACTION_SPECS[tool_id].icon


def test_rectangle_capture_builds_closed_rect(qapp):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping.vector_layer import VectorFeature
    from paleo_workbench.mapping.map_tools import RectangleCaptureTool

    doc = CompositeDocument(ProjectDocument.new("t"))
    controller = doc.edit_controller
    layer = controller.create_layer("面", "polygon")
    controller._open_session(layer)

    tool = RectangleCaptureTool(layer.edit_session, snap=lambda p: p)
    assert tool.mouse_press((1.0, 1.0)) is True
    assert tool.mouse_press((4.0, 3.0)) is True
    features = layer.edit_session.features()
    assert len(features) == 1
    ring = features[0].geometry["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 5, f"矩形未闭合: {ring}"
    xs = sorted({c[0] for c in ring})
    ys = sorted({c[1] for c in ring})
    assert xs == [1.0, 4.0] and ys == [1.0, 3.0], f"对角未展开: {ring}"


def test_circle_capture_builds_closed_ring(qapp):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping.map_tools import CircleCaptureTool

    doc = CompositeDocument(ProjectDocument.new("t"))
    controller = doc.edit_controller
    layer = controller.create_layer("面", "polygon")
    controller._open_session(layer)

    tool = CircleCaptureTool(layer.edit_session, snap=lambda p: p)
    assert tool.mouse_press((2.0, 2.0)) is True
    assert tool.mouse_press((5.0, 2.0)) is True
    features = layer.edit_session.features()
    assert len(features) == 1
    ring = features[0].geometry["coordinates"][0]
    assert ring[0] == ring[-1] and len(ring) == 65, f"圆环异常: {len(ring)}"
    import math
    dist = math.dist(ring[0], (2.0, 2.0))
    assert abs(dist - 3.0) < 1e-6, f"半径错误: {dist}"


def test_snap_geometries_command(qapp):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument
    from paleo_workbench.mapping.vector_layer import VectorFeature

    doc = CompositeDocument(ProjectDocument.new("t"))
    controller = doc.edit_controller
    layer = controller.create_layer("线", "line")
    controller.import_layer_features(layer.id, [
        VectorFeature(feature_id="f1",
                      geometry={"type": "LineString", "coordinates": [
                          [0.0, 0.0], [1.1, 0.1]]},
                      attributes={}),
        VectorFeature(feature_id="f2",
                      geometry={"type": "LineString", "coordinates": [
                          [5.0, 5.0], [6.0, 5.0]]},
                      attributes={}),
    ])
    # 只吸附 f1：候选含 f2 的 (6,5)——(1.1,0.1) 距它远超容差，应命中
    # 自层最近顶点 (1.1,0.1) 自身 → 无变更（诚实拒绝，不开空宏）。
    layer.set_selection({"f1"})
    controller._open_session(layer)
    controller._snapping.modes = {"vertex", "segment"}
    ok, message = controller.snap_geometries(tolerance=0.2)
    assert (ok, message) == (False, "选集无人可吸附"), (ok, message)


def test_snapping_priority_tiebreak():
    """M4-3b：等距候选按 layer_priority 裁决（小值优先，回退栈）。"""
    from paleo_workbench.mapping.map_interaction import SnappingService
    from paleo_workbench.mapping.vector_layer import VectorLayer

    service = SnappingService()
    service.enabled = True
    service.modes = {"vertex"}
    from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer

    def _layer_with_point(layer_id: str):
        layer = VectorLayer(id=layer_id, name=layer_id, crs="",
                            schema={}, style={},
                            features=[VectorFeature(
                                feature_id=f"{layer_id}-f",
                                geometry={"type": "LineString", "coordinates": [
                                    [5.0, 5.0], [9.0, 5.0]]},
                                attributes={})])
        service.index_for(layer)  # 索引建在挂载后
        return layer

    a = _layer_with_point("a")
    b = _layer_with_point("b")
    service.layer_priority["a"] = 10
    service.layer_priority["b"] = 1
    assert service.snap((5.1, 5.0), tolerance=1.0,
                        layers=[a, b], map_units_per_pixel=1.0) == (5.0, 5.0)
    assert service.last_match.feature_id == "b-f", (
        f"等距时优先级未裁决：{service.last_match}")
