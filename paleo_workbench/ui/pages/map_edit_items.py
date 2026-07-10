from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
)

from paleo_workbench.ui import tokens

# Default well marker radius in scene/map units.
WELL_RADIUS = 0.4
# Vertex handle half-size in scene/map units.
VERTEX_HANDLE_HALF = 0.35

_FACIES_FILL = QColor(tokens.PRIMARY)
_FACIES_FILL.setAlpha(70)
_FACIES_PEN = QPen(QColor(tokens.PRIMARY), 0)  # cosmetic width
_WELL_FILL = QBrush(QColor(tokens.TEAL))
_WELL_PEN = QPen(QColor(tokens.TEXT_DARK), 0)
_HANDLE_FILL = QBrush(QColor(tokens.TEAL))
_HANDLE_PEN = QPen(QColor(tokens.TEXT_DARK), 0)


class FeatureItemMixin:
    """Shared identity / export surface for map feature graphics items."""

    feature_id: str
    kind: str

    def to_record(self) -> dict[str, Any]:
        raise NotImplementedError


class VertexHandleItem(QGraphicsRectItem):
    """Draggable handle for a single ring vertex (scene-managed, not a feature)."""

    def __init__(
        self,
        feature_id: str,
        vertex_index: int,
        x: float,
        y: float,
        half: float = VERTEX_HANDLE_HALF,
        parent=None,
    ):
        h = float(half)
        super().__init__(QRectF(-h, -h, 2 * h, 2 * h), parent)
        self.feature_id = str(feature_id)
        self.vertex_index = int(vertex_index)
        self.setPos(float(x), float(y))
        self.setBrush(_HANDLE_FILL)
        self.setPen(_HANDLE_PEN)
        self.setZValue(100)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)


class FaciesPolygonItem(QGraphicsPolygonItem, FeatureItemMixin):
    """Facies polygon feature on the edit scene."""

    def __init__(
        self,
        feature_id: str,
        coordinates: list[list[float]],
        name: str = "",
        style: dict[str, Any] | None = None,
        parent=None,
    ):
        polygon = QPolygonF([QPointF(float(p[0]), float(p[1])) for p in coordinates])
        super().__init__(polygon, parent)
        self.feature_id = feature_id
        self.kind = "facies"
        self._name = name or ""
        self._style = dict(style or {})
        self._coordinates = [[float(p[0]), float(p[1])] for p in coordinates]
        self.setBrush(QBrush(_FACIES_FILL))
        self.setPen(_FACIES_PEN)
        self.setZValue(10)
        self.setFlag(QGraphicsPolygonItem.GraphicsItemFlag.ItemIsSelectable, True)

    def coordinates(self) -> list[list[float]]:
        return [list(p) for p in self._coordinates]

    def set_coordinates(self, coordinates: list[list[float]]) -> None:
        """Replace ring coordinates and refresh the polygon path."""
        self._coordinates = [[float(p[0]), float(p[1])] for p in coordinates]
        self.setPolygon(QPolygonF([QPointF(p[0], p[1]) for p in self._coordinates]))
        self.setPos(0.0, 0.0)

    def translate_by(self, dx: float, dy: float) -> None:
        """Shift polygon vertices and update the graphics path."""
        dx_f = float(dx)
        dy_f = float(dy)
        for p in self._coordinates:
            p[0] += dx_f
            p[1] += dy_f
        self.setPolygon(QPolygonF([QPointF(p[0], p[1]) for p in self._coordinates]))
        self.setPos(0.0, 0.0)

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.feature_id,
            "kind": self.kind,
            "name": self._name,
            "coordinates": [list(p) for p in self._coordinates],
            "style": dict(self._style),
        }


class WellPointItem(QGraphicsEllipseItem, FeatureItemMixin):
    """Well point feature as a small ellipse centered on map coordinates."""

    def __init__(
        self,
        feature_id: str,
        x: float,
        y: float,
        name: str = "",
        radius: float = WELL_RADIUS,
        parent=None,
    ):
        r = float(radius)
        super().__init__(QRectF(float(x) - r, float(y) - r, 2 * r, 2 * r), parent)
        self.feature_id = feature_id
        self.kind = "well"
        self._name = name or ""
        self._x = float(x)
        self._y = float(y)
        self._radius = r
        self.setBrush(_WELL_FILL)
        self.setPen(_WELL_PEN)
        self.setZValue(20)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable, True)

    def translate_by(self, dx: float, dy: float) -> None:
        """Shift well point and update the ellipse rect."""
        self._x = float(self._x) + float(dx)
        self._y = float(self._y) + float(dy)
        r = self._radius
        self.setRect(QRectF(self._x - r, self._y - r, 2 * r, 2 * r))
        self.setPos(0.0, 0.0)

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.feature_id,
            "kind": self.kind,
            "name": self._name,
            "coordinates": [self._x, self._y],
        }
