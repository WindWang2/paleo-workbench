"""M2 相带调色板 + 吸色管 + 数字快捷键（无桥 fallback 路径）。

对应 docs/development/paleo-ui-workbench/03-tdd-ui-test-plan.md 矩阵 M2 与
01-interaction-specs.md S2 验收标准。D6 前置实证用例在文件首（gate）。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget

from paleo_workbench.mapping.facies_taxonomy import FaciesTaxonomy

QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _restore_override_cursor():
    """吸色管测试可能向 QApplication 全局 override cursor 栈压入十字光标
    （P1-5 review）——栈不随 widget 销毁复原，逐用例清空防跨用例污染。"""
    from PySide6.QtGui import QGuiApplication

    yield
    while QGuiApplication.overrideCursor() is not None:
        QGuiApplication.restoreOverrideCursor()


# ---------------------------------------------------------------------------
# D6 前置实证：同键跨快捷键上下文分发（gate；结论回写 00-decisions）
# ---------------------------------------------------------------------------

def test_digit_key_scope_and_hub_guard(qtbot, monkeypatch):
    """D6 冲突消解实证（offscreen 修正案）。

    offscreen 平台无活动窗口，QTest 模拟键不驱动 QShortcutMap（既有仓库
    经验：tests/test_keyboard_shortcuts.py 注释），跨上下文路由无法在此
    环境实证。改为验证结构契约：
    1. 画布域 WidgetWithChildrenShortcut 与 ApplicationShortcut 可共存
       （两者同时 enabled 且键序列一致）；
    2. 双保险：hub 页导航回调在绘图工具激活期被守卫短路（即便双触发，
       hub 也不切页）。
    """
    root = QWidget()
    qtbot.addWidget(root)
    child = QWidget(root)
    child.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    root.resize(200, 120)
    root.show()
    qtbot.wait(20)

    app_sc = QShortcut(QKeySequence("7"), root)
    app_sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
    widget_sc = QShortcut(QKeySequence("7"), child)
    widget_sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    # 结构契约：两者同时存活、同键、各自作用域正确。
    assert app_sc.key().toString() == widget_sc.key().toString() == "7"
    assert widget_sc.parent() is child

    from paleo_workbench.ui.app_shell import AppShell

    navigated: list[int] = []
    shell = AppShell.__new__(AppShell)  # 不跑完整 __init__（重）
    monkeypatch.setattr(AppShell, "navigate_to",
                        lambda self, idx, *a, **k: navigated.append(idx))
    shell.workstation = None  # 无工作站 → 守卫放行
    shell._shortcut_switch_page(2)
    assert navigated == [2]
    shell.workstation = SimpleNamespace(
        composite=SimpleNamespace(_digit_keys_active=lambda: True))
    shell._shortcut_switch_page(3)
    assert navigated == [2]  # 绘图激活期被 D6 守卫短路


# ---------------------------------------------------------------------------
# FaciesBrushContext（当前相带画刷上下文）
# ---------------------------------------------------------------------------

def test_brush_context_equip_and_clear(qtbot):
    from paleo_workbench.ui.workstation.facies_selector import FaciesBrushContext

    brush = FaciesBrushContext()
    assert not brush.is_armed
    events: list[dict] = []
    brush.equipped_changed.connect(events.append)
    brush.equip({"facies": "三角洲", "sub_facies": "分流河道",
                 "micro_facies": ""})
    assert brush.is_armed
    assert brush.selection()["facies"] == "三角洲"
    assert brush.selection()["level"] == "sub_facies"
    assert len(events) == 1
    brush.clear()
    assert not brush.is_armed
    assert len(events) == 2


def test_brush_context_equip_same_selection_no_spam(qtbot):
    from paleo_workbench.ui.workstation.facies_selector import FaciesBrushContext

    brush = FaciesBrushContext()
    events: list[dict] = []
    brush.equipped_changed.connect(events.append)
    payload = {"facies": "潮坪", "sub_facies": "", "micro_facies": ""}
    brush.equip(payload)
    brush.equip(dict(payload))
    assert len(events) == 1  # 幂等装备不重复广播


# ---------------------------------------------------------------------------
# 调色板部件
# ---------------------------------------------------------------------------

def _palette(qtbot, taxonomy=None):
    from paleo_workbench.ui.components.facies_palette_widget import (
        FaciesPaletteWidget,
    )
    from paleo_workbench.ui.workstation.facies_selector import FaciesBrushContext

    widget = FaciesPaletteWidget()
    qtbot.addWidget(widget)
    widget.set_brush(FaciesBrushContext(widget))
    widget.set_taxonomy(taxonomy or FaciesTaxonomy.builtin())
    widget.resize(320, 560)
    widget.show()
    qtbot.wait(20)
    return widget


def test_palette_renders_taxonomy_sections(qtbot):
    taxonomy = FaciesTaxonomy.builtin()
    widget = _palette(qtbot, taxonomy)
    top_names = taxonomy.names("facies")
    assert widget.section_count() == len(top_names)
    # 亚相格总数 = 各相的亚相数之和
    total = sum(len(taxonomy.names("sub_facies", (name,))) for name in top_names)
    assert widget.swatch_count() == total


def test_palette_click_equips_brush(qtbot):
    widget = _palette(qtbot)
    target = widget.favorites()[0]
    widget.equip_by_selection(target["selection"])
    assert widget._brush.selection()["facies"] == target["selection"]["facies"]
    assert widget.equip_label.text().contains(target["selection"]["facies"]) \
        if hasattr(widget.equip_label.text(), "contains") \
        else target["selection"]["facies"] in widget.equip_label.text()


def test_palette_colors_match_categorized_renderer(qtbot):
    from paleo_workbench.ui.components.facies_palette_widget import facies_color
    from paleo_workbench.ui.workstation.stage_actions import (
        _categorized_facies_style,
    )

    for name in FaciesTaxonomy.builtin().names("facies"):
        style = _categorized_facies_style(
            [{"properties": {"facies": name}}])
        categories = style.get("categories") or {}
        assert categories.get(name), f"renderer produced no category for {name}"
        assert facies_color(name).lower() == str(categories[name]).lower(), (
            f"palette/renderer color mismatch for {name}")


def test_palette_eyedropper_button_toggles(qtbot):
    widget = _palette(qtbot)
    states: list[bool] = []
    widget.eyedropper_toggled.connect(states.append)
    qtbot.mouseClick(widget.eyedropper_button, Qt.MouseButton.LeftButton)
    qtbot.mouseClick(widget.eyedropper_button, Qt.MouseButton.LeftButton)
    assert states == [True, False]


def test_palette_favorites_first_nine(qtbot):
    widget = _palette(qtbot)
    favorites = widget.favorites()
    assert 1 <= len(favorites) <= 9
    widget.equip_by_index(2)
    assert widget._brush.selection()["facies"] == favorites[2]["selection"]["facies"]


# ---------------------------------------------------------------------------
# 吸色管（数据路径纯函数 + 部件状态）
# ---------------------------------------------------------------------------

def _result(layer_id, attrs, name="层"):
    return {
        "layer_id": layer_id, "layer_name": name, "feature_id": "f1",
        "geometry_type": "Polygon", "attributes": dict(attrs),
        "source": "composite", "template": "facies", "editable": True,
    }


def test_eyedropper_pick_first_facies_result(qtbot):
    from paleo_workbench.ui.components.facies_eyedropper import pick_facies_at

    hits = [
        _result("L0", {"id": "w1"}),  # 非相带要素 → 跳过
        _result("L1", {"facies": "三角洲", "sub_facies": "分流河道",
                       "micro_facies": "", "level": "sub_facies"}),
        _result("L2", {"facies": "潮坪"}),
    ]
    picked = pick_facies_at((3.0, 3.0), lambda point: hits)
    assert picked is not None
    assert picked["facies"] == "三角洲"
    assert picked["sub_facies"] == "分流河道"
    assert picked["layer_id"] == "L1"
    assert picked["color"]  # 分类渲染色随取


def test_eyedropper_empty_click_returns_none(qtbot):
    from paleo_workbench.ui.components.facies_eyedropper import pick_facies_at

    assert pick_facies_at((0.0, 0.0), lambda point: []) is None


def test_eyedropper_skips_non_facies_layers(qtbot):
    from paleo_workbench.ui.components.facies_eyedropper import pick_facies_at

    hits = [_result("wells", {"depth": 100}), _result("seis", {"amp": 3})]
    assert pick_facies_at((1.0, 1.0), lambda point: hits) is None


# ---------------------------------------------------------------------------
# 集成：CompositeDocument 画刷优先 / 吸管点击 / 数字键生命周期
# ---------------------------------------------------------------------------

def _composite(qtbot, monkeypatch, project=None):
    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(project or ProjectDocument.new("画刷测试"))
    qtbot.addWidget(doc)
    doc.resize(1200, 800)
    doc.show()
    qtbot.wait(30)

    # 相带模态对话框在此路径内局部 import —— 补丁目标是定义模块。
    class _Bomb:
        def __init__(self, *a, **k):
            raise AssertionError("modal dialog constructed")

    monkeypatch.setattr(
        "paleo_workbench.ui.workstation.facies_selector."
        "FaciesSelectionDialog", _Bomb)
    return doc


def _capture_polygon(doc) -> tuple[str, str]:
    """在 doc 上数字化一个三角带面，返回 (layer_id, feature_id)。"""
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    controller.activate_tool("add_polygon")
    tool = controller.tools.active_tool
    captured: list[tuple[str, str]] = []
    controller.feature_captured.connect(
        lambda lid, fid: captured.append((lid, fid)))
    tool.mouse_press((0.0, 0.0))
    tool.mouse_press((10.0, 0.0))
    tool.double_click((5.0, 10.0))
    assert len(captured) == 1
    return captured[0]


def test_captured_feature_auto_assigned_no_dialog(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    doc.facies_brush.equip({"facies": "三角洲", "sub_facies": "河口坝",
                            "micro_facies": ""})
    layer_id, feature_id = _capture_polygon(doc)
    layer = doc.edit_controller.layer(layer_id)
    feature = layer.edit_session.feature(feature_id)
    assert feature.attributes["facies"] == "三角洲"
    assert feature.attributes["sub_facies"] == "河口坝"
    assert feature.attributes["level"] == "sub_facies"
    # 单一撤销命令（一次 undo 完整回滚属性写入）
    session = layer.edit_session
    assert session is not None
    depth_before = len(session.undo_stack)
    session.undo()
    assert len(session.undo_stack) == depth_before - 1


def test_continuous_assignment_three_features(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    doc.facies_brush.equip({"facies": "潮坪", "sub_facies": "砂坪",
                            "micro_facies": ""})
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    controller.activate_tool("add_polygon")
    tool = controller.tools.active_tool
    ids: list[str] = []
    controller.feature_captured.connect(
        lambda lid, fid: ids.append(fid))
    for offset in range(3):
        tool.mouse_press((float(offset), 0.0))
        tool.mouse_press((float(offset) + 10.0, 0.0))
        tool.double_click((float(offset) + 5.0, 10.0))
    assert len(ids) == 3
    for fid in ids:
        assert layer.edit_session.feature(fid).attributes["facies"] == "潮坪"
    # 每要素一条撤销命令
    assert len(layer.edit_session.undo_stack) >= 3


def test_brush_off_falls_back_to_dialog(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    assert not doc.facies_brush.is_armed
    routed: list[tuple[str, str]] = []
    monkeypatch.setattr(
        doc, "_assign_facies_dialog",
        lambda lid, fid: routed.append((lid, fid)))
    layer_id, feature_id = _capture_polygon(doc)
    assert routed == [(layer_id, feature_id)]  # 未装备 → 既有模态路径


def test_eyedropper_click_equips_from_map_feature(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    # 建面阶段的捕获本应走模态（未装备画刷）——吸色管测试不关心该弹窗，
    # 置空后捕获保持属性空白，再手工赋属性作为"地图上已有相带"。
    monkeypatch.setattr(doc, "_assign_facies_dialog", lambda *a: None)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    controller.activate_tool("add_polygon")
    tool = controller.tools.active_tool
    captured: list[str] = []
    controller.feature_captured.connect(
        lambda lid, fid: captured.append(fid))
    tool.mouse_press((0.0, 0.0))
    tool.mouse_press((10.0, 0.0))
    tool.double_click((5.0, 10.0))
    fid = captured[0]
    controller.apply_facies_selection(layer.id, fid, {
        "facies": "潟湖", "sub_facies": "", "micro_facies": ""})

    doc.set_eyedropper_active(True)
    doc.handle_eyedropper_click((5.0, 2.0))
    assert doc.facies_brush.is_armed
    assert doc.facies_brush.selection()["facies"] == "潟湖"


def test_eyedropper_empty_click_keeps_brush(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    doc.facies_brush.equip({"facies": "陆棚", "sub_facies": "",
                            "micro_facies": ""})
    doc.set_eyedropper_active(True)
    statuses: list[str] = []
    doc.status_message.connect(statuses.append)
    doc.handle_eyedropper_click((999.0, 999.0))
    assert doc.facies_brush.selection()["facies"] == "陆棚"
    assert any("未命中" in s for s in statuses)


def test_digit_keys_bound_only_while_drawing(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    controller.activate_tool("add_polygon")
    qtbot.wait(30)
    assert doc._digit_keys_active()
    doc.setFocus()
    doc.facies_brush.clear()
    qtbot.keyClick(doc, Qt.Key.Key_3)
    assert doc.facies_brush.is_armed  # 绘图工具激活期数字键装备画刷

    controller.activate_tool("pan")
    qtbot.wait(30)
    assert not doc._digit_keys_active()
    doc.facies_brush.clear()
    qtbot.keyClick(doc, Qt.Key.Key_3)
    assert not doc.facies_brush.is_armed  # 工具退出后数字键不触发


def test_digit_keys_equip_favorites_index(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    controller.activate_tool("add_polygon")
    qtbot.wait(30)
    doc.setFocus()
    qtbot.keyClick(doc, Qt.Key.Key_1)
    favorites = doc.facies_palette.favorites()
    assert doc.facies_brush.selection()["facies"] == favorites[0]["selection"]["facies"]
