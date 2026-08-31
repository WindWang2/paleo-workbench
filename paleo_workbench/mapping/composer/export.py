"""Composition page export: PNG / SVG / PDF with one physical-size contract.

The composition owns physical truth: paper size in millimetres plus an
export DPI. All three formats frame the SAME page:

* SVG — vector scene authored in mm (viewBox in mm units);
* PNG — the SVG replayed at ``dpi`` through ``QSvgRenderer`` with
  ``setDotsPerMeter`` persisted so printed size matches the export DPI;
* PDF — ``QPdfWriter`` with the page set to the document's physical size;
  the SVG replays vectorially onto its painter (same replay path as the
  unified canvas, #923 discipline: one renderer configuration for screen
  and export).

No UI thread blocking concerns beyond Qt's synchronous paint of one page;
large rasters stay bounded by the DPI × paper size the user asked for.
"""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.mapping.composer.models import MapCompositionDocument
from paleo_workbench.mapping.composer.renderer import composer_renderer

_MM_PER_INCH = 25.4


def composition_page_pixels(doc: MapCompositionDocument, dpi: float) -> tuple[int, int]:
    """Physical page size in device pixels at *dpi* (the single DPI fold)."""
    width_px = max(1, round(doc.width_mm / _MM_PER_INCH * float(dpi)))
    height_px = max(1, round(doc.height_mm / _MM_PER_INCH * float(dpi)))
    return (width_px, height_px)


def _composition_svg(doc: MapCompositionDocument) -> str:
    svg = composer_renderer.render_to_svg(doc)
    # Re-anchor the authoring SVG (96 DPI px attributes) to physical size:
    # the viewBox is already in mm, so only the width/height attributes need
    # to switch to millimetres for a physically-sized page.
    import re

    head, sep, tail = svg.partition(">")
    head = re.sub(r'width="[^"]*"', f'width="{doc.width_mm}mm"', head, count=1)
    head = re.sub(r'height="[^"]*"', f'height="{doc.height_mm}mm"', head, count=1)
    return head + sep + tail


def export_composition_svg(
    doc: MapCompositionDocument, path: str | Path, *, dpi: float | None = None
) -> Path:
    """Write the composition as a physical-size vector SVG page."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(_composition_svg(doc), encoding="utf-8")
    return out


def export_composition_png(
    doc: MapCompositionDocument, path: str | Path, *, dpi: float | None = None
) -> Path:
    """Raster export: SVG replayed at the requested device resolution."""
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    effective_dpi = float(dpi if dpi is not None else doc.dpi)
    width_px, height_px = composition_page_pixels(doc, effective_dpi)
    renderer = QSvgRenderer(QByteArray(_composition_svg(doc).encode("utf-8")))
    if not renderer.isValid():
        raise RuntimeError("composition SVG did not parse; refusing to export PNG")
    image = QImage(width_px, height_px, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        renderer.render(painter)
    finally:
        painter.end()
    dots_per_meter = round(effective_dpi / 0.0254)
    image.setDotsPerMeterX(dots_per_meter)
    image.setDotsPerMeterY(dots_per_meter)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(out), "PNG"):
        raise RuntimeError("could not save composition PNG")
    return out


def export_composition_pdf(
    doc: MapCompositionDocument, path: str | Path, *, dpi: float | None = None
) -> Path:
    """Vector PDF export at the document's physical page size."""
    from PySide6.QtCore import QByteArray, QMarginsF, QRectF, QSizeF
    from PySide6.QtGui import QPageLayout, QPainter, QPageSize, QPdfWriter
    from PySide6.QtSvg import QSvgRenderer

    effective_dpi = float(dpi if dpi is not None else doc.dpi)
    writer = QPdfWriter(str(path))
    writer.setResolution(int(round(effective_dpi)))
    page_size = QPageSize(
        QSizeF(doc.width_mm, doc.height_mm), QPageSize.Unit.Millimeter, "Composition",
        QPageSize.SizeMatchPolicy.ExactMatch,
    )
    writer.setPageLayout(
        QPageLayout(page_size, QPageLayout.Orientation.Portrait, QMarginsF(0, 0, 0, 0))
    )
    painter = QPainter()
    if not painter.begin(writer):
        raise RuntimeError("could not open PDF writer for composition export")
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        renderer = QSvgRenderer(QByteArray(_composition_svg(doc).encode("utf-8")))
        if not renderer.isValid():
            raise RuntimeError("composition SVG did not parse; refusing to export PDF")
        # Map the mm-authored scene onto the writer's logical page rectangle.
        page_rect_px = writer.pageLayout().paintRectPixels(writer.resolution())
        if page_rect_px.width() <= 0 or page_rect_px.height() <= 0:
            # Fallback: compute from physical size at the writer resolution.
            width_px = doc.width_mm / _MM_PER_INCH * writer.resolution()
            height_px = doc.height_mm / _MM_PER_INCH * writer.resolution()
            from PySide6.QtCore import QRectF

            page_rect_px = QRectF(0, 0, width_px, height_px)
        renderer.render(painter, page_rect_px)
    finally:
        painter.end()
    return Path(path)


def export_composition(
    doc: MapCompositionDocument,
    path: str | Path,
    *,
    fmt: str | None = None,
    dpi: float | None = None,
) -> Path:
    """Dispatch on extension (png/svg/pdf) or an explicit *fmt*."""
    out = Path(path)
    format_name = (fmt or out.suffix.lstrip(".") or "png").lower()
    if format_name == "svg":
        return export_composition_svg(doc, out, dpi=dpi)
    if format_name == "pdf":
        return export_composition_pdf(doc, out, dpi=dpi)
    if format_name == "png":
        return export_composition_png(doc, out, dpi=dpi)
    raise ValueError(f"unsupported composition export format {format_name!r}")
