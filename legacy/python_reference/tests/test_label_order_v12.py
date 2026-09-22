# -*- coding: utf-8 -*-
"""V12 M3：标注顺序不变量（回退渲染器，I-2）。

标注必须是**几何之后**的独立一遍，同 zIndex 时按图层序 —— 顶层标注压在最上
（QGIS 原生语义：label pass 按画布层序排序后绘制）。修复前回退渲染器把标注
内联在所在层的绘制过程中，于是下层点标注会被上层几何/标注盖住，两栈观感
不一致（D-D）。
"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")


def _point_layer(layer_id: str, text: str, color: str, *, y: float = 5.0):
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot

    return MapLayerSnapshot(
        id=layer_id, name=layer_id, layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
        data_revision=1, style_revision=1,
        features=({"id": f"{layer_id}-f1",
                   "geometry": {"type": "Point", "coordinates": [5.0, y]},
                   "properties": {"text": text}},),
        style={
            "fill": color, "stroke": color, "stroke_width": 1.0,
            "marker": "circle", "marker_size": 4.0,
            "labels": {
                "field": "text", "size": 22.0, "color": color,
                "halo_color": color, "halo_width": 0.0, "visible": True,
            },
        },
        visible=True, opacity=1.0,
    )


def _render(snapshot):
    """离屏渲染一帧（需 qapp fixture：字体引擎要有 QGuiApplication）。"""
    from PySide6.QtGui import QImage, QPainter
    from paleo_workbench.mapping.map_render_backend import FallbackMapRenderBackend

    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(snapshot)
    backend.set_extent((0.0, 0.0, 10.0, 10.0))
    backend.set_output_size(400, 400)
    backend.set_dpi(96.0)
    image = QImage(400, 400, QImage.Format.Format_RGBA8888)
    image.fill(0)
    painter = QPainter(image)
    try:
        backend.render_to_painter(painter, 400, 400)
    finally:
        painter.end()
    return image


def _color_hits(image, rgb, tolerance: int = 40) -> int:
    target = tuple(rgb)
    count = 0
    for y in range(image.height()):
        for x in range(image.width()):
            pixel = image.pixelColor(x, y)
            if (abs(pixel.red() - target[0]) <= tolerance
                    and abs(pixel.green() - target[1]) <= tolerance
                    and abs(pixel.blue() - target[2]) <= tolerance):
                count += 1
    return count


def _snapshot(layers):
    from paleo_workbench.mapping.map_render_backend import MapRenderSnapshot

    return MapRenderSnapshot(project_crs="EPSG:4326", layers=tuple(layers))


def test_top_layer_label_wins_when_labels_overlap(qapp):
    """两层同锚点同文案：顶层标注必须完全盖住下层（几何之后统一绘制）。"""
    lower = _point_layer("lower", "重叠标注", "#c92a2a")   # 红
    upper = _point_layer("upper", "重叠标注", "#1864ab")   # 蓝
    image = _render(_snapshot([lower, upper]))

    lower_hits = _color_hits(image, (0xC9, 0x2A, 0x2A))
    upper_hits = _color_hits(image, (0x18, 0x64, 0xAB))
    assert upper_hits > 0, "顶层标注根本没画出来"
    assert lower_hits == 0, (
        f"下层标注仍有 {lower_hits} 像素露出——标注未在几何之后统一绘制"
        f"（顶层 {upper_hits} 像素）")


def test_labels_paint_above_upper_layer_geometry(qapp):
    """标注不得被任何图层几何覆盖：上层实心面不得吃掉下层点标注。"""
    from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot

    points = _point_layer("pts", "标注", "#c92a2a", y=4.0)
    cover = MapLayerSnapshot(
        id="cover", name="cover", layer_type="vector",
        extent=(0.0, 0.0, 10.0, 10.0), crs="EPSG:4326",
        data_revision=1, style_revision=1,
        features=({"id": "cover-f1",
                   "geometry": {"type": "Polygon", "coordinates": [[
                       (0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0),
                       (0.0, 0.0)]]},
                   "properties": {}},),
        style={"fill": "#e9ecef", "stroke": "#e9ecef", "stroke_width": 0.0},
        visible=True, opacity=1.0,
    )
    image = _render(_snapshot([points, cover]))
    assert _color_hits(image, (0xC9, 0x2A, 0x2A)) > 0, (
        "下层点标注被上层实心面覆盖——标注必须在全部几何之后绘制")
