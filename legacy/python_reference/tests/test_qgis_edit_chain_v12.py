# -*- coding: utf-8 -*-
"""V12 M0-3：编辑链路端到端（真桥）。

钉死编辑工具链缺陷 D-B：宿主在「新建草稿 → 开始编辑 → 激活节点编辑」这条
自然路径上必须把该层推成**画布当前层**——桥侧 ``editLayer()`` 要求
``canvas->currentLayer()`` 属于会话集合，否则顶点工具退化成 v1 回调，
而原生会话下 Python 工具拿不到 session，拖动变成静默失败（几何不动、
没有任何提示）。

修复前实测：该路径上桥侧接受的 ``set_current_layer`` 调用数为 **0**
（首次推送发生在镜像发布之前被拒，且无人重试）。
"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

_RING = [[(4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0), (4.0, 4.0)]]


def _document(qtbot):
    from paleo_workbench.project.models import ProjectDocument
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    doc = CompositeDocument(ProjectDocument.new("t"))
    qtbot.addWidget(doc)
    doc.resize(900, 600)
    doc.show()
    return doc


def _draft_with_feature(qtbot):
    """生产顺序建一张可编辑草稿（含一个面要素）并返回 (doc, controller, layer)。"""
    from paleo_workbench.mapping.vector_layer import VectorFeature

    doc = _document(qtbot)
    controller = doc.edit_controller
    layer = controller.create_layer("相带草稿", "polygon")
    controller.import_layer_features(layer.id, [
        VectorFeature(feature_id="f1",
                      geometry={"type": "Polygon", "coordinates": _RING},
                      attributes={}),
    ])
    doc._sync_composition_now()
    return doc, controller, layer


def test_start_editing_pushes_canvas_current_layer(qtbot):
    """开始编辑后，画布当前层 == 会话层（这是 v2 顶点工具的前提）。"""
    doc, controller, layer = _draft_with_feature(qtbot)
    controller.set_active_layer(layer.id)
    assert doc.canvas.current_layer_doc_id() == layer.id, (
        "发布后的重推未生效：画布当前层未就位，节点编辑会走 v1 静默路径")

    controller.start_editing()
    assert controller.native_editing.is_open(layer.id)
    assert doc.canvas.current_layer_doc_id() == layer.id


def test_vertex_tool_gets_canvas_current_layer_and_drag_moves_geometry(qtbot):
    """完整用户路径：建草稿 → 开始编辑 → 节点编辑 → 拖动顶点 → 几何改变。

    D-A（MSVC 求值顺序崩溃）与 D-B（当前层未推送）任缺其一，本用例都过不去：
    前者让按下即崩，后者让拖动静默无效。
    """
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtTest import QTest

    doc, controller, layer = _draft_with_feature(qtbot)
    controller.set_active_layer(layer.id)
    controller.start_editing()
    assert controller.native_editing.is_open(layer.id)

    # 视口取画布的无名直接子控件：桥把画布按 QWidget 包装，shiboken 对同一
    # 地址只认首次包装类型，`viewport()` 在宿主路径不可达（见 shim 的
    # `_canvas_viewport`）。事件发给画布控件本身不会到达地图工具。
    doc.canvas.set_extent((0.0, 0.0, 10.0, 10.0))
    qtbot.wait(150)
    viewport = doc.canvas._canvas_viewport()
    assert viewport is not None

    controller.activate_tool("vertex")
    assert getattr(doc.canvas, "_last_native_tool", ("", ""))[0] == "vertex"

    # 像素映射按**实际** extent 算：set_extent 会按视口纵横比微调（保形），
    # 用请求值算会偏出拾取容差（10px）。
    xmin, ymin, xmax, ymax = doc.canvas.view_extent
    width, height = viewport.width(), viewport.height()

    def pixel(x: float, y: float):
        return QPoint(int(round((x - xmin) / (xmax - xmin) * width)),
                      int(round((ymax - y) / (ymax - ymin) * height)))

    QTest.mousePress(viewport, Qt.LeftButton, Qt.NoModifier, pixel(4.0, 4.0))
    QTest.mouseMove(viewport, pixel(3.5, 3.5))
    QTest.mouseMove(viewport, pixel(3.0, 3.0))
    QTest.mouseRelease(viewport, Qt.LeftButton, Qt.NoModifier, pixel(3.0, 3.0))
    qtbot.wait(250)

    ring = _mirror_ring(doc, layer.id)
    assert any(abs(px - 3.0) < 0.05 and abs(py - 3.0) < 0.05
               for px, py in ring), (
        f"顶点未被移动——编辑目标没就位或拖动被拒：{ring}")


def _mirror_ring(doc, doc_id: str):
    payload = json.loads(doc.canvas.stack.mirror_features_json(str(doc_id), 0))
    assert payload["exists"], "镜像层不存在"
    for feature in payload["features"]:
        if str(feature.get("id")) == "f1":
            return feature["geometry"]["coordinates"][0]
    raise AssertionError("f1 not in mirror readback")
