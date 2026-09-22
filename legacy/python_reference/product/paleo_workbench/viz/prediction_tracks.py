"""Prediction-specific QPainter tracks with distinct categorical/continuous semantics.

The upstream ``IntervalTrack`` intentionally treats every interval name as a
category.  Online facies labels fit that model; confidence percentages do not.
These local tracks keep the renderer dependency stable while making the two
meanings unambiguous in the Workbench prediction canvas.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QBrush, QFont, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

from geoviz import (
    ECHARTS_BORDER,
    ECHARTS_TEXT,
    IntervalItem,
    IntervalTrack,
    compute_label_policy,
    fit_label_text,
)


_SVG_TEXTURE_DIR = Path(__file__).resolve().parents[2] / "svg_output" / "textures"

# Ordered so an explicit environment is selected before a more general
# lithology word such as "泥" or "砂".
_FACIES_STYLES: tuple[tuple[str, str, str], ...] = (
    ("分流间湾", "#d4c5a9", "tex_mudstone"),
    ("分流河道", "#ebd2b0", "tex_sandstone_medium"),
    ("河道", "#ebd2b0", "tex_sandstone_medium"),
    ("三角洲", "#e6c9a8", "tex_sandstone_medium"),
    ("粉砂", "#e6c9a8", "tex_siltstone"),
    ("页岩", "#c9bfa0", "tex_shale_thin"),
    ("泥", "#d4c5a9", "tex_mudstone"),
    ("砂", "#ebd2b0", "tex_sandstone_medium"),
    ("灰岩", "#b5d4c1", "tex_limestone_micritic"),
    ("白云岩", "#a8cdb8", "tex_dolomite"),
    ("砾", "#e6c9a8", "tex_conglomerate_pebble"),
)

_CONFIDENCE_LOW = QColor("#e8f1fb")
_CONFIDENCE_HIGH = QColor("#124c8c")


def facies_style_for(name: str) -> tuple[str, str | None]:
    """Return a stable fill colour and an SVG-output texture id for a facies."""
    label = str(name or "")
    for keyword, color, texture_id in _FACIES_STYLES:
        if keyword in label:
            return color, texture_id
    return "#e0e0e0", None


class SvgOutputTextureCache:
    """Render tiles from the project-owned ``svg_output/textures`` assets."""

    def __init__(self) -> None:
        self._brushes: dict[str, QBrush] = {}

    def path_for(self, texture_id: str | None) -> Path | None:
        if not texture_id:
            return None
        path = _SVG_TEXTURE_DIR / f"{texture_id}.svg"
        return path if path.is_file() else None

    def brush_for(self, texture_id: str | None) -> QBrush | None:
        if not texture_id:
            return None
        cached = self._brushes.get(texture_id)
        if cached is not None:
            return cached
        path = self.path_for(texture_id)
        if path is None:
            return None
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return None

        # Each catalog SVG is an 80px labelled swatch whose real texture starts
        # at (4, 4). Crop one 12px repeat cell, so the interval shows the
        # supplied texture itself rather than a repeated swatch frame/label.
        source = QPixmap(80, 80)
        source.fill(Qt.GlobalColor.transparent)
        painter = QPainter(source)
        renderer.render(painter, QRectF(0, 0, 80, 80))
        painter.end()
        tile = source.copy(QRect(4, 4, 12, 12))
        brush = QBrush(tile)
        self._brushes[texture_id] = brush
        return brush


_TEXTURES = SvgOutputTextureCache()


class FaciesTextureTrack(IntervalTrack):
    """Categorical prediction-facies column using project-owned SVG textures."""

    def __init__(
        self,
        intervals: list[IntervalItem],
        *,
        label: str = "AI预测相",
        width: int = 86,
        texture_cache: SvgOutputTextureCache | None = None,
    ) -> None:
        colors = {item.name: facies_style_for(item.name)[0] for item in intervals}
        super().__init__(intervals=intervals, label=label, width=width, colors=colors)
        self._texture_cache = texture_cache or _TEXTURES

    def texture_path_for(self, name: str) -> Path | None:
        """Expose the selected SVG for diagnostics/tests without opening it."""
        _color, texture_id = facies_style_for(name)
        return self._texture_cache.path_for(texture_id)

    def paint_content(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setClipRect(rect.adjusted(-2, -2, 2, 2))
        self.paint_grid(painter, rect)

        font = QFont()
        font.setBold(True)
        interval_rects = _interval_rects(self._intervals, self, rect)
        policy = compute_label_policy(
            rect, self.depth_span, [item_rect.height() for _, _, item_rect in interval_rects]
        )
        font.setPixelSize(policy.font_px)
        painter.setFont(font)
        metrics = painter.fontMetrics()

        for index, interval, interval_rect in interval_rects:
            _color, texture_id = facies_style_for(interval.name)
            brush = self._texture_cache.brush_for(texture_id)
            painter.fillRect(interval_rect, brush or QBrush(self._get_color(index, interval.name)))
            _paint_interval_border_and_label(painter, interval_rect, interval.name, policy, metrics)

        _finish_track(painter, rect)


class ConfidenceHeatmapTrack(IntervalTrack):
    """Continuous 0–1 probability column, independent from facies colours."""

    def __init__(
        self,
        intervals: list[IntervalItem],
        probabilities: list[float],
        *,
        label: str = "AI预测置信度",
        width: int = 86,
    ) -> None:
        super().__init__(intervals=intervals, label=label, width=width)
        self._probabilities = list(probabilities)

    def color_for_probability(self, probability: float) -> QColor:
        """Map a probability onto a light-to-dark blue sequential heatmap."""
        try:
            value = float(probability)
        except (TypeError, ValueError):
            value = 0.0
        value = max(0.0, min(1.0, value))
        return QColor(
            round(_CONFIDENCE_LOW.red() + (_CONFIDENCE_HIGH.red() - _CONFIDENCE_LOW.red()) * value),
            round(_CONFIDENCE_LOW.green() + (_CONFIDENCE_HIGH.green() - _CONFIDENCE_LOW.green()) * value),
            round(_CONFIDENCE_LOW.blue() + (_CONFIDENCE_HIGH.blue() - _CONFIDENCE_LOW.blue()) * value),
        )

    def paint_header(self, painter: QPainter, rect: QRectF) -> None:
        super().paint_header(painter, rect)
        painter.save()
        bar = QRectF(rect.left() + 7, rect.bottom() - 7, max(1.0, rect.width() - 14), 3)
        gradient = QLinearGradient(bar.left(), 0, bar.right(), 0)
        gradient.setColorAt(0.0, _CONFIDENCE_LOW)
        gradient.setColorAt(1.0, _CONFIDENCE_HIGH)
        painter.fillRect(bar, QBrush(gradient))
        painter.restore()

    def paint_content(self, painter: QPainter, rect: QRectF) -> None:
        painter.save()
        painter.setClipRect(rect.adjusted(-2, -2, 2, 2))
        self.paint_grid(painter, rect)

        font = QFont()
        font.setBold(True)
        interval_rects = _interval_rects(self._intervals, self, rect)
        policy = compute_label_policy(
            rect, self.depth_span, [item_rect.height() for _, _, item_rect in interval_rects]
        )
        font.setPixelSize(policy.font_px)
        painter.setFont(font)
        metrics = painter.fontMetrics()

        for index, interval, interval_rect in interval_rects:
            probability = self._probabilities[index] if index < len(self._probabilities) else 0.0
            color = self.color_for_probability(probability)
            painter.fillRect(interval_rect, QBrush(color))
            text_color = QColor("#ffffff") if color.lightness() < 128 else QColor(ECHARTS_TEXT)
            _paint_interval_border_and_label(
                painter, interval_rect, interval.name, policy, metrics, text_color=text_color
            )

        _finish_track(painter, rect)


def _interval_rects(intervals, track, rect: QRectF):
    output = []
    for index, interval in enumerate(intervals):
        y_top = track._depth_to_y(interval.top, rect)
        y_bottom = track._depth_to_y(interval.bottom, rect)
        if y_bottom < rect.top() or y_top > rect.bottom():
            continue
        y_top = max(y_top, rect.top())
        y_bottom = min(y_bottom, rect.bottom())
        output.append(
            (index, interval, QRectF(rect.left(), y_top, rect.width(), y_bottom - y_top))
        )
    return output


def _paint_interval_border_and_label(
    painter: QPainter,
    interval_rect: QRectF,
    label: str,
    policy,
    metrics,
    *,
    text_color: QColor | None = None,
) -> None:
    painter.setPen(QPen(QColor(ECHARTS_BORDER), 0.5))
    painter.drawRect(interval_rect)
    painter.setPen(QPen(text_color or QColor(ECHARTS_TEXT), 1))
    text_rect = QRectF(
        interval_rect.left() + 2,
        interval_rect.top() + 1,
        interval_rect.width() - 4,
        interval_rect.height() - 2,
    )
    lines = fit_label_text(label, text_rect, policy, metrics)
    if not lines:
        return
    if policy.vertical:
        painter.save()
        painter.translate(text_rect.center())
        painter.rotate(-90)
        rotated = QRectF(
            -text_rect.height() / 2,
            -text_rect.width() / 2,
            text_rect.height(),
            text_rect.width(),
        )
        painter.drawText(rotated, Qt.AlignmentFlag.AlignCenter, lines[0])
        painter.restore()
        return
    painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "\n".join(lines))


def _finish_track(painter: QPainter, rect: QRectF) -> None:
    painter.setClipping(False)
    painter.setPen(QPen(QColor(ECHARTS_BORDER), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(rect)
    painter.restore()


__all__ = [
    "ConfidenceHeatmapTrack",
    "FaciesTextureTrack",
    "SvgOutputTextureCache",
    "facies_style_for",
]
