"""Export dispatch — per-plot-type export routing (Phase-2, T8 / #252).

T8 resolution: no new engine bindings; host-side dispatcher that routes by
``PlotDocument.type``:

- single_well / correlation / section -> Qt paint (SVG/PDF/PNG)
- plane_map -> ``export_professional_figure`` (PaleoMapCanvas contract)
- fence_3d -> PNG only via ``grabFramebuffer()``; SVG/PDF raise
  ``UnsupportedFormatError``
- composite -> cartography window (SVG/PDF/PNG; mixed vector+raster)

Pagination is host-side and only applies to depth-axis types
(single_well / correlation / section).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from well_log_workstation.export_plot import ExportError
from well_log_workstation.plot_document import PlotDocument

ExportFormat = Literal["svg", "pdf", "png"]


class UnsupportedFormatError(ExportError):
    """Raised when a plot type cannot produce the requested format (T8)."""


@dataclass(frozen=True)
class PageSpec:
    """Export page specification (host-side pagination; ADR 0039 mm units)."""

    page_size: Literal["A4", "A3", "A2"] = "A4"
    orientation: Literal["portrait", "landscape"] = "landscape"
    margins_mm: tuple[float, float, float, float] = (10.0, 10.0, 10.0, 10.0)
    depth_per_page_mm: float | None = None

    @property
    def width_mm(self) -> float:
        dims = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "A2": (420.0, 594.0)}
        w, h = dims[self.page_size]
        return h if self.orientation == "landscape" else w

    @property
    def height_mm(self) -> float:
        dims = {"A4": (210.0, 297.0), "A3": (297.0, 420.0), "A2": (420.0, 594.0)}
        w, h = dims[self.page_size]
        return w if self.orientation == "landscape" else h


def export_plot(
    plot_doc: PlotDocument,
    fmt: ExportFormat,
    *,
    page_spec: PageSpec | None = None,
    **kwargs: Any,
) -> Path:
    """Export a plot document in the requested format, routed by type.

    Extra kwargs are forwarded to the per-type backend (e.g. the source
    widget / canvas instance for plane_map / fence_3d / composite).
    """
    spec = page_spec or PageSpec()
    match plot_doc.type:
        case "single_well" | "correlation" | "section":
            return _qt_paint_export(plot_doc, fmt, spec, **kwargs)
        case "plane_map":
            return _plane_map_export(plot_doc, fmt, spec, **kwargs)
        case "fence_3d":
            return _fence_3d_export(plot_doc, fmt, spec, **kwargs)
        case "composite":
            return _composite_export(plot_doc, fmt, spec, **kwargs)
        case _:
            raise UnsupportedFormatError(f"未知图件类型: {plot_doc.type}")


# -- per-type backends ---------------------------------------------------


def _qt_paint_export(
    plot_doc: PlotDocument,
    fmt: ExportFormat,
    spec: PageSpec,
    **kwargs: Any,
) -> Path:
    """Qt-paint path for single_well / correlation / section.

    Requires a ``paint_fn(painter, rect)`` in kwargs (the host renders the
    presentation(s)); wraps it in the requested format. PNG via QPixmap.
    """
    paint_fn = kwargs.get("paint_fn")
    if paint_fn is None:
        raise ExportError(f"{plot_doc.type} 导出需要 paint_fn 回调")
    out = Path(kwargs.get("path") or f"export_{plot_doc.id}.{fmt}")
    out.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "svg":
        from PySide6.QtSvg import QSvgGenerator
        from PySide6.QtCore import QRectF, QSizeF
        from PySide6.QtGui import QColor, QPainter
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            raise ExportError("需要 QApplication 才能导出 SVG")
        w_mm, h_mm = spec.width_mm, spec.height_mm
        gen = QSvgGenerator()
        gen.setFileName(str(out))
        gen.setSize(QSizeF(w_mm * 3.78, h_mm * 3.78).toSize())  # ~96 dpi base
        gen.setViewBox(QRectF(0, 0, w_mm, h_mm))
        gen.setTitle(plot_doc.name)
        painter = QPainter()
        if not painter.begin(gen):
            raise ExportError("无法开始 SVG 绘制")
        try:
            painter.fillRect(QRectF(0, 0, w_mm, h_mm), QColor("#ffffff"))
            paint_fn(painter, QRectF(0, 0, w_mm, h_mm))
        finally:
            painter.end()
    elif fmt == "pdf":
        from PySide6.QtGui import QColor, QPainter, QPdfWriter
        from PySide6.QtCore import QRectF
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            raise ExportError("需要 QApplication 才能导出 PDF")
        writer = QPdfWriter(str(out))
        writer.setTitle(plot_doc.name)
        writer.setResolution(150)
        painter = QPainter()
        if not painter.begin(writer):
            raise ExportError("无法开始 PDF 绘制")
        try:
            page = painter.viewport()
            painter.fillRect(page, QColor("#ffffff"))
            paint_fn(painter, QRectF(page.x(), page.y(), page.width(), page.height()))
        finally:
            painter.end()
    else:  # png
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter, QPixmap
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            raise ExportError("需要 QApplication 才能导出 PNG")
        w_mm, h_mm = spec.width_mm, spec.height_mm
        pm = QPixmap(int(w_mm * 4), int(h_mm * 4))  # ~4 px/mm (~100 dpi)
        pm.fill(QColor("#ffffff"))
        painter = QPainter(pm)
        try:
            paint_fn(painter, QRectF(0, 0, w_mm, h_mm))
        finally:
            painter.end()
        if not pm.save(str(out)):
            raise ExportError(f"无法保存 PNG: {out}")

    if not out.is_file() or out.stat().st_size < 50:
        raise ExportError("导出文件为空")
    return out


def _plane_map_export(
    plot_doc: PlotDocument,
    fmt: ExportFormat,
    spec: PageSpec,
    **kwargs: Any,
) -> Path:
    """plane_map -> export_professional_figure (PaleoMapCanvas contract)."""
    canvas = kwargs.get("canvas")
    if canvas is None:
        raise ExportError("平面图导出需要 canvas（PaleoMapCanvas）")
    out = Path(kwargs.get("path") or f"export_{plot_doc.id}.{fmt}")
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        from geoviz import export_professional_figure
    except Exception as exc:
        raise ExportError(f"平面图导出需要 geoviz facade: {exc}") from exc
    export_professional_figure(
        canvas,
        out,
        fmt,
        title=plot_doc.name,
        page_size=spec.page_size,
        orientation=spec.orientation,
    )
    return out


def _fence_3d_export(
    plot_doc: PlotDocument,
    fmt: ExportFormat,
    spec: PageSpec,
    **kwargs: Any,
) -> Path:
    """fence_3d -> PNG only (T8 hard constraint; grabFramebuffer)."""
    if fmt != "png":
        raise UnsupportedFormatError(
            "三维栅状图仅支持 PNG 导出（T8：pyqtgraph 无原生矢量导出）"
        )
    view = kwargs.get("view")
    if view is None:
        raise ExportError("栅状图导出需要 view（FenceView）")
    out = Path(kwargs.get("path") or f"export_{plot_doc.id}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    return view.grab_fence_png(out)


def _composite_export(
    plot_doc: PlotDocument,
    fmt: ExportFormat,
    spec: PageSpec,
    **kwargs: Any,
) -> Path:
    """composite -> cartography window (mixed vector + raster panels)."""
    window = kwargs.get("window")
    if window is None:
        raise ExportError("综合图导出需要 layout window（CartographyLayoutWindow）")
    out = Path(kwargs.get("path") or f"export_{plot_doc.id}.{fmt}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "pdf":
        result = window.export_pdf(str(out))
        if result is None:
            raise ExportError("综合图 PDF 导出失败")
    elif fmt == "svg":
        result = window.export_svg(str(out))
        if result is None:
            raise ExportError("综合图 SVG 导出失败")
    else:  # png
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter, QPixmap
        from PySide6.QtWidgets import QApplication

        if QApplication.instance() is None:
            raise ExportError("需要 QApplication 才能导出 PNG")
        w_mm, h_mm = spec.width_mm, spec.height_mm
        pm = QPixmap(int(w_mm * 4), int(h_mm * 4))
        pm.fill()
        painter = QPainter(pm)
        try:
            window.scene().render(painter, QRectF(), window.scene().paper_rect())
        finally:
            painter.end()
        if not pm.save(str(out)):
            raise ExportError(f"无法保存综合图 PNG: {out}")
    return out
