"""Facies SVG pattern tiles as cached texture brushes for the fallback renderer.

The fallback map backend paints with plain QPainter (no QGIS), so facies
polygon fills combine a solid base colour with a black-linework SVG tile
from :mod:`paleo_workbench.mapping.facies_patterns`.  Tiles are 32x32
viewBox transparent-background linework; the correct composition is the
base fill first, then the same path filled with this tiled texture brush
so the base colour shows through the transparent gaps.

Tiles render to QImage (never QPixmap): the fallback backend rasterises
frames on a worker thread and QPixmap is confined to the GUI thread,
while QImage painting is thread-safe.  Brushes are keyed by
``(pattern_id, tile_px)`` so HiDPI/export scales re-render once and every
frame after that is a cache hit.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from paleo_workbench.mapping.facies_patterns import FACIES_PATTERN_DIR

__all__ = ["FaciesPatternBrushCache"]


class FaciesPatternBrushCache:
    """Render ``FACIES_PATTERN_DIR/<pattern_id>.svg`` tiles to texture brushes."""

    def __init__(
        self,
        pattern_dir: Path | str = FACIES_PATTERN_DIR,
        tile_px: int = 32,
    ) -> None:
        self._pattern_dir = Path(pattern_dir)
        self._tile_px = max(1, int(tile_px))
        self._brushes: dict[tuple[str, int], QBrush] = {}

    def path_for(self, pattern_id: str | None) -> Path | None:
        """Resolve a pattern id to its SVG file, or ``None`` when missing."""
        if not pattern_id:
            return None
        path = self._pattern_dir / f"{pattern_id}.svg"
        return path if path.is_file() else None

    def brush_for(self, pattern_id: str | None, *, scale: float = 1.0) -> QBrush | None:
        """Return the cached tiling texture brush for a pattern id.

        ``None`` means the tile is missing or invalid — callers keep the
        solid base fill.  Never raises: an unreadable asset must not break
        a frame.
        """
        if not pattern_id:
            return None
        size = max(1, round(self._tile_px * max(0.05, float(scale))))
        key = (str(pattern_id), size)
        cached = self._brushes.get(key)
        if cached is not None:
            return cached
        brush = self._render_brush(str(pattern_id), size)
        if brush is not None:
            self._brushes[key] = brush
        return brush

    def _render_brush(self, pattern_id: str, size: int) -> QBrush | None:
        try:
            path = self.path_for(pattern_id)
            if path is None:
                return None
            renderer = QSvgRenderer(str(path))
            if not renderer.isValid():
                return None
            tile = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
            tile.fill(Qt.GlobalColor.transparent)
            painter = QPainter(tile)
            try:
                renderer.render(painter, QRectF(0.0, 0.0, float(size), float(size)))
            finally:
                painter.end()
            if tile.isNull():
                return None
            brush = QBrush()
            brush.setTextureImage(tile)
            return brush
        except Exception:
            return None

    def clear(self) -> None:
        """Drop all cached brushes (tests / asset hot-reload)."""
        self._brushes.clear()
