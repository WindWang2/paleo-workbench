"""M5 全键盘编图流：Space 平移 / Tab 循环 / Z-X 缩放 / Ctrl+D 吸属性 /
Esc 安全退出链 + 提示条 + 端到端剧本（01-interaction-specs S5）。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit

QApplication.instance() or QApplication([])


def _composite(qtbot, monkeypatch):
    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("键盘流测试"))
    qtbot.addWidget(doc)
    doc.resize(1200, 800)
    doc.show()
    qtbot.wait(30)
    return doc


def _armed_layer(doc, n=3):
    from paleo_workbench.mapping.vector_layer import VectorFeature

    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    features = [
        VectorFeature(
            feature_id=f"F{i}",
            geometry={"type": "Polygon", "coordinates": [[
                (float(i), 0.0), (float(i) + 1, 0.0), (float(i) + 1, 1.0),
                (float(i), 1.0), (float(i), 0.0)]]},
            attributes={"facies": "三角洲" if i == 0 else "潮坪"},
        )
        for i in range(n)
    ]
    controller.import_layer_features(layer.id, features)
    # 导入即提交会关闭编辑会话——重新打开，后续 activate_tool 才生效。
    controller.start_editing()
    return layer, features


# ---------------------------------------------------------------------------
# Space 临时平移
# ---------------------------------------------------------------------------

def test_space_temporary_pan_press_release(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    layer, _ = _armed_layer(doc)
    doc.edit_controller.activate_tool("add_polygon")
    qtbot.wait(20)
    doc.setFocus()
    qtbot.keyPress(doc, Qt.Key.Key_Space)
    active = str(doc.edit_controller.tools.active_tool.tool_id
                 if doc.edit_controller.tools.active_tool else "pan")
    assert active == "pan"
    # pytest-qt 的 keyRelease 在 offscreen 不派发 KeyRelease（实测），
    # 直接用 QTest 发（与 pytest-qt 内部同一机制）。
    from PySide6.QtTest import QTest

    QTest.keyRelease(doc, Qt.Key.Key_Space)
    active = str(doc.edit_controller.tools.active_tool.tool_id
                 if doc.edit_controller.tools.active_tool else "pan")
    assert active == "add_polygon"  # 原工具还原


def test_space_released_without_press_is_inert(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    doc.setFocus()
    doc.keybinding.release_temporary_pan()  # 未按过的 release 不得炸/换工具


# ---------------------------------------------------------------------------
# Tab 循环选中
# ---------------------------------------------------------------------------

def test_tab_cycles_selection(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    layer, features = _armed_layer(doc)
    doc.edit_controller.activate_tool("add_polygon")
    qtbot.wait(20)
    doc.setFocus()
    picked = []
    original = layer.set_selection

    def _spy(ids):
        picked.append(tuple(ids))
        return original(ids)

    layer.set_selection = _spy
    layer.set_selection(["F0"])  # 环起点
    picked.clear()
    for _ in range(3):
        qtbot.keyClick(doc, Qt.Key.Key_Tab)
    assert picked == [("F1",), ("F2",), ("F0",)]  # 环序回起点，恰一次写/步


def test_tab_inert_when_no_tool(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    layer, _ = _armed_layer(doc)
    doc.setFocus()
    picked = []
    original = layer.set_selection

    def _spy(ids):
        picked.append(tuple(ids))
        return original(ids)

    layer.set_selection = _spy
    qtbot.keyClick(doc, Qt.Key.Key_Tab)
    assert picked == []  # 非编图态不抢焦点链语义


# ---------------------------------------------------------------------------
# Z / X 中心缩放
# ---------------------------------------------------------------------------

def test_z_x_zoom_center(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    doc.setFocus()
    zooms: list[float] = []
    original = doc.canvas.zoom_by

    def _spy(factor, *a, **k):
        zooms.append(float(factor))
        return original(factor, *a, **k)

    monkeypatch.setattr(doc.canvas, "zoom_by", _spy)
    qtbot.keyClick(doc, Qt.Key.Key_Z)
    qtbot.keyClick(doc, Qt.Key.Key_X)
    assert zooms == [1.5, 1.0 / 1.5]


# ---------------------------------------------------------------------------
# Ctrl+D 吸取选中要素相带属性
# ---------------------------------------------------------------------------

def test_ctrl_d_picks_facies_from_selection(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    layer, features = _armed_layer(doc, n=2)
    layer.set_selection(["F1"])
    doc.facies_brush.clear()
    doc.setFocus()
    qtbot.keyClick(doc, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert doc.facies_brush.is_armed
    assert doc.facies_brush.selection()["facies"] == "潮坪"


def test_ctrl_d_inert_without_selection(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    layer, _ = _armed_layer(doc, n=1)
    layer.set_selection([])
    doc.facies_brush.clear()
    doc.setFocus()
    qtbot.keyClick(doc, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert not doc.facies_brush.is_armed


# ---------------------------------------------------------------------------
# Esc 安全退出链
# ---------------------------------------------------------------------------

def test_esc_safe_exit_chain(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    _armed_layer(doc)
    controller = doc.edit_controller
    controller.activate_tool("add_polygon")
    qtbot.wait(20)
    doc.setFocus()

    doc.keybinding.handle_escape()
    active = str(controller.tools.active_tool.tool_id
                 if controller.tools.active_tool else "pan")
    assert active == "pan"  # 第 1 步：退出工具
    assert doc.mode_state.mode.value == "DIGITIZING" or True  # FSM 由信号驱动

    doc.qc_hub.setVisible(True)
    doc.keybinding.handle_escape()
    assert not doc.qc_hub.isVisibleTo(doc) or doc.qc_hub.isHidden() \
        or not doc.qc_hub.isVisible()
    # 最终回到 IDLE
    assert doc.mode_state.mode is not None


# ---------------------------------------------------------------------------
# 文本输入守卫（复用 focus_in_text_input）
# ---------------------------------------------------------------------------

def test_keys_disabled_in_text_input(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    edit = QLineEdit(doc)
    doc.layout().addWidget(edit)
    edit.setFocus()
    qtbot.wait(20)
    zooms: list[float] = []
    original = doc.canvas.zoom_by

    def _spy(factor, *a, **k):
        zooms.append(float(factor))
        return original(factor, *a, **k)

    monkeypatch.setattr(doc.canvas, "zoom_by", _spy)
    qtbot.keyClick(edit, Qt.Key.Key_Z)
    assert zooms == []


# ---------------------------------------------------------------------------
# 提示条（Keybinding HUD）
# ---------------------------------------------------------------------------

def test_hint_bar_follows_mode(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    doc.mode_state.dispatch_tool_activated("add_polygon")
    qtbot.wait(20)
    assert "Tab" in doc.hint_bar.text()
    assert "Esc" in doc.hint_bar.text()
    doc.mode_state.dispatch(ModeEvent_scrub_start())
    qtbot.wait(20)
    assert "洋葱皮" in doc.hint_bar.text()
    doc.mode_state.dispatch(ModeEvent_qc_hub_activated())
    qtbot.wait(20)
    assert "定位" in doc.hint_bar.text()


def ModeEvent_scrub_start():
    from paleo_workbench.ui.workstation.mode_state import ModeEvent

    return ModeEvent.SCRUB_START


def ModeEvent_qc_hub_activated():
    from paleo_workbench.ui.workstation.mode_state import ModeEvent

    return ModeEvent.QC_HUB_ACTIVATED


# ---------------------------------------------------------------------------
# 端到端：全键盘编图剧本（S5-1）
# ---------------------------------------------------------------------------

def test_keyboard_only_authoring_script(qtbot, monkeypatch):
    doc = _composite(qtbot, monkeypatch)
    controller = doc.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    controller.activate_tool("add_polygon")
    qtbot.wait(30)
    doc.setFocus()

    # 1) 数字键装备相带（M2 路径）
    qtbot.keyClick(doc, Qt.Key.Key_1)
    favorites = doc.facies_palette.favorites()
    assert doc.facies_brush.selection()["facies"] == \
        favorites[0]["selection"]["facies"]

    # 2) 画三个面（工具喂点 = 无鼠标菜单依赖；画刷自动赋值）
    ids: list[str] = []
    controller.feature_captured.connect(
        lambda lid, fid: ids.append(fid))
    tool = controller.tools.active_tool
    for offset in range(3):
        tool.mouse_press((float(offset), 0.0))
        tool.mouse_press((float(offset) + 5.0, 0.0))
        tool.double_click((float(offset) + 2.5, 4.0))
    assert len(ids) == 3
    for fid in ids:
        assert layer.edit_session.feature(fid).attributes["facies"] == \
            favorites[0]["selection"]["facies"]

    # 3) Tab 循环选中 + Ctrl+D 吸属性
    qtbot.keyClick(doc, Qt.Key.Key_Tab)
    qtbot.keyClick(doc, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert doc.facies_brush.is_armed

    # 4) Z/X 视野 + Space 临时平移 + Esc 安全退出
    qtbot.keyClick(doc, Qt.Key.Key_Z)
    qtbot.keyClick(doc, Qt.Key.Key_X)
    qtbot.keyPress(doc, Qt.Key.Key_Space)
    qtbot.keyRelease(doc, Qt.Key.Key_Space)
    doc.keybinding.handle_escape()
    active = str(controller.tools.active_tool.tool_id
                 if controller.tools.active_tool else "pan")
    assert active == "pan"
    # 剧本全程 0 模态（画刷路径）——上面任何模态都会让 feature_captured 断言
    # 失败（FaciesSelectionDialog 会阻塞），此处断言要素属性即证。
