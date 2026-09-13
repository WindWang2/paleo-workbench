# -*- coding: utf-8 -*-
"""相图类别图例：顶层相图 → facies_legend 注入 + 并排双箱绘制。"""
from pathlib import Path

import pytest

pytest.importorskip("PySide6")


def _project(tmp_path: Path):
    from paleo_workbench.project.domain import WellEntity
    from paleo_workbench.project.models import ProjectDocument

    project = ProjectDocument.new("Pearl River Mouth", region="HZ26")
    project.meta.project_root = str(tmp_path)
    project.wells.append(
        WellEntity(name="A12", surface_x=1.0, surface_y=2.0,
                   project_x=1.0, project_y=2.0)
    )
    return project


def _facies_style() -> dict:
    return {
        "fill": "#b0bec5", "stroke": "#26364d", "stroke_width": 0.6,
        "renderer": "categorized", "field": "facies_name",
        "categories": {"扇三角洲": "#c47f4e", "湖相泥": "#81c784"},
        "fill_patterns": {"扇三角洲": "delta", "湖相泥": "lacustrine"},
    }


def test_top_facies_legend_from_topmost_visible_categorized(qtbot, tmp_path):
    """顶层可见分类层 → 图例条目（色+纹理）；顶层非分类/隐藏 → 不出。"""
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    document = CompositeDocument(_project(tmp_path))
    qtbot.addWidget(document)
    controller = document.edit_controller
    layer = controller.create_layer("相带", "polygon", template="facies")
    controller.set_active_layer(layer.id)
    controller.start_editing()
    from paleo_workbench.mapping.map_styles import VectorStyle

    controller.set_layer_style(layer.id, _facies_style())
    document._sync_composition_now()

    legend = document._top_facies_legend()
    assert legend is not None
    assert legend["title"] == "相带"
    assert [(i["label"], i["pattern"]) for i in legend["items"]] == [
        ("扇三角洲", "delta"), ("湖相泥", "lacustrine")]

    # 顶层隐藏 → 不再是「顶层显示为相图」（可见性权威 = 面板快照）
    from dataclasses import replace as _replace

    panel = document.layer_manager
    panel._layers = [
        _replace(snap, visible=False) if snap.id == layer.id else snap
        for snap in panel._layers
    ]
    document._sync_composition_now()
    assert document._top_facies_legend() is None

    # 恢复可见 → overlay 态携带 facies_legend 键
    panel._layers = [
        _replace(snap, visible=True) if snap.id == layer.id else snap
        for snap in panel._layers
    ]
    document._sync_composition_now()
    state = document._canvas_overlay_state()
    assert "facies_legend" in (state.get("decorations") or {})
    # 原图例仍在（并列共存）
    assert (state.get("decorations") or {}).get("legend_items")


def test_paint_map_decorations_dual_legend(qtbot):
    """绘制烟囱：facies_legend 存在时左侧并排第二箱（色样块像素可见）。"""
    from PySide6.QtGui import QImage, QPainter

    from paleo_workbench.ui.unified_map_canvas import paint_map_decorations

    image = QImage(560, 240, QImage.Format.Format_RGB32)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    paint_map_decorations(
        painter,
        {
            "elements": ["图例"],
            "legend_items": [{"label": "井位", "color": "#f59f00"}],
            "facies_legend": {
                "title": "地震相预测",
                "items": [
                    {"label": "扇三角洲", "color": "#c47f4e", "pattern": "delta"},
                    {"label": "湖相泥", "color": "#81c784", "pattern": ""},
                ],
            },
        },
        width=560, height=240, extent=(0.0, 0.0, 1.0, 1.0), dark_chrome=True,
    )
    painter.end()
    pixels = {
        "橙(扇三角洲)": (196, 127, 78),
        "绿(湖相泥)": (129, 199, 132),
        "黄(井位原图例)": (245, 159, 0),
    }
    for name, target in pixels.items():
        found = any(
            abs(image.pixelColor(x, y).red() - target[0]) <= 30
            and abs(image.pixelColor(x, y).green() - target[1]) <= 30
            and abs(image.pixelColor(x, y).blue() - target[2]) <= 30
            for x in range(0, 560, 2) for y in range(0, 240, 2))
        assert found, f"图例样块缺失：{name}"
