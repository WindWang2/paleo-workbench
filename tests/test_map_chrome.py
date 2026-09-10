"""图层/画布界面始终绘制比例尺与指北针。"""
from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

QApplication.instance() or QApplication([])

from paleo_workbench.ui.unified_map_canvas import (
    ensure_basic_map_chrome,
    paint_map_decorations,
)


def test_ensure_basic_map_chrome_adds_scale_and_north():
    out = ensure_basic_map_chrome({})
    assert "比例尺" in out["elements"]
    assert "指北针" in out["elements"]


def test_ensure_basic_map_chrome_keeps_existing_aliases():
    out = ensure_basic_map_chrome({"elements": ["scale_bar", "title"]})
    assert "scale_bar" in out["elements"]
    assert "指北针" in out["elements"]
    assert "title" in out["elements"]


def test_empty_decorations_paint_scale_bar_and_north_arrow():
    image = QImage(240, 160, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    paint_map_decorations(
        painter, {},
        width=240, height=160,
        extent=(0.0, 0.0, 100.0, 50.0),
        dark_chrome=True,
    )
    painter.end()
    ink = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixelColor(x, y).name() != "#ffffff":
                ink += 1
    assert ink > 40


def test_north_arrow_paints_top_left():
    image = QImage(240, 160, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    paint_map_decorations(
        painter, {"elements": ["指北针"]},
        width=240, height=160,
        extent=(0.0, 0.0, 100.0, 50.0),
        dark_chrome=True,
    )
    painter.end()
    left = right = 0
    for y in range(70):
        for x in range(60):
            if image.pixelColor(x, y).lightness() < 80:
                left += 1
        for x in range(180, 240):
            if image.pixelColor(x, y).lightness() < 80:
                right += 1
    assert left > 10
    assert left > right


def test_light_map_body_uses_dark_ink():
    """QGIS 画布是白底：dark_chrome=True 才能看见比例尺/指北针。"""
    image = QImage(240, 160, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    paint_map_decorations(
        painter, {"elements": ["比例尺", "指北针"]},
        width=240, height=160,
        extent=(0.0, 0.0, 100.0, 50.0),
        dark_chrome=True,
    )
    painter.end()
    dark = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.lightness() < 80:
                dark += 1
    assert dark > 20
