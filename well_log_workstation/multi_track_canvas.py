"""QWidget multi-track canvas for a HostPresentation (#219).

Paints depth track + curve tracks. This is the host display surface until
Python binds engine ScenePresentation / WellLogView multi-track fully.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from well_log_workstation.template_model import HostPresentation


class MultiTrackCanvas(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MultiTrackCanvas")
        self.setMinimumSize(400, 400)
        self._presentation: HostPresentation | None = None
        self.setStyleSheet("background: #ffffff;")

    def set_presentation(self, presentation: HostPresentation | None) -> None:
        self._presentation = presentation
        self.update()

    def presentation(self) -> HostPresentation | None:
        return self._presentation

    def track_count(self) -> int:
        return 0 if self._presentation is None else self._presentation.track_count

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if self._presentation is None or not self._presentation.tracks:
            p.setPen(QColor("#888"))
            p.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "选择井并应用多图道图版",
            )
            p.end()
            return

        pres = self._presentation
        depth = np.asarray(pres.depth, dtype=np.float64)
        if depth.size < 2:
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "深度数据不足")
            p.end()
            return

        d0, d1 = float(np.nanmin(depth)), float(np.nanmax(depth))
        if not math.isfinite(d0) or not math.isfinite(d1) or d1 <= d0:
            d0, d1 = 0.0, 1.0

        header_h = 28
        top, bottom = 8 + header_h, h - 16
        left_margin = 8
        usable_w = max(40, w - left_margin - 8)
        total_frac = sum(max(0.05, t.width_fraction) for t in pres.tracks) or 1.0

        x = left_margin
        for track in pres.tracks:
            tw = max(24, int(usable_w * (max(0.05, track.width_fraction) / total_frac)))
            # header
            p.setPen(QPen(QColor("#333"), 1))
            p.drawRect(x, 8, tw - 4, header_h - 4)
            p.drawText(x + 4, 8 + 16, track.title[:12])

            # track body
            p.setPen(QPen(QColor("#bbbbbb"), 1))
            p.drawRect(x, top, tw - 4, bottom - top)

            if track.role == "depth":
                p.setPen(QColor("#444"))
                for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
                    yy = top + int((bottom - top) * frac)
                    depth_v = d0 + (d1 - d0) * frac
                    p.drawLine(x, yy, x + 6, yy)
                    p.drawText(x + 8, yy + 4, f"{depth_v:.0f}")
            else:
                for layer in track.layers:
                    self._paint_curve(
                        p,
                        x + 2,
                        top,
                        tw - 8,
                        bottom - top,
                        depth,
                        d0,
                        d1,
                        layer.values,
                        layer.null_mask,
                        track.scale.min if track.scale else 0.0,
                        track.scale.max if track.scale else 100.0,
                        track.scale.mode if track.scale else "linear",
                        QColor(layer.color),
                    )
            x += tw

        p.setPen(QColor("#666"))
        p.drawText(
            8,
            h - 4,
            f"{pres.well_name} · {pres.template_name} · "
            f"{pres.track_count} 图道 · {pres.depth_unit}",
        )
        p.end()

    def _paint_curve(
        self,
        p: QPainter,
        x0: int,
        y0: int,
        tw: int,
        th: int,
        depth: np.ndarray,
        d0: float,
        d1: float,
        values: np.ndarray,
        null_mask: np.ndarray,
        vmin: float,
        vmax: float,
        mode: str,
        color: QColor,
    ) -> None:
        vals = np.asarray(values, dtype=np.float64)
        n = min(depth.size, vals.size, null_mask.size if null_mask is not None else vals.size)
        if n < 2 or tw < 4 or th < 4:
            return
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
            t = max(0.0, min(1.0, t))
            return x0 + t * tw

        def y_map(d: float) -> float:
            t = (d - d0) / (d1 - d0)
            return y0 + t * th

        pen = QPen(color, 1.5)
        p.setPen(pen)
        prev = None
        step = max(1, n // 2000)
        for i in range(0, n, step):
            if null_mask is not None and bool(null_mask[i]):
                prev = None
                continue
            v = float(vals[i])
            d = float(depth[i])
            xx, yy = x_map(v), y_map(d)
            if not math.isfinite(xx) or not math.isfinite(yy):
                prev = None
                continue
            if prev is not None:
                p.drawLine(int(prev[0]), int(prev[1]), int(xx), int(yy))
            prev = (xx, yy)
