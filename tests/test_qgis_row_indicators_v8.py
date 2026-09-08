"""V8 M5 — 原生行指示器面板投影（LayerPresentationState → 桥 kinds）。"""
import json

import pytest

pytest.importorskip("PySide6")
pytestmark = pytest.mark.qgis

from tests.qgis_support import require_qgis  # noqa: E402

require_qgis()

_FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
     "properties": {}}]}


def _layer(layer_id, name):
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
    return MapLayerSnapshot(
        id=layer_id, name=name, layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
        data_revision=1, style_revision=1,
        features=(dict(_FC["features"][0]),), style={},
        visible=True, opacity=1.0,
    )


def _state(**kwargs):
    from paleo_workbench.ui.workstation.layer_decorations import (
        LayerPresentationState,
    )

    return LayerPresentationState(**kwargs)


def _bound_panel(qtbot):
    from paleo_workbench.ui.qgis_stack.canvas_shim import QgisCanvasShim
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    canvas = QgisCanvasShim()
    qtbot.addWidget(canvas)
    panel = QgisLayerTreePanel()
    qtbot.addWidget(panel)
    panel.bind(canvas, [_layer("doc-a", "井位"), _layer("doc-b", "边界")])
    canvas.show()
    panel.show()
    qtbot.waitUntil(lambda: panel.tree_row_count() >= 2, timeout=3000)
    return canvas, panel


def test_row_indicator_kinds_vocabulary(qtbot, qapp):
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    kinds = QgisLayerTreePanel._indicator_kinds(_state(
        dirty=True, stale=True, maturity="published",
    ))
    # 优先序同 layer_decorations._PRIORITY：dirty > stale > published 全列
    # （行内多指示器并列，主信号选择由 fallback 面板/摘要行负责）。
    assert kinds == ["dirty", "stale", "published"]
    assert QgisLayerTreePanel._indicator_kinds(_state()) == []
    # editing 不经 kinds（set_editing_layer 的 ✏ 独占）
    assert "editing" not in QgisLayerTreePanel._indicator_kinds(_state(editing=True))


def test_decorations_project_to_native_indicators(qtbot, qapp):
    canvas, panel = _bound_panel(qtbot)
    tree = panel.tree_host.tree_view_address
    stack = canvas.stack

    panel.set_layer_decorations({
        "doc-a": _state(dirty=True),
        "doc-b": _state(maturity="published", stale=True),
    })
    assert stack.row_indicator_count(tree, "doc-a") == 1
    assert stack.row_indicator_count(tree, "doc-a", "dirty") == 1
    assert stack.row_indicator_count(tree, "doc-b") == 2
    assert stack.row_indicator_count(tree, "doc-b", "stale") == 1
    assert stack.row_indicator_count(tree, "doc-b", "published") == 1

    # 干净态整组清除
    panel.set_layer_decorations({"doc-a": _state(), "doc-b": _state()})
    assert stack.row_indicator_count(tree, "doc-a") == 0
    assert stack.row_indicator_count(tree, "doc-b") == 0


def test_unknown_kinds_skipped_old_bridge_contract(qtbot, qapp):
    """kinds 词汇外的状态不上行（与桥端"未知 kind 跳过"双重防御）。"""
    from paleo_workbench.ui.qgis_stack.layer_tree_panel import QgisLayerTreePanel

    kinds = QgisLayerTreePanel._indicator_kinds(_state(
        missing_input=True, superseded=True, degraded=True, maturity="frozen",
    ))
    assert kinds == ["missing_input", "superseded", "degraded", "frozen"]
    assert json.dumps(kinds)  # 可序列化上桥
