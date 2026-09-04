"""M2 Task 6: 图层树右键菜单自定义动作触发对应请求信号。"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis
from PySide6.QtCore import QCoreApplication, QPoint, QTimer
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QMenu

_FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 1.0]}, "properties": {}}]}


def _layer(layer_id, name, visible=True, metadata=None):
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
    return MapLayerSnapshot(
        id=layer_id, name=name, layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
        data_revision=1, style_revision=1,
        features=(dict(_FC["features"][0]),), style={},
        visible=visible, opacity=1.0,
        metadata=dict(metadata or {}),
    )


def _trigger_menu_action(qtbot, qapp, panel, action_text):
    """右键弹图层树菜单并点选指定动作；返回该动作是否存在。

    offscreen 平台无原生右键合成：事件须发到 viewport（QAbstractScrollArea
    的 ContextMenu 转发路径），菜单经 QgsLayerTreeView::contextMenuEvent →
    menuProvider->createContextMenu()->exec() 真实弹出；动作在 exec 的嵌套
    事件循环里经 singleShot 触发（等价用户点击，trigger 自动关闭菜单）。
    """
    tree = panel.tree_host.tree_view
    state = {"done": False, "found": False}

    def on_menu(menu):
        def trigger():
            state["done"] = True
            for action in menu.actions():
                if action.text() == action_text:
                    state["found"] = True
                    action.trigger()
                    break
            # offscreen 下 programmatic trigger 不会自动退出 QMenu::exec，
            # 显式 close（真实用户点击时由菜单自身处理）。
            menu.close()
        QTimer.singleShot(50, trigger)

    tree.contextMenuAboutToShow.connect(on_menu)
    viewport = next(
        (child for child in tree.children()
         if getattr(child, "objectName", lambda: "")() == "qt_scrollarea_viewport"),
        tree,
    )
    pos = QPoint(5, 5)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos,
                              viewport.mapToGlobal(pos))
    QCoreApplication.sendEvent(viewport, event)
    qtbot.waitUntil(lambda: state["done"], timeout=3000)
    return state["found"]


@pytest.fixture()
def panel_with_layer(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [_layer("doc-a", "井位", metadata={"editable": "true"})])
    canvas.show()
    panel.show()
    qtbot.waitUntil(lambda: panel.tree_row_count() >= 1, timeout=3000)
    panel.select_layer("doc-a")
    return panel


def test_menu_attribute_table_action_emits(qtbot, qapp, panel_with_layer):
    panel = panel_with_layer
    received = []
    panel.attribute_table_requested.connect(received.append)
    found = _trigger_menu_action(qtbot, qapp, panel, "打开属性表")
    assert found, "右键菜单缺少「打开属性表」动作"
    qtbot.waitUntil(lambda: received == ["doc-a"], timeout=2000)


def test_menu_properties_action_emits(qtbot, qapp, panel_with_layer):
    panel = panel_with_layer
    received = []
    panel.properties_requested.connect(received.append)
    found = _trigger_menu_action(qtbot, qapp, panel, "图层属性…")
    assert found, "右键菜单缺少「图层属性…」动作"
    qtbot.waitUntil(lambda: received == ["doc-a"], timeout=2000)


def test_menu_remove_layer_action_emits_request_not_direct_delete(
        qtbot, qapp, panel_with_layer):
    """删除必须走 remove_layer_requested 信号（文档模型落地），非 QGIS 直接删。"""
    panel = panel_with_layer
    received = []
    panel.remove_layer_requested.connect(received.append)
    found = _trigger_menu_action(qtbot, qapp, panel, "删除图层")
    assert found, "右键菜单缺少「删除图层」动作"
    qtbot.waitUntil(lambda: received == ["doc-a"], timeout=2000)
    # 宿主未处理信号时，镜像图层不得被 QGIS 默认动作直接删除
    assert panel.tree_row_count() == 1


def _inspect_menu_action(qtbot, qapp, panel, action_text):
    """右键弹出菜单但不触发，返回匹配动作的 (checkable, checked)；无则 None。

    菜单 exec 关闭后 QAction 随之销毁，状态必须在回调内就地读取。
    """
    tree = panel.tree_host.tree_view
    state = {"done": False, "result": None}

    def on_menu(menu):
        def inspect():
            state["done"] = True
            for action in menu.actions():
                if action.text() == action_text:
                    state["result"] = (action.isCheckable(), action.isChecked())
                    break
            menu.close()
        QTimer.singleShot(50, inspect)

    tree.contextMenuAboutToShow.connect(on_menu)
    viewport = next(
        (child for child in tree.children()
         if getattr(child, "objectName", lambda: "")() == "qt_scrollarea_viewport"),
        tree,
    )
    pos = QPoint(5, 5)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, pos,
                              viewport.mapToGlobal(pos))
    QCoreApplication.sendEvent(viewport, event)
    qtbot.waitUntil(lambda: state["done"], timeout=3000)
    return state["result"]


@pytest.fixture()
def panel_with_reference(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [
        _layer("ref-on", "参与捕捉的引用",
               metadata={"reference": "true", "snap": "true"}),
        _layer("ref-off", "不参与捕捉的引用",
               metadata={"reference": "true", "snap": "false"}),
    ])
    canvas.show()
    panel.show()
    qtbot.waitUntil(lambda: panel.tree_row_count() >= 2, timeout=3000)
    return panel


def test_menu_reference_snap_check_state_follows_authority(
        qtbot, qapp, panel_with_reference):
    """M3 Task 6（M2 移交项）：「参与捕捉」菜单项勾选态投影 Python 权威。"""
    panel = panel_with_reference
    panel.select_layer("ref-on")
    state = _inspect_menu_action(qtbot, qapp, panel, "参与捕捉")
    assert state == (True, True)

    panel.select_layer("ref-off")
    state = _inspect_menu_action(qtbot, qapp, panel, "参与捕捉")
    assert state == (True, False)
