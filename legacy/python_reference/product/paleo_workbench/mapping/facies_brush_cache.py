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

vector-perf-increment Ticket 4: :meth:`prebake` rasterises every pattern
once per scale level into a single atlas QImage (grid of cells) at backend
init — first-paint jank and per-pattern QSvgRenderer instantiation move
off the frame path; ``brush_for`` serves cells from the atlas and keeps
the lazy single-tile render as fallback (missing assets never break).
"""

from __future__ import annotations

import math
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from paleo_workbench.mapping.facies_patterns import FACIES_PATTERN_DIR

__all__ = ["FaciesPatternBrushCache"]

#: 预烘焙的缩放档（brush_for 的 size=round(32*scale) 在该档内命中同一格）。
_PREBAKE_SCALES = (1.0, 2.0, 3.0)


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
        # 图集：缩放档 → (atlas QImage, {pattern_id: cell QRectF})。
        self._atlases: dict[int, tuple[QImage, dict[str, QRectF]]] = {}
        self._prebaked = False

    def path_for(self, pattern_id: str | None) -> Path | None:
        """Resolve a pattern id to its SVG file, or ``None`` when missing."""
        if not pattern_id:
            return None
        path = self._pattern_dir / f"{pattern_id}.svg"
        return path if path.is_file() else None

    def pattern_ids(self) -> list[str]:
        """目录中可用的 pattern id（预烘焙遍历用）。"""
        try:
            return sorted(
                p.stem for p in self._pattern_dir.glob("*.svg") if p.is_file()
            )
        except OSError:
            return []

    def prebake(self) -> int:
        """把全部 pattern 按档烘焙进单一图集 QImage（Ticket 4）。

        返回烘焙成功的档数（0 = 资产目录缺失——保持懒渲染回退，不抛）。
        """
        ids = self.pattern_ids()
        if not ids:
            return 0
        levels = 0
        for scale in _PREBAKE_SCALES:
            size = max(1, round(self._tile_px * scale))
            cells: dict[str, QRectF] = {}
            cols = max(1, math.ceil(math.sqrt(len(ids))))
            rows = math.ceil(len(ids) / cols)
            atlas = QImage(
                cols * size, rows * size, QImage.Format.Format_ARGB32_Premultiplied
            )
            atlas.fill(Qt.GlobalColor.transparent)
            painter = QPainter(atlas)
            try:
                for index, pattern_id in enumerate(ids):
                    path = self.path_for(pattern_id)
                    if path is None:
                        continue
                    renderer = QSvgRenderer(str(path))
                    if not renderer.isValid():
                        continue
                    cx = (index % cols) * size
                    cy = (index // cols) * size
                    target = QRectF(float(cx), float(cy), float(size), float(size))
                    # 单元格间不画分隔（透明底）；目标区域即纹理源区域。
                    painter.save()
                    painter.setClipRect(target.toRect())
                    renderer.render(painter, target)
                    painter.restore()
                    cells[pattern_id] = target
            finally:
                painter.end()
            if cells:
                self._atlases[size] = (atlas, cells)
                levels += 1
        self._prebaked = bool(self._atlases)
        return levels

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
        brush = self._atlas_brush(str(pattern_id), size)
        if brush is None:
            brush = self._render_brush(str(pattern_id), size)
        if brush is not None:
            self._brushes[key] = brush
        return brush

    def _atlas_brush(self, pattern_id: str, size: int) -> QBrush | None:
        """图集档位命中：从图集单元格切纹理（零 SVG 解析）。"""
        entry = self._atlases.get(size)
        if entry is None:
            return None
        atlas, cells = entry
        cell = cells.get(pattern_id)
        if cell is None:
            return None
        tile = atlas.copy(cell.toRect())
        if tile.isNull():
            return None
        brush = QBrush()
        brush.setTextureImage(tile)
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
        self._atlases.clear()
        self._prebaked = False
