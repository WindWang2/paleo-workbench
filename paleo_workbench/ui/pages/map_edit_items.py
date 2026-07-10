from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QBrush, QColor, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsPolygonItem

from paleo_workbench.ui import tokens

# Default well marker radius in scene/map units.
WELL_RADIUS = 0.4

_FACIES_FILL = QColor(tokens.PRIMARY)
_FACIES_FILL.setAlpha(70)
_FACIES_PEN = QPen(QColor(tokens.PRIMARY), 0)  # cosmetic width
_WELL_FILL = QBrush(QColor(tokens.TEAL))
_WELL_PEN = QPen(QColor(tokens.TEXT_DARK), 0)


class FeatureItemMixin:
    """Shared identity / export surface for map feature graphics items."""

    feature_id: str
    kind: str

    def to_record(self) -> dict[str, Any]:
        raise NotImplementedError


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

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.feature_id,
            "kind": self.kind,
            "name": self._name,
            "coordinates": [self._x, self._y],
        }
