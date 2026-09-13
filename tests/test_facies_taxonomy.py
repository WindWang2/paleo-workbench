# -*- coding: utf-8 -*-
"""相分类词表 + 三级级联选择（grill 共识 Q1~Q8）。

覆盖：词表核心（内置/工程覆盖/geojson 导入/级联查询）、选择器组件
（过滤/任一级可停）、控制器写入（apply_facies_selection 四字段）、
捕获完成回调（feature_captured——绘制完成弹窗的触发源）。
"""
import json

import pytest

pytest.importorskip("PySide6")

from paleo_workbench.mapping.facies_taxonomy import (
    FACIES_LEVEL_KEYS,
    FaciesTaxonomy,
)


# -- 词表核心 ---------------------------------------------------------------


def test_builtin_taxonomy_counts_and_cascade():
    taxonomy = FaciesTaxonomy.builtin()
    n_f, n_s, n_m = taxonomy.counts()
    assert (n_f, n_s, n_m) == (8, 24, 66)
    assert "三角洲" in taxonomy.names("facies")
    subs = taxonomy.names("sub_facies", ("三角洲",))
    assert set(subs) >= {"三角洲前缘", "三角洲平原", "前三角洲"}
    micros = taxonomy.names("micro_facies", ("三角洲", "三角洲前缘"))
    assert set(micros) >= {"分流河道", "天然堤"}
    # 父链断裂（相名不存在）→ 该级全集，不静默清空
    assert taxonomy.names("sub_facies", ("不存在的相",)) == taxonomy.names("sub_facies")


def test_taxonomy_from_geojson_features_builds_hierarchy():
    features = [
        {"properties": {"id": "a", "level": "facies", "facies": "三角洲"}},
        {"properties": {"id": "b", "level": "facies", "facies": "陆棚"}},
        {"properties": {"id": "c", "level": "sub_facies", "facies": "三角洲前缘",
                        "parent_id": "a"}},
        {"properties": {"id": "d", "level": "sub_facies", "facies": "滨外陆棚",
                        "parent_id": "b"}},
        {"properties": {"id": "e", "level": "micro_facies", "facies": "分流河道",
                        "parent_id": "c"}},
        # 孤儿微相（父缺失）→ 跳过
        {"properties": {"id": "f", "level": "micro_facies", "facies": "孤儿",
                        "parent_id": "nope"}},
    ]
    taxonomy = FaciesTaxonomy.from_geojson_features(features)
    assert taxonomy.counts() == (2, 2, 1)
    assert taxonomy.names("micro_facies", ("三角洲", "三角洲前缘")) == ["分流河道"]


def test_taxonomy_project_override_and_fallback():
    from types import SimpleNamespace

    override = SimpleNamespace(
        facies_taxonomy={"source": "project", "tree": {"扇三角洲": {"前缘": {}}}})
    taxonomy = FaciesTaxonomy.from_project(override)
    assert taxonomy.source == "project"
    assert taxonomy.names("facies") == ["扇三角洲"]
    # 无覆盖段 → 内置
    assert FaciesTaxonomy.from_project(SimpleNamespace()).source == "builtin"
    # 空树覆盖 → 同样回落内置（不落成空词表）
    empty = SimpleNamespace(facies_taxonomy={"source": "project", "tree": {}})
    assert FaciesTaxonomy.from_project(empty).source == "builtin"


def test_selection_level_any_stop():
    assert FaciesTaxonomy.selection_level(
        {"facies": "三角洲"}) == "facies"
    assert FaciesTaxonomy.selection_level(
        {"facies": "三角洲", "sub_facies": "三角洲前缘"}) == "sub_facies"
    assert FaciesTaxonomy.selection_level(
        {"facies": "三角洲", "sub_facies": "三角洲前缘",
         "micro_facies": "分流河道"}) == "micro_facies"


# -- 级联选择器组件 -----------------------------------------------------------


def test_cascade_selector_filters_and_stops_any_level(qtbot):
    from paleo_workbench.ui.workstation.facies_selector import (
        FaciesCascadeSelector,
    )

    selector = FaciesCascadeSelector(FaciesTaxonomy.builtin())
    qtbot.addWidget(selector)
    # 相级全量；子级首项为空（不填——任一级可停）
    assert selector._combos["facies"].count() == 8
    assert selector._combos["sub_facies"].itemText(0) == ""
    # 选相 → 亚相过滤为该相子项 + 空项
    selector._combos["facies"].setCurrentText("三角洲")
    subs = [selector._combos["sub_facies"].itemText(i)
            for i in range(selector._combos["sub_facies"].count())]
    assert subs[0] == "" and "三角洲前缘" in subs and "滨外陆棚" not in subs
    # 选到亚相 → 微相过滤
    selector._combos["sub_facies"].setCurrentText("三角洲前缘")
    micros = [selector._combos["micro_facies"].itemText(i)
              for i in range(selector._combos["micro_facies"].count())]
    assert "分流河道" in micros
    # 只选相即可确定（selection 返回，子级空）
    selector._combos["sub_facies"].setCurrentIndex(0)
    selection = selector.selection()
    assert selection["facies"] == "三角洲"
    assert selection["sub_facies"] == ""
    # set_selection 从要素属性恢复
    selector.set_selection(
        {"facies": "三角洲", "sub_facies": "三角洲前缘", "micro_facies": "分流河道"})
    assert selector.selection()["micro_facies"] == "分流河道"


def test_dialog_cancel_returns_none(qtbot, monkeypatch):
    """Q6-a：取消/关闭不写属性——对话框层由 reject 语义保证（此处钉
    selection 组装与 level 字段）。"""
    from paleo_workbench.ui.workstation.facies_selector import (
        FaciesSelectionDialog,
    )

    dialog = FaciesSelectionDialog(FaciesTaxonomy.builtin())
    qtbot.addWidget(dialog)
    dialog._selector.set_selection({"facies": "三角洲"})
    selection = dialog.selection()
    assert selection["level"] == "facies"
    assert selection["sub_facies"] == ""


# -- 控制器：捕获回调 + 选择写入 -----------------------------------------------


def _controller():
    from paleo_workbench.ui.workstation.composite_editing import (
        CompositeEditController,
    )

    return CompositeEditController()


def test_capture_tool_notifies_captured_feature():
    from paleo_workbench.mapping.map_tools import AddPolygonTool

    controller = _controller()
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    captured: list[str] = []
    controller.activate_tool("add_polygon")
    tool = controller.tools.active_tool
    assert tool is not None
    # 直接喂点（fallback 路径）→ on_captured 收到新要素 id
    tool._on_captured = captured.append
    assert tool.mouse_press((0.0, 0.0))
    assert tool.mouse_press((10.0, 0.0))
    assert tool.double_click((0.0, 10.0))
    assert len(captured) == 1
    feature_id = captured[0]
    assert layer.edit_session.feature(feature_id).geometry["type"] == "Polygon"


def test_controller_emits_feature_captured_for_facies_layer(qtbot):
    controller = _controller()
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    controller.activate_tool("add_polygon")
    events: list[tuple[str, str]] = []
    controller.feature_captured.connect(
        lambda lid, fid: events.append((lid, fid)))
    tool = controller.tools.active_tool
    tool.mouse_press((0.0, 0.0))
    tool.mouse_press((10.0, 0.0))
    tool.double_click((5.0, 10.0))
    assert len(events) == 1
    assert events[0][0] == layer.id
    # 非相带层（自定义面层）不触发
    plain = controller.create_layer("自定义面", "polygon")
    controller.set_active_layer(plain.id)
    controller.start_editing()
    controller.activate_tool("add_polygon")
    events.clear()
    tool = controller.tools.active_tool
    tool.mouse_press((0.0, 0.0))
    tool.mouse_press((10.0, 0.0))
    tool.double_click((5.0, 10.0))
    assert events == []


def test_apply_facies_selection_writes_three_names_and_level():
    controller = _controller()
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    from paleo_workbench.mapping.map_tools import AddPolygonTool

    tool = AddPolygonTool(layer.edit_session)
    tool.mouse_press((0.0, 0.0))
    tool.mouse_press((10.0, 0.0))
    tool.double_click((0.0, 10.0))
    feature_id = layer.edit_session.features()[0].feature_id

    ok, reason = controller.apply_facies_selection(
        layer.id, feature_id,
        {"facies": "三角洲", "sub_facies": "三角洲前缘", "micro_facies": ""})
    assert ok, reason
    attributes = layer.edit_session.feature(feature_id).attributes
    assert attributes["facies"] == "三角洲"
    assert attributes["sub_facies"] == "三角洲前缘"
    assert attributes["micro_facies"] == ""
    assert attributes["level"] == "sub_facies"


# -- 相带模板分级变体 -----------------------------------------------------------


def test_facies_template_variants_and_level_helper():
    from paleo_workbench.ui.workstation.composite_editing import (
        FACIES_TEMPLATE_KEYS,
        _TEMPLATE_BY_KEY,
        facies_template_level,
    )

    assert FACIES_TEMPLATE_KEYS == {"facies", "facies_sub", "facies_micro"}
    assert facies_template_level("facies_sub") == "sub_facies"
    assert facies_template_level("facies_micro") == "micro_facies"
    assert facies_template_level("fault") is None
    # 三个变体同字段（词表级联三字段 + level + parent_id 在位）
    for key in sorted(FACIES_TEMPLATE_KEYS):
        names = {field.name for field in _TEMPLATE_BY_KEY[key].fields}
        assert {"facies", "sub_facies", "micro_facies", "level",
                "parent_id"} <= names


# -- 纹理分类渲染（grill 后续：按相类别纹理渲染） --------------------------------


def _project(tmp_path):
    from paleo_workbench.project.domain import WellEntity
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0,
                   project_x=1.0, project_y=2.0)
    )
    return project


def test_pattern_map_covers_builtin_taxonomy_facies():
    """内置词表 8 相全部有 SVG 纹理映射（相图按类别纹理渲染的完备性）。"""
    from paleo_workbench.mapping.facies_patterns import (
        FACIES_PATTERN_DIR,
        pattern_id_for_facies,
        pattern_path_for_facies,
    )

    taxonomy = FaciesTaxonomy.builtin()
    for name in taxonomy.names("facies"):
        pattern_id = pattern_id_for_facies(name)
        assert pattern_id, f"相「{name}」缺少纹理映射"
        assert pattern_path_for_facies(name) is not None, (
            f"相「{name}」的纹理文件缺失：{pattern_id}.svg")
    assert FACIES_PATTERN_DIR.is_dir()


def test_categorized_style_field_override_for_level_layers():
    """分级图层强制按目标字段分类（亚相图 sub_facies），不交叉回退。"""
    from paleo_workbench.ui.workstation.stage_actions import (
        _categorized_facies_style,
    )

    features = [
        {"facies": "三角洲", "sub_facies": "三角洲前缘"},
        {"facies": "三角洲", "sub_facies": "三角洲平原"},
    ]
    style = _categorized_facies_style(features, field="sub_facies")
    assert style["renderer"] == "categorized"
    assert style["field"] == "sub_facies"
    assert set(style["categories"]) == {"三角洲前缘", "三角洲平原"}
    # 亚相里只有显式映射的类带纹理（三角洲前缘→delta）；其余纯色分类。
    assert dict(style["fill_patterns"]) == {"三角洲前缘": "delta"}


def test_facies_layer_auto_pattern_style_on_content_change(qtbot, tmp_path):
    """指定相带后图层自动应用分类纹理样式；自定义符号不接管。"""
    from paleo_workbench.ui.workstation.composite_document import (
        CompositeDocument,
    )

    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    controller = document.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    from paleo_workbench.mapping.vector_layer import VectorFeature

    polygon = {"type": "Polygon",
               "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    session = layer.edit_session
    session.add_feature(VectorFeature("f1", dict(polygon),
                                      {"facies": "三角洲", "confidence": "中"}))
    session.add_feature(VectorFeature("f2", dict(polygon),
                                      {"facies": "碳酸盐台地", "confidence": "中"}))
    controller.content_changed.emit(layer.id)

    style = dict(layer.style)
    assert style["renderer"] == "categorized"
    assert style["field"] == "facies"
    assert set(style["categories"]) == {"三角洲", "碳酸盐台地"}
    assert dict(style["fill_patterns"]) == {
        "三角洲": "delta", "碳酸盐台地": "carbonate_platform"}

    # 类别集合不变（纯几何编辑）→ 不重置样式
    applied_style = dict(layer.style)
    session.add_feature(VectorFeature("f3", dict(polygon),
                                      {"facies": "三角洲", "confidence": "中"}))
    controller.content_changed.emit(layer.id)
    assert layer.style == applied_style

    # 用户自定义分类符号（类别不同）→ 不接管
    custom = dict(applied_style)
    custom["categories"] = {"我的分类": "#ff0000"}
    controller.set_layer_style(layer.id, custom)
    session.add_feature(VectorFeature("f4", dict(polygon),
                                      {"facies": "潟湖", "confidence": "中"}))
    controller.content_changed.emit(layer.id)
    assert "潟湖" not in (layer.style.get("categories") or {})


# -- 检查器按钮 ----------------------------------------------------------------


def test_inspector_feature_page_has_assign_facies(qtbot):
    from paleo_workbench.ui.workstation.inspector import WorkstationInspector

    panel = WorkstationInspector()
    qtbot.addWidget(panel)
    requested: list[dict] = []
    panel.assign_facies_requested.connect(requested.append)
    panel.show_feature({
        "kind": "feature",
        "object": {"layer_id": "composite:layer_x", "feature_id": "f1",
                   "layer_name": "相带", "geometry_type": "Polygon",
                   "attributes": {"facies": "三角洲"}, "editable": True},
        "layer_id": "composite:layer_x",
    })
    from PySide6.QtWidgets import QPushButton

    assign_buttons = [b for b in panel.findChildren(QPushButton)
                      if b.text() == "指定相带…"]
    assert assign_buttons, "检查器要素页缺少「指定相带…」按钮"
    assign_buttons[-1].click()
    assert requested and requested[-1]["layer_id"] == "composite:layer_x"


# -- 词表资源完整性 ------------------------------------------------------------


def test_builtin_taxonomy_resource_is_valid_json_with_levels():
    from pathlib import Path

    path = (Path(__file__).parent.parent / "paleo_workbench" / "resources"
            / "facies_taxonomy.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["_meta"]["levels"] == ["相", "亚相", "微相"]
    taxonomy = FaciesTaxonomy(payload["tree"])
    assert taxonomy.counts() == (8, 24, 66)
    assert FACIES_LEVEL_KEYS == ("facies", "sub_facies", "micro_facies")
