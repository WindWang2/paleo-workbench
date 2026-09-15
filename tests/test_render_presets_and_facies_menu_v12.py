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
