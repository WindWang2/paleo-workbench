from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
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
_LINE_PEN = QPen(QColor(tokens.ACCENT), 0)
_LINE_PEN.setCosmetic(True)
_LINE_PEN.setWidth(2)
_LABEL_COLOR = QColor(tokens.TEXT_DARK)
_TOPOLOGY_OK = "ok"
_TOPOLOGY_WARNING = "warning"


class FeatureItemMixin:
    """Shared identity / export surface for map feature graphics items."""

    feature_id: str
    kind: str
    topology_status: str

    def to_record(self) -> dict[str, Any]:
        raise NotImplementedError

    def get_property(self, key: str) -> Any:
        raise NotImplementedError

    def set_property(self, key: str, value: Any) -> None:
        raise NotImplementedError

    def set_topology_status(self, status: str) -> None:
        self.topology_status = str(status or _TOPOLOGY_OK)

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
        self.topology_status = _TOPOLOGY_OK
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

    def get_property(self, key: str) -> Any:
        if key == "name":
            return self._name
        if key == "topology_status":
            return self.topology_status
        return None

    def set_property(self, key: str, value: Any) -> None:
        if key == "name":
            self._name = "" if value is None else str(value)
        elif key == "topology_status":
            self.set_topology_status(str(value or _TOPOLOGY_OK))

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.feature_id,
            "kind": self.kind,
            "name": self._name,
            "coordinates": [list(p) for p in self._coordinates],
            "style": dict(self._style),
            "topology_status": self.topology_status,
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
        self.topology_status = _TOPOLOGY_OK
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

    def get_property(self, key: str) -> Any:
        if key == "name":
            return self._name
        if key == "topology_status":
            return self.topology_status
        return None

    def set_property(self, key: str, value: Any) -> None:
        if key == "name":
            self._name = "" if value is None else str(value)
        elif key == "topology_status":
            self.set_topology_status(str(value or _TOPOLOGY_OK))

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.feature_id,
            "kind": self.kind,
            "name": self._name,
            "coordinates": [self._x, self._y],
            "topology_status": self.topology_status,
        }


class LineItem(QGraphicsPathItem, FeatureItemMixin):
    """Polyline feature (faults / boundaries)."""

    def __init__(
        self,
        feature_id: str,
        coordinates: list[list[float]],
        name: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.feature_id = feature_id
        self.kind = "line"
        self.topology_status = _TOPOLOGY_OK
        self._name = name or ""
        self._coordinates = [[float(p[0]), float(p[1])] for p in coordinates]
        self.setPen(_LINE_PEN)
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.setZValue(15)
        self.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable, True)
        self._rebuild_path()

    def coordinates(self) -> list[list[float]]:
        return [list(p) for p in self._coordinates]

    def set_coordinates(self, coordinates: list[list[float]]) -> None:
        self._coordinates = [[float(p[0]), float(p[1])] for p in coordinates]
        self._rebuild_path()
        self.setPos(0.0, 0.0)

    def translate_by(self, dx: float, dy: float) -> None:
        dx_f = float(dx)
        dy_f = float(dy)
        for p in self._coordinates:
            p[0] += dx_f
            p[1] += dy_f
        self._rebuild_path()
        self.setPos(0.0, 0.0)

    def get_property(self, key: str) -> Any:
        if key == "name":
            return self._name
        if key == "topology_status":
            return self.topology_status
        return None

    def set_property(self, key: str, value: Any) -> None:
        if key == "name":
            self._name = "" if value is None else str(value)
        elif key == "topology_status":
            self.set_topology_status(str(value or _TOPOLOGY_OK))

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.feature_id,
            "kind": self.kind,
            "name": self._name,
            "coordinates": [list(p) for p in self._coordinates],
            "topology_status": self.topology_status,
        }

    def _rebuild_path(self) -> None:
        path = QPainterPath()
        if not self._coordinates:
            self.setPath(path)
            return
        path.moveTo(float(self._coordinates[0][0]), float(self._coordinates[0][1]))
        for p in self._coordinates[1:]:
            path.lineTo(float(p[0]), float(p[1]))
        self.setPath(path)


class LabelItem(QGraphicsSimpleTextItem, FeatureItemMixin):
    """Text annotation anchored at map coordinates."""

    def __init__(
        self,
        feature_id: str,
        x: float,
        y: float,
        text: str = "",
        name: str = "",
        parent=None,
    ):
        display = text or name or ""
        super().__init__(display, parent)
        self.feature_id = feature_id
        self.kind = "label"
        self.topology_status = _TOPOLOGY_OK
        self._text = display
        self._name = name or display
        self._x = float(x)
        self._y = float(y)
        self.setBrush(QBrush(_LABEL_COLOR))
        font = QFont()
        font.setPointSize(10)
        self.setFont(font)
        self.setZValue(30)
        self.setFlag(QGraphicsSimpleTextItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setPos(self._x, self._y)

    def translate_by(self, dx: float, dy: float) -> None:
        self._x = float(self._x) + float(dx)
        self._y = float(self._y) + float(dy)
        self.setPos(self._x, self._y)

    def get_property(self, key: str) -> Any:
        if key == "name":
            return self._name
        if key == "text":
            return self._text
        if key == "topology_status":
            return self.topology_status
        return None

    def set_property(self, key: str, value: Any) -> None:
        if key == "name":
            self._name = "" if value is None else str(value)
        elif key == "text":
            self._text = "" if value is None else str(value)
            self.setText(self._text)
        elif key == "topology_status":
            self.set_topology_status(str(value or _TOPOLOGY_OK))

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.feature_id,
            "kind": self.kind,
            "name": self._name,
            "text": self._text,
            "coordinates": [self._x, self._y],
            "topology_status": self.topology_status,
        }
