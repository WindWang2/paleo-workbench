"""Task 8：identify 门禁放宽 + 无活动层激活 + 点击悬浮框。

门禁：identify 从"活动矢量图层"放宽为"工程已打开且存在可查询图层"
（``ToolContext.queryable_layer_count``，编修层 + 基础工区层 + 就绪引用层）；
select/select_rectangle 门禁不动。identify 与活动层解耦（V10 识别修复）：
恒绑无层 IdentifyTool（原生栈 PwbIdentifyTool 扫全部可见镜像层，旧桥经
identify_delegate 多层识别），有结果时在点击处 QToolTip 悬浮（纯函数
``_identify_popup_text`` 组装文本）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from paleo_workbench.mapping.map_tools import IdentifyTool
from paleo_workbench.mapping.tool_availability import (
    _NEEDS_LAYER_GROUPS,
    evaluate_tool,
)
from paleo_workbench.mapping.tool_context import ToolContext
from paleo_workbench.mapping.tool_help import TOOL_HELP
from paleo_workbench.mapping.vector_layer import VectorFeature
from paleo_workbench.project.domain import WellEntity
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.workstation.composite_document import (
    CompositeDocument,
    _base_identify_entry,
    _identify_popup_text,
    _pick_base_identify_target_id,
)
from paleo_workbench.ui.workstation.composite_editing import (
    CompositeEditController,
    pick_topmost_visible_layer_id,
)


def _ctx(**changes) -> ToolContext:
    base = {"project_open": True, "mapping_stage": None}
    base.update(changes)
    return ToolContext(**base)


# -- 门禁三态 ---------------------------------------------------------------


def test_identify_disabled_without_project():
    verdict = evaluate_tool(
        "identify", _ctx(project_open=False, queryable_layer_count=5))
    assert not verdict.enabled
    assert verdict.disabled_reason == "未打开工程"


def test_identify_disabled_without_queryable_layers():
    verdict = evaluate_tool("identify", _ctx(queryable_layer_count=0))
    assert not verdict.enabled
    assert verdict.disabled_reason == "没有可查询的图层"


def test_identify_enabled_without_active_layer_when_queryable():
    verdict = evaluate_tool(
        "identify",
        _ctx(active_layer_id="", active_layer_kind="",
             queryable_layer_count=2),
    )
    assert verdict.enabled, verdict.disabled_reason


def test_identify_enabled_with_raster_and_count():
    verdict = evaluate_tool(
        "identify",
        _ctx(active_layer_id="ref-1", qgis_layer_type="raster",
             queryable_layer_count=1),
    )
    assert verdict.enabled, verdict.disabled_reason


def test_select_gates_unchanged_without_active_layer():
    for tool_id in ("select", "select_rectangle"):
        verdict = evaluate_tool(tool_id, _ctx(queryable_layer_count=3))
        assert not verdict.enabled
        assert verdict.disabled_reason == "没有活动的矢量图层"


def test_measure_gate_unchanged_without_active_layer():
    verdict = evaluate_tool(
        "measure_distance", _ctx(queryable_layer_count=3))
    assert not verdict.enabled
    assert verdict.disabled_reason == "没有活动的矢量图层"


def test_identify_help_states_queryable_requirement():
    assert (
        TOOL_HELP["identify"].requirements == "有可查询图层（工程已打开）"
    )


# -- 组可见性 ---------------------------------------------------------------


def test_inspection_group_not_layer_gated():
    assert "inspection" not in _NEEDS_LAYER_GROUPS


def test_identify_stays_visible_without_layers():
    verdict = evaluate_tool("identify", _ctx(queryable_layer_count=0))
    assert verdict.visible
    assert not verdict.enabled


# -- popup 纯函数 ------------------------------------------------------------


def _result(layer_name="相带", attributes=None, feature_id="f1"):
    return {
        "layer_id": "l1",
        "layer_name": layer_name,
        "feature_id": feature_id,
        "geometry_type": "Polygon",
        "attributes": dict(attributes or {}),
        "source": "composite",
        "template": "",
        "editable": True,
        "record": {},
    }


def test_popup_prefers_name_attribute():
    text = _identify_popup_text(
        [_result(attributes={"name": "A12", "facies": "砂"})])
    assert text == "相带：A12"


def test_popup_falls_back_to_facies_then_first_attribute():
    assert _identify_popup_text(
        [_result(attributes={"facies": "泥岩", "depth": 10})]) == "相带：泥岩"
    assert _identify_popup_text(
        [_result(attributes={"depth": 100})]) == "相带：100"


def test_popup_skips_geometry_like_attributes():
    text = _identify_popup_text(
        [_result(attributes={"geometry": {"type": "Point"},
                           "GEOM": "x", "depth": 7})])
    assert text == "相带：7"


def test_popup_empty_attributes_falls_back_to_feature_id():
    assert _identify_popup_text([_result(attributes={})]) == "相带：f1"


def test_popup_empty_results_is_empty():
    assert _identify_popup_text([]) == ""


def test_popup_caps_at_five_with_overflow_suffix():
    results = [
        _result(layer_name=f"层{i}", attributes={"name": f"n{i}"},
                feature_id=f"f{i}")
        for i in range(7)
    ]
    lines = _identify_popup_text(results).split("\n")
    assert lines[:5] == [f"层{i}：n{i}" for i in range(5)]
    assert lines[5] == "共 7 项 · 详见识别结果面板"
    assert len(lines) == 6


def test_popup_exactly_five_has_no_suffix():
    results = [_result(layer_name=f"层{i}") for i in range(5)]
    text = _identify_popup_text(results)
    assert "详见识别结果面板" not in text
    assert len(text.split("\n")) == 5


# -- 原生选层纯函数 ----------------------------------------------------------


def test_pick_topmost_visible_layer():
    assert pick_topmost_visible_layer_id(("a", "b", "c"), frozenset({"a", "b", "c"})) == "c"


def test_pick_topmost_skips_hidden():
    assert pick_topmost_visible_layer_id(("a", "b", "c"), frozenset({"a", "b"})) == "b"


def test_pick_topmost_none_when_all_hidden_or_empty():
    assert pick_topmost_visible_layer_id(("a", "b"), frozenset()) is None
    assert pick_topmost_visible_layer_id((), frozenset()) is None


# -- fallback 激活 -----------------------------------------------------------


def test_identify_tool_routes_click_to_identify():
    calls: list = []
    tool = IdentifyTool(identify=lambda point: calls.append(point) or "f1")
    assert tool.tool_id == "identify"
    assert tool.mouse_press((1.0, 2.0)) is True
    assert calls == [(1.0, 2.0)]
    assert tool.mouse_press((1.0, 2.0), button="right") is False
    assert len(calls) == 1


def test_fallback_identify_without_any_layer_uses_delegate(qtbot):
    controller = CompositeEditController()
    calls: list = []
    controller.identify_delegate = lambda point: calls.append(point)
    controller.activate_tool("identify")
    tool = controller.tools.active_tool
    assert isinstance(tool, IdentifyTool)
    assert tool.mouse_press((3.0, 4.0)) is True
    assert calls == [(3.0, 4.0)]


def test_fallback_identify_without_active_layer_binds_topmost(qtbot):
    """识别与图层解耦（V10 识别修复）：无活动层 + 存在编修层时也绑
    无层 IdentifyTool——绑 SelectTool 会让原生栈把识别点击路由成选择
    回调，信息面板永远不出现。"""
    controller = CompositeEditController()
    lower = controller.create_layer("下层", "polygon")
    upper = controller.create_layer("上层", "polygon")
    controller.set_active_layer(None)
    calls: list = []
    controller.identify_delegate = lambda point: calls.append(point)
    controller.activate_tool("identify")
    tool = controller.tools.active_tool
    assert isinstance(tool, IdentifyTool)
    assert getattr(tool, "layer", None) is None
    assert tool.mouse_press((3.0, 4.0)) is True
    assert calls == [(3.0, 4.0)]
    assert lower.id != upper.id


def test_fallback_identify_skips_hidden_topmost(qtbot):
    """可见性过滤属于识别执行（delegate / 原生拾取只扫可见层），
    不属于工具激活——隐藏层存在不影响 IdentifyTool 绑定。"""
    controller = CompositeEditController()
    controller.create_layer("下层", "polygon")
    upper = controller.create_layer("上层", "polygon")
    controller.apply_display_state([
        SimpleNamespace(id=upper.id, visible=False, opacity=1.0),
    ])
    controller.set_active_layer(None)
    calls: list = []
    controller.identify_delegate = lambda point: calls.append(point)
    controller.activate_tool("identify")
    tool = controller.tools.active_tool
    assert isinstance(tool, IdentifyTool)
    assert tool.mouse_press((1.0, 1.0)) is True
    assert calls == [(1.0, 1.0)]


def test_topmost_visible_layer_id_follows_display(qtbot):
    controller = CompositeEditController()
    first = controller.create_layer("一层", "polygon")
    second = controller.create_layer("二层", "polygon")
    assert controller.topmost_visible_layer_id() == second.id
    controller.apply_display_state([
        SimpleNamespace(id=first.id, visible=True, opacity=1.0),
        SimpleNamespace(id=second.id, visible=False, opacity=1.0),
    ])
    assert controller.topmost_visible_layer_id() == first.id


def test_ensure_identify_layer_current_selects_topmost(qtbot, tmp_path):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    if not document.uses_native_stack:
        pytest.skip("仅原生栈需要置 current")
    controller = document.edit_controller
    controller.create_layer("下层", "polygon")
    upper = controller.create_layer("上层", "polygon")
    controller.set_active_layer(None)
    document._ensure_identify_layer_current()
    assert controller.active_layer_id == upper.id


def test_command_requested_identify_activates_without_active_layer(
    qtbot, tmp_path
):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    controller = document.edit_controller
    controller.create_layer("下层", "polygon")
    controller.create_layer("上层", "polygon")
    controller.set_active_layer(None)
    document._on_command_requested("identify")
    tool = controller.tools.active_tool
    assert tool is not None
    # V10 识别修复：编修层存在时 identify 仍必须是 identify 工具——
    # 绑 SelectTool（tool_id "select"）会让原生栈把识别点击变成选择
    # 回调，属性信息不弹（用户报障的根因）。
    assert isinstance(tool, IdentifyTool)
    assert tool.tool_id == "identify"


# -- 文档集成 -----------------------------------------------------------------


def _project(tmp_path: Path) -> ProjectDocument:
    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0,
                   project_x=1.0, project_y=2.0)
    )
    return project


def test_document_queryable_count_covers_base_layers(qtbot, tmp_path):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    assert len(document._base_layers) > 0
    assert document.queryable_layer_count() == len(document._base_layers)
    verdict = evaluate_tool("identify", document.tool_context())
    assert verdict.enabled, verdict.disabled_reason


def test_document_queryable_count_zero_without_anything(qtbot, tmp_path):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    document._base_layers = []
    assert document.queryable_layer_count() == 0
    verdict = evaluate_tool("identify", document.tool_context())
    assert not verdict.enabled
    assert verdict.disabled_reason == "没有可查询的图层"


def test_identify_with_results_pops_tooltip_on_hit(
    qtbot, tmp_path, monkeypatch
):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    controller = document.edit_controller
    layer = controller.create_layer("相带", "polygon")
    # 并行在途改动（layer_tree_panel reconcile）会吞新建层活动态：
    # 此处显式恢复被测前置（见 task-8 报告 concerns）。
    controller.set_active_layer(layer.id)
    controller.start_editing()
    layer.edit_session.add_feature(VectorFeature(
        "poly",
        {"type": "Polygon",
         "coordinates": [[[0.0, -1.0], [2.0, -1.0], [2.0, 1.0],
                           [0.0, 1.0], [0.0, -1.0]]]},
        {"facies": "三角洲"},
    ))
    shown: list = []
    monkeypatch.setattr(
        "paleo_workbench.ui.workstation.composite_document.QToolTip",
        SimpleNamespace(showText=lambda *args: shown.append(args),
                        hideText=lambda: None),
    )
    feature_id = document._identify_with_results((1.0, 0.0))
    assert feature_id == "poly"
    assert len(shown) == 1
    assert "相带：三角洲" in shown[0][1]


def test_identify_with_results_no_tooltip_on_miss(
    qtbot, tmp_path, monkeypatch
):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    controller = document.edit_controller
    layer = controller.create_layer("相带", "polygon")
    # 并行在途改动（layer_tree_panel reconcile）会吞新建层活动态：
    # 此处显式恢复被测前置（见 task-8 报告 concerns）。
    controller.set_active_layer(layer.id)
    controller.start_editing()
    layer.edit_session.add_feature(VectorFeature(
        "poly",
        {"type": "Polygon",
         "coordinates": [[[0.0, -1.0], [2.0, -1.0], [2.0, 1.0],
                           [0.0, 1.0], [0.0, -1.0]]]},
        {"facies": "三角洲"},
    ))
    shown: list = []
    monkeypatch.setattr(
        "paleo_workbench.ui.workstation.composite_document.QToolTip",
        SimpleNamespace(showText=lambda *args: shown.append(args),
                        hideText=lambda: None),
    )
    document._identify_with_results((500.0, 500.0))
    assert shown == []


def test_native_identified_pops_tooltip(qtbot, tmp_path, monkeypatch):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    controller = document.edit_controller
    layer = controller.create_layer("相带", "polygon")
    # 并行在途改动（layer_tree_panel reconcile）会吞新建层活动态：
    # 此处显式恢复被测前置（见 task-8 报告 concerns）。
    controller.set_active_layer(layer.id)
    controller.start_editing()
    layer.edit_session.add_feature(VectorFeature(
        "poly",
        {"type": "Polygon", "coordinates": [[[0.0, 0.0]]] } ,
        {"name": "河道砂"},
    ))
    shown: list = []
    monkeypatch.setattr(
        "paleo_workbench.ui.workstation.composite_document.QToolTip",
        SimpleNamespace(showText=lambda *args: shown.append(args),
                        hideText=lambda: None),
    )
    document._on_native_identified(
        {"layer_doc_id": layer.id, "feature_id": "poly"})
    assert document.identify_results.tree.topLevelItemCount() == 1
    assert len(shown) == 1
    assert "相带：河道砂" in shown[0][1]


def test_native_identified_miss_clears_without_tooltip(
    qtbot, tmp_path, monkeypatch
):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    shown: list = []
    monkeypatch.setattr(
        "paleo_workbench.ui.workstation.composite_document.QToolTip",
        SimpleNamespace(showText=lambda *args: shown.append(args),
                        hideText=lambda: None),
    )
    document._on_native_identified(
        {"layer_doc_id": "nope", "feature_id": "ghost"})
    assert document.identify_results.tree.topLevelItemCount() == 0
    assert shown == []


# -- Task 9：原生栈识别覆盖基础镜像层 ------------------------------------------
# 原生 QgsMapToolIdentifyFeature 只钉画布 currentLayer；零编修层 + 仅基础层
# （井位等镜像层）时 Task 8 的 _ensure 只处理编修层，点击无命中。
# 以下用例钉死：基础层条目重建纯函数、current 选择顺序（编修 → 基础）、
# 原生回调进面板 + 悬浮、真桥端到端。


def _flagged(document):
    return next(
        layer for layer in document._base_layers
        if layer.id == "home_workarea:wells_flagged"
    )


def test_base_identify_entry_hit(qtbot, tmp_path):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    layer = _flagged(document)
    record = layer.features[0]
    entry = _base_identify_entry(
        document._base_layers, layer.id, record.get("id"))
    assert entry is not None
    assert entry["layer_id"] == layer.id
    assert entry["layer_name"] == layer.name
    assert entry["feature_id"] == record.get("id")
    assert entry["geometry_type"] == "Point"
    assert entry["attributes"]["name"] == "A12"
    assert entry["editable"] is False
    assert entry["template"] == ""
    assert entry["record"]["id"] == record.get("id")


def test_base_identify_entry_miss_unknown_layer(qtbot, tmp_path):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    assert _base_identify_entry(
        document._base_layers, "home_workarea:nope", "wells:x") is None


def test_base_identify_entry_miss_unknown_feature(qtbot, tmp_path):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    layer = _flagged(document)
    assert _base_identify_entry(
        document._base_layers, layer.id, "wells:ghost") is None


def test_base_identify_entry_empty_feature_id(qtbot, tmp_path):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    layer = _flagged(document)
    assert _base_identify_entry(document._base_layers, layer.id, "") is None


def test_pick_base_identify_target_topmost_visible():
    lower = SimpleNamespace(id="home_workarea:boundary", visible=True)
    upper = SimpleNamespace(id="home_workarea:wells_flagged", visible=True)
    assert _pick_base_identify_target_id([lower, upper]) == upper.id


def test_pick_base_identify_target_skips_hidden():
    lower = SimpleNamespace(id="home_workarea:boundary", visible=True)
    upper = SimpleNamespace(id="home_workarea:wells_flagged", visible=False)
    assert _pick_base_identify_target_id([lower, upper]) == lower.id


def test_pick_base_identify_target_none_when_hidden_or_empty():
    hidden = SimpleNamespace(id="home_workarea:boundary", visible=False)
    assert _pick_base_identify_target_id([hidden]) is None
    assert _pick_base_identify_target_id([]) is None


def test_native_identified_base_layer_builds_panel_entry(
    qtbot, tmp_path, monkeypatch
):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    layer = _flagged(document)
    record = layer.features[0]
    shown: list = []
    monkeypatch.setattr(
        "paleo_workbench.ui.workstation.composite_document.QToolTip",
        SimpleNamespace(showText=lambda *args: shown.append(args),
                        hideText=lambda: None),
    )
    document._on_native_identified(
        {"layer_doc_id": layer.id, "feature_id": record.get("id")})
    assert document.identify_results.tree.topLevelItemCount() == 1
    assert len(shown) == 1
    assert "A12" in shown[0][1]


def test_native_identified_base_miss_clears_without_tooltip(
    qtbot, tmp_path, monkeypatch
):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    layer = _flagged(document)
    shown: list = []
    monkeypatch.setattr(
        "paleo_workbench.ui.workstation.composite_document.QToolTip",
        SimpleNamespace(showText=lambda *args: shown.append(args),
                        hideText=lambda: None),
    )
    document._on_native_identified(
        {"layer_doc_id": layer.id, "feature_id": "wells:ghost"})
    assert document.identify_results.tree.topLevelItemCount() == 0
    assert shown == []


def test_native_identified_multi_hit_lists_all_layers(
    qtbot, tmp_path, monkeypatch
):
    """多点列举（V10 识别修复）：hits 数组逐条重建，未知层条目被滤除。"""
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    layer = _flagged(document)
    record = layer.features[0]
    shown: list = []
    monkeypatch.setattr(
        "paleo_workbench.ui.workstation.composite_document.QToolTip",
        SimpleNamespace(showText=lambda *args: shown.append(args),
                        hideText=lambda: None),
    )
    document._on_native_identified({
        "hits": [
            {"layer_doc_id": layer.id, "feature_id": record.get("id")},
            {"layer_doc_id": "home_workarea:nope", "feature_id": "ghost"},
        ],
    })
    assert document.identify_results.tree.topLevelItemCount() == 1
    assert "A12" in shown[0][1]


def test_native_identified_reference_snapshot_entry(
    qtbot, tmp_path, monkeypatch
):
    """引用层（导入参考，如参考相图）命中 → 面板条目 + 来源=reference。"""
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot

    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    shown: list = []
    monkeypatch.setattr(
        "paleo_workbench.ui.workstation.composite_document.QToolTip",
        SimpleNamespace(showText=lambda *args: shown.append(args),
                        hideText=lambda: None),
    )
    snapshot = MapLayerSnapshot(
        id="ref_test", name="参考相图", layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
        data_revision=1, style_revision=1,
        features=({"id": "ref_test:0",
                   "geometry": {"type": "Polygon",
                                "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
                   "properties": {"facies": "深水盆地"}},),
        style={}, visible=True, opacity=0.65,
        metadata={"reference": "true"},
    )
    document.layer_manager._layers.append(snapshot)
    document._on_native_identified(
        {"layer_doc_id": "ref_test", "feature_id": "ref_test:0"})
    assert document.identify_results.tree.topLevelItemCount() == 1
    item = document.identify_results.tree.topLevelItem(0)
    assert item.text(0) == "参考相图"
    assert "深水盆地" in shown[0][1]


def test_ensure_identify_layer_current_selects_base_without_edit_layers(
    qtbot, tmp_path
):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    if not document.uses_native_stack:
        pytest.skip("仅原生栈需要置 current")
    assert document.edit_controller.active_layer_id is None
    pushed: list = []
    document.canvas.set_current_layer = pushed.append
    document._ensure_identify_layer_current()
    assert pushed == ["home_workarea:wells_flagged"]
    # 只定识别目标：不得在 edit_controller 里伪造活动层。
    assert document.edit_controller.active_layer_id is None


def test_ensure_identify_layer_current_prefers_edit_over_base(
    qtbot, tmp_path
):
    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    if not document.uses_native_stack:
        pytest.skip("仅原生栈需要置 current")
    controller = document.edit_controller
    controller.create_layer("下层", "polygon")
    upper = controller.create_layer("上层", "polygon")
    controller.set_active_layer(None)
    pushed: list = []
    document.canvas.set_current_layer = pushed.append
    document._ensure_identify_layer_current()
    assert controller.active_layer_id == upper.id
    # 编修层命中时只走既有传播（set_active_layer → canvas），不碰基础层。
    assert pushed == [upper.id]


@pytest.mark.qgis
def test_native_identify_base_end_to_end(qtbot, tmp_path, monkeypatch):
    """真桥：零编修层时原生点击井点 → 面板有条目 + 悬浮含井名。"""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    if not document.uses_native_stack:
        pytest.skip("仅原生栈可做真桥点击")
    document.resize(800, 600)
    document.show()
    document._sync_composition_now()
    qtbot.wait(500)
    layer = _flagged(document)
    record = layer.features[0]
    coords = record["geometry"]["coordinates"]
    shown: list = []
    monkeypatch.setattr(
        "paleo_workbench.ui.workstation.composite_document.QToolTip",
        SimpleNamespace(showText=lambda *args: shown.append(args),
                        hideText=lambda: None),
    )
    document._on_command_requested("identify")
    assert document.edit_controller.active_layer_id is None
    viewport = document.canvas._canvas_viewport()
    assert viewport is not None
    sx, sy = document.canvas.map_to_screen((float(coords[0]), float(coords[1])))
    QTest.mouseClick(viewport, Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(sx), int(sy)))
    qtbot.waitUntil(
        lambda: document.identify_results.tree.topLevelItemCount() == 1,
        timeout=8000,
    )
    assert len(shown) == 1
    assert "A12" in shown[0][1]
