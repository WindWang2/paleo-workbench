from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene

from paleo_workbench.mapping.document_io import features_from_document
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_items import (
    FaciesPolygonItem,
    FeatureItemMixin,
    WellPointItem,
)

_DEFAULT_SCENE_RECT = QRectF(-5000, -5000, 10000, 10000)
_SCENE_PAD = 50.0


class MapEditScene(QGraphicsScene):
    """Edit scene that owns map feature graphics items (read-only load for V1 task 3)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapEditScene")
        self.setSceneRect(_DEFAULT_SCENE_RECT)
        self._items_by_id: dict[str, FeatureItemMixin] = {}

    def feature_count(self) -> int:
        return len(self._items_by_id)

    def item_by_id(self, feature_id: str) -> FeatureItemMixin | None:
        return self._items_by_id.get(feature_id)

    def clear_features(self) -> None:
        for item in list(self._items_by_id.values()):
            if isinstance(item, QGraphicsItem):
                self.removeItem(item)
        self._items_by_id.clear()
        self.setSceneRect(_DEFAULT_SCENE_RECT)

    def load_document(self, doc: PaleoMapDocument | None) -> None:
        """Normalize document features and create graphics items. Bad geometry is skipped."""
        self.clear_features()
        if doc is None:
            return
        for record in features_from_document(doc):
            try:
                item = self._item_from_record(record)
            except Exception:
                continue
            if item is None:
                continue
            self.addItem(item)
            self._items_by_id[item.feature_id] = item
        self._fit_scene_rect()

    def _item_from_record(self, record: dict[str, Any]) -> FeatureItemMixin | None:
        kind = record.get("kind")
        feature_id = record.get("id")
        if not feature_id:
            return None
        if kind == "facies":
            return self._make_facies(record)
        if kind == "well":
            return self._make_well(record)
        # lines/labels deferred to later tasks
        return None

    def _make_facies(self, record: dict[str, Any]) -> FaciesPolygonItem | None:
        coords = record.get("coordinates") or []
        if not isinstance(coords, (list, tuple)) or len(coords) < 3:
            return None
        points: list[list[float]] = []
        for p in coords:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                return None
            try:
                points.append([float(p[0]), float(p[1])])
            except (TypeError, ValueError):
                return None
        return FaciesPolygonItem(
            feature_id=str(record["id"]),
            coordinates=points,
            name=str(record.get("name") or ""),
            style=record.get("style") or {},
        )

    def _make_well(self, record: dict[str, Any]) -> WellPointItem | None:
        coords = record.get("coordinates") or [0, 0]
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            return None
        try:
            x = float(coords[0])
            y = float(coords[1])
        except (TypeError, ValueError):
            return None
        return WellPointItem(
            feature_id=str(record["id"]),
            x=x,
            y=y,
            name=str(record.get("name") or ""),
        )

    def _fit_scene_rect(self) -> None:
        if not self._items_by_id:
            self.setSceneRect(_DEFAULT_SCENE_RECT)
            return
        bounds = self.itemsBoundingRect()
        if bounds.isNull() or not bounds.isValid():
            self.setSceneRect(_DEFAULT_SCENE_RECT)
            return
        self.setSceneRect(bounds.adjusted(-_SCENE_PAD, -_SCENE_PAD, _SCENE_PAD, _SCENE_PAD))
