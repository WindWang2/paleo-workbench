from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainterPath
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsSceneMouseEvent

from paleo_workbench.mapping.document_io import features_from_document
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_commands import EditCommandStack, MoveCommand
from paleo_workbench.ui.pages.map_edit_items import (
    FaciesPolygonItem,
    FeatureItemMixin,
    WellPointItem,
)

_DEFAULT_SCENE_RECT = QRectF(-5000, -5000, 10000, 10000)
_SCENE_PAD = 50.0


class MapEditScene(QGraphicsScene):
    """Edit scene: load features, select/move tools, undo stack, dirty flag."""

    selection_ids_changed = Signal(list)
    document_dirty_changed = Signal(bool)
    command_stack_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapEditScene")
        self.setSceneRect(_DEFAULT_SCENE_RECT)
        self._items_by_id: dict[str, FeatureItemMixin] = {}
        self._tool: str = "select"
        self._command_stack = EditCommandStack(max_depth=50)
        self._dirty = False
        self._dragging = False
        self._drag_origin = QPointF()
        self._drag_last = QPointF()
        self._drag_ids: list[str] = []
        self.selectionChanged.connect(self._emit_selection_ids)

    # --- public API ---------------------------------------------------------

    def feature_count(self) -> int:
        return len(self._items_by_id)

    def item_by_id(self, feature_id: str) -> FeatureItemMixin | None:
        return self._items_by_id.get(feature_id)

    def command_stack(self) -> EditCommandStack:
        return self._command_stack

    def current_tool(self) -> str:
        return self._tool

    def set_tool(self, tool_id: str) -> None:
        self._tool = str(tool_id or "select")
        self._cancel_drag()

    def is_dirty(self) -> bool:
        return self._dirty

    def set_dirty(self, dirty: bool) -> None:
        dirty_b = bool(dirty)
        if self._dirty == dirty_b:
            return
        self._dirty = dirty_b
        self.document_dirty_changed.emit(self._dirty)

    def selected_feature_ids(self) -> list[str]:
        ids: list[str] = []
        for item in self.selectedItems():
            if isinstance(item, FeatureItemMixin):
                ids.append(item.feature_id)
        return ids

    def clear_features(self) -> None:
        self._cancel_drag()
        for item in list(self._items_by_id.values()):
            if isinstance(item, QGraphicsItem):
                self.removeItem(item)
        self._items_by_id.clear()
        self._command_stack.clear()
        self.set_dirty(False)
        self.command_stack_changed.emit()
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

    def translate_features(self, feature_ids: list[str] | tuple[str, ...], dx: float, dy: float) -> None:
        """Translate features and push a MoveCommand (marks dirty when geometry changes)."""
        ids = [fid for fid in feature_ids if fid in self._items_by_id]
        if not ids:
            return
        if float(dx) == 0.0 and float(dy) == 0.0:
            return
        cmd = MoveCommand(
            feature_ids=ids,
            dx=float(dx),
            dy=float(dy),
            apply_move=self._apply_move_one,
        )
        self._command_stack.push(cmd)
        self.set_dirty(True)
        self.command_stack_changed.emit()

    def undo(self) -> bool:
        if not self._command_stack.can_undo():
            return False
        ok = self._command_stack.undo()
        if ok:
            self.set_dirty(True)
            self.command_stack_changed.emit()
        return ok

    def redo(self) -> bool:
        if not self._command_stack.can_redo():
            return False
        ok = self._command_stack.redo()
        if ok:
            self.set_dirty(True)
            self.command_stack_changed.emit()
        return ok

    # --- mouse interaction --------------------------------------------------

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._tool == "move":
            pos = event.scenePos()
            hit = self._feature_item_at(pos)
            if hit is not None and not hit.isSelected():
                self.clearSelection()
                hit.setSelected(True)
            ids = self.selected_feature_ids()
            if ids:
                self._dragging = True
                self._drag_origin = QPointF(pos)
                self._drag_last = QPointF(pos)
                self._drag_ids = list(ids)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._dragging and self._tool == "move":
            pos = event.scenePos()
            dx = pos.x() - self._drag_last.x()
            dy = pos.y() - self._drag_last.y()
            self._drag_last = QPointF(pos)
            if dx != 0.0 or dy != 0.0:
                for fid in self._drag_ids:
                    item = self._items_by_id.get(fid)
                    if item is None or not isinstance(item, QGraphicsItem):
                        continue
                    # Visual-only preview via item position; geometry commits on release.
                    item.setPos(item.pos() + QPointF(dx, dy))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._dragging and event.button() == Qt.MouseButton.LeftButton:
            total_dx = self._drag_last.x() - self._drag_origin.x()
            total_dy = self._drag_last.y() - self._drag_origin.y()
            ids = list(self._drag_ids)
            self._reset_drag_positions()
            self._dragging = False
            self._drag_ids = []
            if ids and (total_dx != 0.0 or total_dy != 0.0):
                self.translate_features(ids, total_dx, total_dy)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # --- internals ----------------------------------------------------------

    def _emit_selection_ids(self) -> None:
        self.selection_ids_changed.emit(self.selected_feature_ids())

    def _apply_move_one(self, feature_id: str, dx: float, dy: float) -> None:
        item = self._items_by_id.get(feature_id)
        if item is None:
            return
        translate = getattr(item, "translate_by", None)
        if callable(translate):
            translate(dx, dy)

    def _feature_item_at(self, pos: QPointF) -> FeatureItemMixin | None:
        for item in self.items(pos):
            if isinstance(item, FeatureItemMixin):
                return item
        # Slight tolerance for thin edges / small wells.
        path = QPainterPath()
        path.addEllipse(pos, 0.5, 0.5)
        for item in self.items(path):
            if isinstance(item, FeatureItemMixin):
                return item
        return None

    def _reset_drag_positions(self) -> None:
        for fid in self._drag_ids:
            item = self._items_by_id.get(fid)
            if item is not None and isinstance(item, QGraphicsItem):
                item.setPos(0.0, 0.0)

    def _cancel_drag(self) -> None:
        if self._dragging:
            self._reset_drag_positions()
        self._dragging = False
        self._drag_ids = []

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
