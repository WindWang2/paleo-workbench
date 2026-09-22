from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsPathItem, QGraphicsScene

from paleo_workbench.mapping.geometry_schema import new_feature_id
from paleo_workbench.ui import tokens

_DRAFT_MIN_DIST = 1e-9

_DRAFT_PEN = QPen(QColor(tokens.ACCENT), 0)
_DRAFT_PEN.setCosmetic(True)
_DRAFT_PEN.setWidth(1)
_DRAFT_PEN.setStyle(Qt.PenStyle.DashLine)


class MapDraftManager:
    """Manages polyline/facies draft points and scene preview path item."""

    def __init__(self, scene: QGraphicsScene) -> None:
        self._scene = scene
        self._draft_points: list[list[float]] = []
        self._draft_kind: str | None = None
        self._draft_preview: QGraphicsPathItem | None = None

    @property
    def points(self) -> list[list[float]]:
        return self._draft_points

    @property
    def kind(self) -> str | None:
        return self._draft_kind

    def point_count(self) -> int:
        return len(self._draft_points)

    def append_point(self, x: float, y: float, kind: str = "line") -> None:
        self._draft_kind = kind
        if self._draft_points:
            last = self._draft_points[-1]
            if abs(last[0] - x) < _DRAFT_MIN_DIST and abs(last[1] - y) < _DRAFT_MIN_DIST:
                return
        self._draft_points.append([float(x), float(y)])
        self.update_preview(float(x), float(y), close_preview=(kind == "facies"))

    def update_preview(
        self,
        cursor_x: float,
        cursor_y: float,
        close_preview: bool = False,
    ) -> None:
        if self._draft_preview is None:
            self._draft_preview = QGraphicsPathItem()
            self._draft_preview.setPen(_DRAFT_PEN)
            self._draft_preview.setZValue(50)
            self._scene.addItem(self._draft_preview)
        path = QPainterPath()
        pts = self._draft_points
        if not pts:
            self._draft_preview.setPath(path)
            return
        path.moveTo(pts[0][0], pts[0][1])
        for p in pts[1:]:
            path.lineTo(p[0], p[1])
        path.lineTo(float(cursor_x), float(cursor_y))
        if close_preview and len(pts) >= 2:
            path.lineTo(pts[0][0], pts[0][1])
        self._draft_preview.setPath(path)

    def cancel(self) -> None:
        self._draft_points = []
        self._draft_kind = None
        if self._draft_preview is not None:
            self._scene.removeItem(self._draft_preview)
            self._draft_preview = None

    def finish_line(self, create_feature_fn: Callable[[dict], str | None]) -> str | None:
        if self._draft_kind not in (None, "line"):
            return None
        points = [list(p) for p in self._draft_points]
        self.cancel()
        if len(points) < 2:
            return None
        return create_feature_fn({
            "id": new_feature_id("line"),
            "kind": "line",
            "name": "",
            "coordinates": points,
        })

    def finish_facies(
        self,
        create_feature_fn: Callable[[dict], str | None],
        refresh_topology_fn: Callable[[str], None],
    ) -> str | None:
        if self._draft_kind not in (None, "facies"):
            return None
        points = [list(p) for p in self._draft_points]
        self.cancel()
        if len(points) < 3:
            return None
        ring = [list(p) for p in points]
        if ring[0][0] != ring[-1][0] or ring[0][1] != ring[-1][1]:
            ring.append([ring[0][0], ring[0][1]])
        fid = create_feature_fn({
            "id": new_feature_id("facies"),
            "kind": "facies",
            "name": "新相带",
            "coordinates": ring,
            "style": {},
        })
        if fid:
            refresh_topology_fn(fid)
        return fid
