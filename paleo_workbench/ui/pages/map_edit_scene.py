from __future__ import annotations

from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QKeyEvent, QPainterPath
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsSceneMouseEvent

from paleo_workbench.mapping import map_edit_api as api
from paleo_workbench.mapping.document_io import features_from_document
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_commands import (
    EditCommandStack,
    MoveCommand,
    VertexEditCommand,
)
from paleo_workbench.ui.pages.map_edit_items import (
    FaciesPolygonItem,
    FeatureItemMixin,
    VertexHandleItem,
    WellPointItem,
)

_DEFAULT_SCENE_RECT = QRectF(-5000, -5000, 10000, 10000)
_SCENE_PAD = 50.0
# Edge hit tolerance for double-click insert (scene units, squared compared via dist2).
_EDGE_HIT_TOL2 = 0.75 * 0.75


class MapEditScene(QGraphicsScene):
    """Edit scene: load features, select/move/vertex tools, undo stack, dirty flag."""

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
        self._vertex_handles: list[VertexHandleItem] = []
        self._active_vertex_index: int | None = None
        self._vertex_drag = False
        self._vertex_drag_feature_id: str | None = None
        self._vertex_drag_index: int | None = None
        self._vertex_drag_origin = QPointF()
        self._vertex_drag_start_xy: tuple[float, float] | None = None
        self.selectionChanged.connect(self._on_selection_changed)

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
        self._cancel_vertex_drag()
        self._refresh_vertex_handles()

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

    def vertex_handle_count(self) -> int:
        return len(self._vertex_handles)

    def vertex_handles(self) -> list[VertexHandleItem]:
        return list(self._vertex_handles)

    def set_active_vertex_index(self, index: int | None) -> None:
        self._active_vertex_index = None if index is None else int(index)

    def active_vertex_index(self) -> int | None:
        return self._active_vertex_index

    def clear_features(self) -> None:
        self._cancel_drag()
        self._cancel_vertex_drag()
        self._clear_vertex_handles()
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
        self._refresh_vertex_handles()

    def apply_set_vertex(self, feature_id: str, index: int, x: float, y: float) -> bool:
        """Set one vertex via VertexEditCommand. Returns True if applied."""
        item = self._items_by_id.get(feature_id)
        if not isinstance(item, FaciesPolygonItem):
            return False
        old = item.coordinates()
        new = [list(p) for p in old]
        try:
            api.set_vertex(new, int(index), float(x), float(y))
        except (IndexError, TypeError, ValueError):
            return False
        return self._push_vertex_edit(feature_id, old, new)

    def apply_insert_vertex(self, feature_id: str, index: int, x: float, y: float) -> bool:
        item = self._items_by_id.get(feature_id)
        if not isinstance(item, FaciesPolygonItem):
            return False
        old = item.coordinates()
        new = [list(p) for p in old]
        try:
            api.insert_vertex(new, int(index), float(x), float(y))
        except (IndexError, TypeError, ValueError):
            return False
        return self._push_vertex_edit(feature_id, old, new)

    def apply_delete_vertex(self, feature_id: str, index: int) -> bool:
        item = self._items_by_id.get(feature_id)
        if not isinstance(item, FaciesPolygonItem):
            return False
        old = item.coordinates()
        new = [list(p) for p in old]
        if not api.delete_vertex(new, int(index)):
            return False
        return self._push_vertex_edit(feature_id, old, new)

    def undo(self) -> bool:
        if not self._command_stack.can_undo():
            return False
        ok = self._command_stack.undo()
        if ok:
            self.set_dirty(True)
            self.command_stack_changed.emit()
            self._refresh_vertex_handles()
        return ok

    def redo(self) -> bool:
        if not self._command_stack.can_redo():
            return False
        ok = self._command_stack.redo()
        if ok:
            self.set_dirty(True)
            self.command_stack_changed.emit()
            self._refresh_vertex_handles()
        return ok

    # --- mouse / key interaction --------------------------------------------

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._tool == "vertex":
            pos = event.scenePos()
            handle = self._handle_at(pos)
            if handle is not None:
                self._active_vertex_index = handle.vertex_index
                handle.setSelected(True)
                self._vertex_drag = True
                self._vertex_drag_feature_id = handle.feature_id
                self._vertex_drag_index = handle.vertex_index
                self._vertex_drag_origin = QPointF(pos)
                item = self._items_by_id.get(handle.feature_id)
                if isinstance(item, FaciesPolygonItem):
                    coords = item.coordinates()
                    idx = handle.vertex_index
                    if 0 <= idx < len(coords):
                        self._vertex_drag_start_xy = (coords[idx][0], coords[idx][1])
                    else:
                        self._vertex_drag_start_xy = None
                else:
                    self._vertex_drag_start_xy = None
                event.accept()
                return
            # Click feature to select for vertex editing
            hit = self._feature_item_at(pos)
            if hit is not None and isinstance(hit, FaciesPolygonItem):
                if not hit.isSelected() or len(self.selected_feature_ids()) != 1:
                    self.clearSelection()
                    hit.setSelected(True)
                event.accept()
                return
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
        if self._vertex_drag and self._tool == "vertex":
            pos = event.scenePos()
            fid = self._vertex_drag_feature_id
            idx = self._vertex_drag_index
            item = self._items_by_id.get(fid) if fid else None
            if isinstance(item, FaciesPolygonItem) and idx is not None:
                coords = item.coordinates()
                try:
                    api.set_vertex(coords, idx, pos.x(), pos.y())
                except (IndexError, TypeError, ValueError):
                    pass
                else:
                    item.set_coordinates(coords)
                    self._sync_handle_positions(item)
            event.accept()
            return
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
        if self._vertex_drag and event.button() == Qt.MouseButton.LeftButton:
            fid = self._vertex_drag_feature_id
            idx = self._vertex_drag_index
            start = self._vertex_drag_start_xy
            pos = event.scenePos()
            self._vertex_drag = False
            self._vertex_drag_feature_id = None
            self._vertex_drag_index = None
            self._vertex_drag_start_xy = None
            item = self._items_by_id.get(fid) if fid else None
            if isinstance(item, FaciesPolygonItem) and idx is not None and start is not None:
                end_x, end_y = float(pos.x()), float(pos.y())
                if end_x != start[0] or end_y != start[1]:
                    # Restore original, then commit via command for undo.
                    restored = item.coordinates()
                    try:
                        api.set_vertex(restored, idx, start[0], start[1])
                    except (IndexError, TypeError, ValueError):
                        pass
                    else:
                        item.set_coordinates(restored)
                    self.apply_set_vertex(fid, idx, end_x, end_y)
                else:
                    self._refresh_vertex_handles()
            event.accept()
            return
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

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._tool == "vertex":
            fid = self._single_editable_feature_id()
            if fid is not None:
                item = self._items_by_id.get(fid)
                if isinstance(item, FaciesPolygonItem):
                    pos = event.scenePos()
                    # Prefer edge insert when not on an existing handle.
                    if self._handle_at(pos) is None:
                        edge = api.closest_edge(item.coordinates(), pos.x(), pos.y())
                        if edge is not None:
                            i, qx, qy, dist2 = edge
                            if dist2 <= _EDGE_HIT_TOL2:
                                self.apply_insert_vertex(fid, i + 1, qx, qy)
                                event.accept()
                                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._tool == "vertex" and event.key() in (
            Qt.Key.Key_Delete,
            Qt.Key.Key_Backspace,
        ):
            fid = self._single_editable_feature_id()
            idx = self._active_vertex_index
            if fid is not None and idx is not None:
                if self.apply_delete_vertex(fid, idx):
                    self._active_vertex_index = None
                    event.accept()
                    return
        super().keyPressEvent(event)

    # --- internals ----------------------------------------------------------

    def _on_selection_changed(self) -> None:
        self._emit_selection_ids()
        self._refresh_vertex_handles()

    def _emit_selection_ids(self) -> None:
        self.selection_ids_changed.emit(self.selected_feature_ids())

    def _push_vertex_edit(
        self,
        feature_id: str,
        old_coords: list[list[float]],
        new_coords: list[list[float]],
    ) -> bool:
        if old_coords == new_coords:
            return False
        cmd = VertexEditCommand(
            feature_id=feature_id,
            old_coordinates=old_coords,
            new_coordinates=new_coords,
            apply_coordinates=self._apply_coordinates,
        )
        self._command_stack.push(cmd)
        self.set_dirty(True)
        self.command_stack_changed.emit()
        self._refresh_vertex_handles()
        return True

    def _apply_coordinates(self, feature_id: str, coordinates: list[list[float]]) -> None:
        item = self._items_by_id.get(feature_id)
        if isinstance(item, FaciesPolygonItem):
            item.set_coordinates(coordinates)

    def _apply_move_one(self, feature_id: str, dx: float, dy: float) -> None:
        item = self._items_by_id.get(feature_id)
        if item is None:
            return
        translate = getattr(item, "translate_by", None)
        if callable(translate):
            translate(dx, dy)

    def _single_editable_feature_id(self) -> str | None:
        ids = self.selected_feature_ids()
        if len(ids) != 1:
            return None
        item = self._items_by_id.get(ids[0])
        if isinstance(item, FaciesPolygonItem):
            return ids[0]
        return None

    def _clear_vertex_handles(self) -> None:
        for h in self._vertex_handles:
            self.removeItem(h)
        self._vertex_handles.clear()

    def _refresh_vertex_handles(self) -> None:
        self._clear_vertex_handles()
        if self._tool != "vertex":
            return
        fid = self._single_editable_feature_id()
        if fid is None:
            return
        item = self._items_by_id.get(fid)
        if not isinstance(item, FaciesPolygonItem):
            return
        coords = item.coordinates()
        if len(coords) < 2:
            return
        closed = (
            len(coords) >= 2
            and float(coords[0][0]) == float(coords[-1][0])
            and float(coords[0][1]) == float(coords[-1][1])
        )
        count = len(coords) - 1 if closed else len(coords)
        for i in range(count):
            handle = VertexHandleItem(fid, i, coords[i][0], coords[i][1])
            self.addItem(handle)
            self._vertex_handles.append(handle)

    def _sync_handle_positions(self, item: FaciesPolygonItem) -> None:
        coords = item.coordinates()
        for handle in self._vertex_handles:
            if handle.feature_id != item.feature_id:
                continue
            idx = handle.vertex_index
            if 0 <= idx < len(coords):
                handle.setPos(coords[idx][0], coords[idx][1])

    def _handle_at(self, pos: QPointF) -> VertexHandleItem | None:
        for item in self.items(pos):
            if isinstance(item, VertexHandleItem):
                return item
        path = QPainterPath()
        path.addEllipse(pos, 0.4, 0.4)
        for item in self.items(path):
            if isinstance(item, VertexHandleItem):
                return item
        return None

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

    def _cancel_vertex_drag(self) -> None:
        if self._vertex_drag and self._vertex_drag_feature_id and self._vertex_drag_start_xy is not None:
            item = self._items_by_id.get(self._vertex_drag_feature_id)
            idx = self._vertex_drag_index
            start = self._vertex_drag_start_xy
            if isinstance(item, FaciesPolygonItem) and idx is not None:
                coords = item.coordinates()
                try:
                    api.set_vertex(coords, idx, start[0], start[1])
                    item.set_coordinates(coords)
                except (IndexError, TypeError, ValueError):
                    pass
        self._vertex_drag = False
        self._vertex_drag_feature_id = None
        self._vertex_drag_index = None
        self._vertex_drag_start_xy = None

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
