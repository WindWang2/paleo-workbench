"""Correlation-lite multi-well canvas with shared depth (#222)."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QWheelEvent
from PySide6.QtWidgets import QWidget

from well_log_workstation.template_model import HostPresentation


class CorrelationCanvas(QWidget):
    """Side-by-side well columns; shared depth window (pan/zoom)."""

    depth_range_changed = Signal(float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CorrelationCanvas")
        self.setMinimumSize(480, 400)
        self.setStyleSheet("background: #ffffff;")
        self._columns: list[HostPresentation] = []
        self._d0: float | None = None
        self._d1: float | None = None
        self._drag_y: int | None = None
        self._drag_d0: float | None = None
        self._drag_d1: float | None = None

    def set_columns(self, presentations: list[HostPresentation]) -> None:
        self._columns = list(presentations)
        self._fit_depth()
        self.update()

    def columns(self) -> list[HostPresentation]:
        return list(self._columns)

    def column_count(self) -> int:
        return len(self._columns)

    def depth_range(self) -> tuple[float, float] | None:
        if self._d0 is None or self._d1 is None:
            return None
        return self._d0, self._d1

    def set_depth_range(self, d0: float, d1: float) -> None:
        if d1 <= d0:
            return
        self._d0, self._d1 = d0, d1
        self.depth_range_changed.emit(d0, d1)
        self.update()

    def _fit_depth(self) -> None:
        mins: list[float] = []
        maxs: list[float] = []
        for pres in self._columns:
            depth = np.asarray(pres.depth, dtype=np.float64)
            if depth.size:
                mins.append(float(np.nanmin(depth)))
                maxs.append(float(np.nanmax(depth)))
        if mins and maxs:
            self._d0, self._d1 = min(mins), max(maxs)
        else:
            self._d0, self._d1 = 0.0, 1.0

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        if self._d0 is None or self._d1 is None:
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        span = self._d1 - self._d0
        factor = 0.9 if delta > 0 else 1.1
        mid = 0.5 * (self._d0 + self._d1)
        new_span = max(span * factor, 1e-3)
        self.set_depth_range(mid - new_span / 2, mid + new_span / 2)
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_y = int(event.position().y())
            self._drag_d0, self._drag_d1 = self._d0, self._d1
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if (
            self._drag_y is None
            or self._drag_d0 is None
            or self._drag_d1 is None
            or self._d0 is None
            or self._d1 is None
        ):
            return
        dy = int(event.position().y()) - self._drag_y
        h = max(1, self.height() - 48)
        span = self._drag_d1 - self._drag_d0
        shift = (dy / h) * span
        self.set_depth_range(self._drag_d0 + shift, self._drag_d1 + shift)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_y = None
        event.accept()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if not self._columns or self._d0 is None or self._d1 is None:
            p.setPen(QColor("#888"))
            p.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "创建地层对比图（≥2 口井）",
            )
            p.end()
            return

        n = len(self._columns)
        gap = 6
        col_w = max(40, (w - 16 - gap * (n - 1)) // n)
        top, bottom = 36, h - 24
        d0, d1 = self._d0, self._d1

        for i, pres in enumerate(self._columns):
            x0 = 8 + i * (col_w + gap)
            p.setPen(QPen(QColor("#333"), 1))
            p.drawRect(x0, 8, col_w - 2, 22)
            p.drawText(x0 + 4, 24, pres.well_name[:18])
            p.setPen(QPen(QColor("#ccc"), 1))
            p.drawRect(x0, top, col_w - 2, bottom - top)

            # primary curve layer from first curve track
            curve_track = next(
                (t for t in pres.tracks if t.role == "curve" and t.layers),
                None,
            )
            depth = np.asarray(pres.depth, dtype=np.float64)
            if curve_track is None or depth.size < 2:
                continue
            layer = curve_track.layers[0]
            vals = np.asarray(layer.values, dtype=np.float64)
            nulls = np.asarray(layer.null_mask, dtype=bool)
            scale = curve_track.scale
            vmin = scale.min if scale else 0.0
            vmax = scale.max if scale else 100.0
            mode = scale.mode if scale else "linear"
            if mode == "log":
                vmin = max(vmin, 1e-6)
                vmax = max(vmax, vmin * 10)
                log_min, log_max = math.log10(vmin), math.log10(vmax)

            def x_map(v: float) -> float:
                if mode == "log":
                    if v <= 0 or not math.isfinite(v):
                        return float("nan")
                    t = (math.log10(v) - log_min) / (log_max - log_min)
                else:
                    if not math.isfinite(v):
                        return float("nan")
                    t = (v - vmin) / (vmax - vmin) if vmax > vmin else 0.5
                return x0 + 4 + max(0.0, min(1.0, t)) * (col_w - 12)

            def y_map(d: float) -> float:
                return top + ((d - d0) / (d1 - d0)) * (bottom - top)

            p.setPen(QPen(QColor(layer.color), 1.5))
            prev = None
            npts = min(depth.size, vals.size, nulls.size)
            step = max(1, npts // 1500)
            for j in range(0, npts, step):
                if bool(nulls[j]):
                    prev = None
                    continue
                d = float(depth[j])
                if d < d0 or d > d1:
                    prev = None
                    continue
                xx, yy = x_map(float(vals[j])), y_map(d)
                if not math.isfinite(xx) or not math.isfinite(yy):
                    prev = None
                    continue
                if prev is not None:
                    p.drawLine(int(prev[0]), int(prev[1]), int(xx), int(yy))
                prev = (xx, yy)

        p.setPen(QColor("#555"))
        p.drawText(
            8,
            h - 6,
            f"对比-lite · {n} 井 · 共享深度 {d0:.1f}–{d1:.1f} · 滚轮缩放 / 拖动平移",
        )
        p.end()
