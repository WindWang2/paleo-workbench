from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QKeyEvent, QPainterPath
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsSceneMouseEvent

import geoviz as api
from paleo_workbench.mapping.document_io import features_from_document
from paleo_workbench.mapping.feature_query_index import FeatureQueryIndex
from paleo_workbench.mapping.geometry_schema import new_feature_id
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_commands import (
    CreateFeatureCommand,
    EditCommandStack,
    MoveCommand,
    PropertyChangeCommand,
    RingEditCommand,
    VertexEditCommand,
)
from paleo_workbench.ui.pages.map_edit_draft import MapDraftManager
from paleo_workbench.ui.pages.map_edit_factory import item_from_record
from paleo_workbench.ui.pages.map_edit_items import (
    FaciesPolygonItem,
    FeatureItemMixin,
    LabelItem,
    LineItem,
    VertexHandleItem,
    WellPointItem,
)
from paleo_workbench.ui.pages.map_edit_snap import MapSnapManager
from paleo_workbench.ui.pages.map_edit_topology import (
    apply_adjacency_warnings,
    facies_geometry_issues,
    plan_merge_facies,
    plan_split_facies,
    plan_topology_rebuild,
)

_DEFAULT_SCENE_RECT = QRectF(-5000, -5000, 10000, 10000)
_SCENE_PAD = 50.0
# Pick, snap and handle tolerances are screen pixels converted to scene units
# via the current view scale. World-unit constants made degree-CRS documents
# pick/snap within tens of kilometers (0.5 units = 0.5 deg) and made handles
# sub-pixel at fit view.
_DEFAULT_SNAP_TOL = 8.0
# Edge hit tolerance for double-click insert (screen pixels, squared compare).
_EDGE_HIT_TOL = 8.0
# Vertex-handle and feature pick radii in screen pixels. The handle radius is
# kept below the edge tolerance so double-click edge inserts are not shadowed
# by nearby vertices on short edges.
_HANDLE_PICK_TOL = 4.0
_FEATURE_PICK_TOL = 8.0
# Adjacency-warning gap tolerance stays a world-unit geometry gate; it must
# not inherit the screen-pixel snap tolerance.
_ADJACENCY_GAP_TOL = 0.5


class MapEditScene(QGraphicsScene):
    """Edit scene: load features, select/move/vertex/line/label tools, undo stack, dirty flag."""

    selection_ids_changed = Signal(list)
    document_dirty_changed = Signal(bool)
    command_stack_changed = Signal()
    topology_issues_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("MapEditScene")
        self.setSceneRect(_DEFAULT_SCENE_RECT)
        self._items_by_id: dict[str, FeatureItemMixin] = {}
        self._hit_query_index = FeatureQueryIndex()
        self._loading_features = False
        self._tool: str = "select"
        self._bound_document: PaleoMapDocument | None = None
        self._edit_history_max = 200
        self._command_stack = EditCommandStack(
            max_depth=50,
            on_push=lambda cmd: self._append_edit_log(cmd, action="do"),
            on_undo=lambda cmd: self._append_edit_log(cmd, action="undo"),
            on_redo=lambda cmd: self._append_edit_log(cmd, action="redo"),
        )
        self._dirty = False
        self._dragging = False
        self._drag_origin = QPointF()
        self._drag_last = QPointF()
        self._drag_ids: list[str] = []
        self._vertex_handles: list[VertexHandleItem] = []
        self._active_vertex_index: int | None = None
        self._active_vertex_part_index = 0
        self._active_vertex_ring_index = 0
        self._vertex_drag = False
        self._vertex_drag_feature_id: str | None = None
        self._vertex_drag_index: int | None = None
        self._vertex_drag_part_index = 0
        self._vertex_drag_ring_index = 0
        self._vertex_drag_origin = QPointF()
        self._vertex_drag_start_xy: tuple[float, float] | None = None
        # Layer visibility by kind
        self._layer_visible: dict[str, bool] = {
            "facies": True,
            "well": True,
            "line": True,
            "label": True,
        }
        self._snap_manager = MapSnapManager(_DEFAULT_SNAP_TOL)
        # Grid snap index, rebuilt only when the snap candidate generation
        # (MapSnapManager.build_count) changes — never per mouse move.
        self._snap_index: api.SnapCandidateIndex | None = None
        self._snap_index_build = -1
        # Navigation display LOD: while active, path items paint simplified
        # bounding-box geometry. Display-only — never touches coordinates.
        self._navigation_lod = False
        # Last published topology issue list; emitted only on content change.
        self._last_published_issues: list[dict[str, object]] | None = None
        self._draft_manager = MapDraftManager(self)
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
        prev = self._tool
        self._tool = str(tool_id or "select")
        self._cancel_drag()
        self._cancel_vertex_drag()
        if prev in {"line", "facies"} and self._tool not in {"line", "facies"}:
            self._cancel_draft()
        elif prev != self._tool and self._tool in {"line", "facies"}:
            self._cancel_draft()
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

    @property
    def _snap_enabled(self) -> bool:
        return self._snap_manager.enabled

    @_snap_enabled.setter
    def _snap_enabled(self, value: bool) -> None:
        self._snap_manager.enabled = value

    @property
    def _snap_tolerance(self) -> float:
        return self._snap_manager.tolerance

    @_snap_tolerance.setter
    def _snap_tolerance(self, value: float) -> None:
        self._snap_manager.tolerance = value

    @property
    def _reference_snap_points(self) -> list[tuple[float, float]]:
        return self._snap_manager.reference_points

    def set_snap_enabled(self, enabled: bool) -> None:
        self._snap_manager.enabled = enabled

    def snap_enabled(self) -> bool:
        return self._snap_manager.enabled

    def set_snap_tolerance(self, tol: float) -> None:
        self._snap_manager.tolerance = tol

    def set_reference_snap_points(self, points: list[tuple[float, float]]) -> None:
        self._snap_manager.set_reference_points(points)

    def set_layer_visible(self, kind: str, visible: bool) -> None:
        key = str(kind)
        self._layer_visible[key] = bool(visible)
        for item in self._items_by_id.values():
            if item.kind == key and isinstance(item, QGraphicsItem):
                item.setVisible(bool(visible))
        # Hidden geometry must leave snap caches so pick/snap stay consistent.
        self._invalidate_snap_candidates()

    def layer_is_visible(self, kind: str) -> bool:
        return self._layer_visible.get(str(kind), True)

    def features_to_records(self) -> list[dict[str, Any]]:
        """Export all feature items as normalized records."""
        return [item.to_record() for item in self._items_by_id.values()]

    def export_features(self) -> list[dict[str, Any]]:
        """Alias used by save-draft path."""
        return self.features_to_records()

    def hit_test_at(self, x: float, y: float, tolerance: float = 0.0) -> str | None:
        """Return feature id under map point via map_edit_api (Python or C++).

        ``tolerance`` is in screen pixels and is converted to scene units at the
        current view scale, so degree-CRS documents do not pick within tens of
        kilometers. Only features on visible layers are considered so hidden
        geometry cannot be selected or moved via the geometry hit path (Qt item
        stack already skips invisible items; this keeps the C++/Python geometry
        path aligned).
        """
        tolerance_units = float(tolerance) * self._units_per_pixel()
        records = self._hit_query_index.query(
            float(x), float(y), tolerance_units, visible=self.layer_is_visible
        )
        return api.hit_test(records, float(x), float(y), tolerance=tolerance_units)

    def hit_query_diagnostics(self) -> dict[str, int]:
        """Expose bounded-query counters for profiling and regression tests."""
        return self._hit_query_index.diagnostics()

    def clear_features(self) -> None:
        self._cancel_drag()
        self._cancel_vertex_drag()
        self._cancel_line_draft()
        self._clear_vertex_handles()
        for item in list(self._items_by_id.values()):
            if isinstance(item, QGraphicsItem):
                self.removeItem(item)
        self._items_by_id.clear()
        self._hit_query_index.clear()
        self._invalidate_snap_candidates()
        self._command_stack.clear()
        self._bound_document = None
        self.set_dirty(False)
        self.command_stack_changed.emit()
        self.setSceneRect(_DEFAULT_SCENE_RECT)

    def load_document(self, doc: PaleoMapDocument | None) -> None:
        """Normalize document features and create graphics items. Bad geometry is skipped."""
        self.clear_features()
        if doc is None:
            return
        self._bound_document = doc
        self._loading_features = True
        try:
            for record in features_from_document(doc):
                try:
                    item = self._item_from_record(record)
                except Exception:
                    continue
                if item is None:
                    continue
                self._register_item(item)
        finally:
            self._loading_features = False
        self._hit_query_index.rebuild(
            self._items_by_id.values(), record_for_item=self._hit_record_for_item
        )
        self._fit_scene_rect()

    def _append_edit_log(self, command: object, *, action: str = "do") -> None:
        """Persist a compact audit row onto the bound document's edit_history."""
        doc = self._bound_document
        if doc is None:
            return
        entry: dict[str, Any] = {
            "op": type(command).__name__,
            "action": str(action),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        # Best-effort payload for common command types (no full geometry dump).
        if hasattr(command, "feature_ids"):
            entry["feature_ids"] = list(getattr(command, "feature_ids") or [])
        if hasattr(command, "feature_id"):
            entry["feature_id"] = str(getattr(command, "feature_id") or "")
        if hasattr(command, "dx") and hasattr(command, "dy"):
            entry["dx"] = float(command.dx)
            entry["dy"] = float(command.dy)
        if hasattr(command, "key"):
            entry["key"] = str(command.key)
        if hasattr(command, "record") and isinstance(command.record, dict):
            entry["record_id"] = str(command.record.get("id") or "")
            entry["record_kind"] = str(command.record.get("kind") or "")
        history = list(doc.edit_history or [])
        history.append(entry)
        if len(history) > self._edit_history_max:
            history = history[-self._edit_history_max :]
        doc.edit_history = history

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
        self._invalidate_snap_candidates()
        self.set_dirty(True)
        self.command_stack_changed.emit()
        self._refresh_vertex_handles()

    def apply_set_vertex(
        self,
        feature_id: str,
        index: int,
        x: float,
        y: float,
        *,
        part_index: int = 0,
        ring_index: int = 0,
    ) -> bool:
        """Set one vertex via VertexEditCommand. Returns True if applied."""
        item = self._items_by_id.get(feature_id)
        if not isinstance(item, (FaciesPolygonItem, LineItem)):
            return False
        old = (
            item.ring_coordinates(part_index, ring_index)
            if isinstance(item, FaciesPolygonItem)
            else item.coordinates()
        )
        new = [list(p) for p in old]
        try:
            api.set_vertex(new, int(index), float(x), float(y))
        except (IndexError, TypeError, ValueError):
            return False
        return self._push_vertex_edit(
            feature_id, old, new, part_index=part_index, ring_index=ring_index
        )

    def apply_insert_vertex(
        self,
        feature_id: str,
        index: int,
        x: float,
        y: float,
        *,
        part_index: int = 0,
        ring_index: int = 0,
    ) -> bool:
        item = self._items_by_id.get(feature_id)
        if not isinstance(item, (FaciesPolygonItem, LineItem)):
            return False
        old = (
            item.ring_coordinates(part_index, ring_index)
            if isinstance(item, FaciesPolygonItem)
            else item.coordinates()
        )
        new = [list(p) for p in old]
        try:
            api.insert_vertex(new, int(index), float(x), float(y))
        except (IndexError, TypeError, ValueError):
            return False
        return self._push_vertex_edit(
            feature_id, old, new, part_index=part_index, ring_index=ring_index
        )

    def apply_delete_vertex(
        self,
        feature_id: str,
        index: int,
        *,
        part_index: int = 0,
        ring_index: int = 0,
    ) -> bool:
        item = self._items_by_id.get(feature_id)
        if not isinstance(item, (FaciesPolygonItem, LineItem)):
            return False
        old = (
            item.ring_coordinates(part_index, ring_index)
            if isinstance(item, FaciesPolygonItem)
            else item.coordinates()
        )
        new = [list(p) for p in old]
        if not api.delete_vertex(new, int(index)):
            return False
        return self._push_vertex_edit(
            feature_id, old, new, part_index=part_index, ring_index=ring_index
        )

    def apply_property_change(self, feature_id: str, key: str, value: object) -> bool:
        """Change name/text via PropertyChangeCommand. Returns True if applied."""
        item = self._items_by_id.get(feature_id)
        if item is None:
            return False
        if key not in {"name", "text"}:
            return False
        old = item.get_property(key)
        new_val = "" if value is None else str(value)
        if old == new_val:
            return False
        cmd = PropertyChangeCommand(
            feature_id=feature_id,
            key=key,
            old_value=old,
            new_value=new_val,
            apply_property=self._apply_property,
        )
        self._command_stack.push(cmd)
        self.set_dirty(True)
        self.command_stack_changed.emit()
        return True

    def create_feature(self, record: dict[str, Any]) -> str | None:
        """Create a feature from a record via CreateFeatureCommand. Returns feature id."""
        rec = dict(record)
        fid = str(rec.get("id") or new_feature_id(str(rec.get("kind") or "feat")))
        rec["id"] = fid
        if fid in self._items_by_id:
            return None
        # Validate constructible before pushing.
        probe = self._item_from_record(rec)
        if probe is None:
            return None
        cmd = CreateFeatureCommand(
            record=rec,
            add_feature=self._add_feature_from_record,
            remove_feature=self._remove_feature_by_id,
        )
        self._command_stack.push(cmd)
        self.set_dirty(True)
        self.command_stack_changed.emit()
        return fid

    @property
    def _draft_points(self) -> list[list[float]]:
        return self._draft_manager.points

    @property
    def _draft_kind(self) -> str | None:
        return self._draft_manager.kind

    def finish_line_draft(self) -> str | None:
        """Finish current line draft if it has at least 2 points. Returns new feature id."""
        return self._draft_manager.finish_line(self.create_feature)

    def finish_facies_draft(self) -> str | None:
        """Finish facies polygon draft (min 3 unique points). Closes the ring."""
        return self._draft_manager.finish_facies(self.create_feature, self.refresh_topology)

    def cancel_line_draft(self) -> None:
        self._draft_manager.cancel()

    def draft_point_count(self) -> int:
        return self._draft_manager.point_count()

    def draft_kind(self) -> str | None:
        return self._draft_manager.kind

    def refresh_topology(self, feature_id: str | None = None) -> None:
        """Validate topology and set topology_status on facies (and optional lines)."""
        ids = [feature_id] if feature_id else list(self._items_by_id.keys())
        for fid in ids:
            item = self._items_by_id.get(fid) if fid else None
            if item is None:
                continue
            status = "ok"
            if isinstance(item, FaciesPolygonItem):
                issues = self._facies_geometry_issues(item)
                if issues:
                    status = "warning"
            elif isinstance(item, LineItem):
                # Open polylines: no self-intersection ring check; keep ok for V1.
                status = "ok"
            item.set_topology_status(status)
        # Full refresh also applies adjacency warnings across facies.
        if feature_id is None:
            self._apply_adjacency_warnings()
        self._publish_topology_issues()

    def _publish_topology_issues(self) -> None:
        """Emit topology_issues_changed only when the issue content changed."""
        issues = self.topology_issues()
        if issues != self._last_published_issues:
            self._last_published_issues = issues
            self.topology_issues_changed.emit(issues)

    def topology_issues(self) -> list[dict[str, object]]:
        """Return structured issues for the bottom workbench and save gate."""
        issues: list[dict[str, object]] = []
        for item in self._items_by_id.values():
            if not isinstance(item, FaciesPolygonItem):
                continue
            issues.extend(self._facies_geometry_issues(item))
        return issues

    def _facies_geometry_issues(
        self,
        item: FaciesPolygonItem,
    ) -> list[dict[str, object]]:
        return facies_geometry_issues(item)

    def validate_for_save(self) -> tuple[bool, list[dict[str, object]]]:
        issues = self.topology_issues()
        return not any(issue.get("severity") == "error" for issue in issues), issues

    def _apply_adjacency_warnings(self) -> None:
        facies = [
            item
            for item in self._items_by_id.values()
            if isinstance(item, FaciesPolygonItem)
        ]
        # Geometry gate in world units, independent of the pixel snap tolerance.
        apply_adjacency_warnings(facies, gap_tol=_ADJACENCY_GAP_TOL)

    def rebuild_topology_forced(self, snap_tol: float | None = None) -> dict[str, Any]:
        """Snap shared nodes across facies, re-validate rings/adjacency, undoable."""
        # The scene snap tolerance is screen pixels; convert it unless the
        # caller passed an explicit world-unit tolerance.
        if snap_tol is None:
            tol = self._snap_tolerance * self._units_per_pixel()
        else:
            tol = float(snap_tol)
        facies = [
            item
            for item in self._items_by_id.values()
            if isinstance(item, FaciesPolygonItem)
        ]
        report, cmd = plan_topology_rebuild(facies, tol, self._apply_coordinates)
        if cmd is not None:
            self._command_stack.push(cmd)
            self.set_dirty(True)
            self.command_stack_changed.emit()
            self._refresh_vertex_handles()
        self.refresh_topology()
        return report

    def merge_selected_facies(self) -> str | None:
        """Merge exactly two selected facies polygons into one. Returns new id."""
        ids = self.selected_feature_ids()
        facies_ids = [
            fid
            for fid in ids
            if isinstance(self._items_by_id.get(fid), FaciesPolygonItem)
        ]
        if len(facies_ids) != 2:
            return None
        a = self._items_by_id[facies_ids[0]]
        b = self._items_by_id[facies_ids[1]]
        assert isinstance(a, FaciesPolygonItem) and isinstance(b, FaciesPolygonItem)
        new_id, cmd = plan_merge_facies(
            a,
            b,
            self._add_feature_from_record,
            self._remove_feature_by_id,
            self._item_from_record,
        )
        if new_id and cmd:
            self._command_stack.push(cmd)
            self.set_dirty(True)
            self.command_stack_changed.emit()
            self.refresh_topology(new_id)
            self._refresh_vertex_handles()
            return new_id
        return None

    def split_selected_facies_by_line(self) -> list[str] | None:
        """Split one selected facies using one selected line. Returns new ids."""
        ids = self.selected_feature_ids()
        facies_ids = [
            fid
            for fid in ids
            if isinstance(self._items_by_id.get(fid), FaciesPolygonItem)
        ]
        line_ids = [
            fid for fid in ids if isinstance(self._items_by_id.get(fid), LineItem)
        ]
        if len(facies_ids) != 1 or len(line_ids) != 1:
            return None
        poly_item = self._items_by_id[facies_ids[0]]
        line_item = self._items_by_id[line_ids[0]]
        assert isinstance(poly_item, FaciesPolygonItem) and isinstance(line_item, LineItem)
        new_ids, cmd = plan_split_facies(
            poly_item,
            line_item,
            self._add_feature_from_record,
            self._remove_feature_by_id,
            self._item_from_record,
        )
        if new_ids and cmd:
            self._command_stack.push(cmd)
            self.set_dirty(True)
            self.command_stack_changed.emit()
            for nid in new_ids:
                self.refresh_topology(nid)
            self._refresh_vertex_handles()
            return new_ids
        return None

    def undo(self) -> bool:
        if not self._command_stack.can_undo():
            return False
        ok = self._command_stack.undo()
        if ok:
            self._invalidate_snap_candidates()
            self.set_dirty(True)
            self.command_stack_changed.emit()
            self._refresh_vertex_handles()
        return ok

    def redo(self) -> bool:
        if not self._command_stack.can_redo():
            return False
        ok = self._command_stack.redo()
        if ok:
            self._invalidate_snap_candidates()
            self.set_dirty(True)
            self.command_stack_changed.emit()
            self._refresh_vertex_handles()
        return ok

    # --- mouse / key interaction --------------------------------------------

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._tool in {"line", "facies"}:
            x, y = self._snap_xy(event.scenePos().x(), event.scenePos().y())
            self._append_draft_point(x, y, kind=self._tool)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._tool == "label":
            x, y = self._snap_xy(event.scenePos().x(), event.scenePos().y())
            self.create_feature({
                "id": new_feature_id("label"),
                "kind": "label",
                "name": "注记",
                "text": "注记",
                "coordinates": [x, y],
            })
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._tool == "vertex":
            pos = event.scenePos()
            handle = self._handle_at(pos)
            if handle is not None:
                self._active_vertex_index = handle.vertex_index
                self._active_vertex_part_index = handle.part_index
                self._active_vertex_ring_index = handle.ring_index
                handle.setSelected(True)
                self._vertex_drag = True
                self._vertex_drag_feature_id = handle.feature_id
                self._vertex_drag_index = handle.vertex_index
                self._vertex_drag_part_index = handle.part_index
                self._vertex_drag_ring_index = handle.ring_index
                self._vertex_drag_origin = QPointF(pos)
                item = self._items_by_id.get(handle.feature_id)
                if isinstance(item, (FaciesPolygonItem, LineItem)):
                    coords = (
                        item.ring_coordinates(handle.part_index, handle.ring_index)
                        if isinstance(item, FaciesPolygonItem)
                        else item.coordinates()
                    )
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
            if hit is not None and isinstance(hit, (FaciesPolygonItem, LineItem)):
                if not hit.isSelected() or len(self.selected_feature_ids()) != 1:
                    self.clearSelection()
                    hit.setSelected(True)
                event.accept()
                return
        if event.button() == Qt.MouseButton.LeftButton and self._tool == "select":
            pos = event.scenePos()
            # Prefer geometry hit-test (C++ when available) over pure Qt item stack.
            fid = self.hit_test_at(pos.x(), pos.y(), tolerance=self._snap_tolerance)
            if fid:
                item = self._items_by_id.get(fid)
                if item is not None and isinstance(item, QGraphicsItem):
                    multi = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                    if not multi:
                        self.clearSelection()
                    item.setSelected(True)
                    event.accept()
                    return
            elif not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.clearSelection()
        if event.button() == Qt.MouseButton.LeftButton and self._tool == "move":
            pos = event.scenePos()
            hit = self._feature_item_at(pos)
            if hit is None:
                fid = self.hit_test_at(pos.x(), pos.y(), tolerance=self._snap_tolerance)
                hit = self._items_by_id.get(fid) if fid else None
            if hit is not None and isinstance(hit, QGraphicsItem) and not hit.isSelected():
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
        if self._tool in {"line", "facies"} and self._draft_points:
            x, y = self._snap_xy(event.scenePos().x(), event.scenePos().y())
            self._update_draft_preview(x, y, close_preview=(self._tool == "facies"))
            event.accept()
            return
        if self._vertex_drag and self._tool == "vertex":
            pos = event.scenePos()
            x, y = self._snap_xy(pos.x(), pos.y())
            fid = self._vertex_drag_feature_id
            idx = self._vertex_drag_index
            part_index = self._vertex_drag_part_index
            ring_index = self._vertex_drag_ring_index
            item = self._items_by_id.get(fid) if fid else None
            if isinstance(item, (FaciesPolygonItem, LineItem)) and idx is not None:
                coords = (
                    item.ring_coordinates(part_index, ring_index)
                    if isinstance(item, FaciesPolygonItem)
                    else item.coordinates()
                )
                try:
                    api.set_vertex(coords, idx, x, y)
                except (IndexError, TypeError, ValueError):
                    pass
                else:
                    if isinstance(item, FaciesPolygonItem):
                        item.set_ring_coordinates(part_index, ring_index, coords)
                    else:
                        item.set_coordinates(coords)
                    self._refresh_hit_entry(item)
                    self._invalidate_snap_candidates()
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
            part_index = self._vertex_drag_part_index
            ring_index = self._vertex_drag_ring_index
            start = self._vertex_drag_start_xy
            pos = event.scenePos()
            end_x, end_y = self._snap_xy(pos.x(), pos.y())
            self._vertex_drag = False
            self._vertex_drag_feature_id = None
            self._vertex_drag_index = None
            self._vertex_drag_start_xy = None
            item = self._items_by_id.get(fid) if fid else None
            if isinstance(item, (FaciesPolygonItem, LineItem)) and idx is not None and start is not None:
                if end_x != start[0] or end_y != start[1]:
                    # Restore original, then commit via command for undo.
                    restored = (
                        item.ring_coordinates(part_index, ring_index)
                        if isinstance(item, FaciesPolygonItem)
                        else item.coordinates()
                    )
                    try:
                        api.set_vertex(restored, idx, start[0], start[1])
                    except (IndexError, TypeError, ValueError):
                        pass
                    else:
                        if isinstance(item, FaciesPolygonItem):
                            item.set_ring_coordinates(part_index, ring_index, restored)
                        else:
                            item.set_coordinates(restored)
                        self._refresh_hit_entry(item)
                    self.apply_set_vertex(
                        fid,
                        idx,
                        end_x,
                        end_y,
                        part_index=part_index,
                        ring_index=ring_index,
                    )
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
        if event.button() == Qt.MouseButton.LeftButton and self._tool == "line":
            # mousePress already added the double-click point; finish the draft.
            self.finish_line_draft()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._tool == "facies":
            self.finish_facies_draft()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._tool == "vertex":
            fid = self._single_editable_feature_id()
            if fid is not None:
                item = self._items_by_id.get(fid)
                if isinstance(item, (FaciesPolygonItem, LineItem)):
                    pos = event.scenePos()
                    # Prefer edge insert when not on an existing handle.
                    if self._handle_at(pos) is None:
                        x, y = self._snap_xy(pos.x(), pos.y())
                        edge = api.closest_edge(item.coordinates(), x, y)
                        if edge is not None:
                            i, qx, qy, dist2 = edge
                            edge_tol2 = (_EDGE_HIT_TOL * self._units_per_pixel()) ** 2
                            if dist2 <= edge_tol2:
                                self.apply_insert_vertex(fid, i + 1, qx, qy)
                                event.accept()
                                return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._tool in {"line", "facies"}:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self._tool == "line":
                    self.finish_line_draft()
                else:
                    self.finish_facies_draft()
                event.accept()
                return
            if event.key() == Qt.Key.Key_Escape:
                self._cancel_draft()
                event.accept()
                return
        if self._tool == "vertex" and event.key() in (
            Qt.Key.Key_Delete,
            Qt.Key.Key_Backspace,
        ):
            fid = self._single_editable_feature_id()
            idx = self._active_vertex_index
            if fid is not None and idx is not None:
                if self.apply_delete_vertex(
                    fid,
                    idx,
                    part_index=self._active_vertex_part_index,
                    ring_index=self._active_vertex_ring_index,
                ):
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
        *,
        part_index: int = 0,
        ring_index: int = 0,
    ) -> bool:
        if old_coords == new_coords:
            return False
        item = self._items_by_id.get(feature_id)
        if isinstance(item, FaciesPolygonItem):
            cmd = RingEditCommand(
                feature_id=feature_id,
                part_index=part_index,
                ring_index=ring_index,
                old_coordinates=old_coords,
                new_coordinates=new_coords,
                apply_ring=self._apply_ring_coordinates,
            )
        else:
            cmd = VertexEditCommand(
                feature_id=feature_id,
                old_coordinates=old_coords,
                new_coordinates=new_coords,
                apply_coordinates=self._apply_coordinates,
            )
        self._command_stack.push(cmd)
        self._invalidate_snap_candidates()
        self.set_dirty(True)
        self.command_stack_changed.emit()
        self._refresh_vertex_handles()
        self.refresh_topology(feature_id)
        return True

    def _apply_coordinates(self, feature_id: str, coordinates: list[list[float]]) -> None:
        item = self._items_by_id.get(feature_id)
        if isinstance(item, (FaciesPolygonItem, LineItem)):
            item.set_coordinates(coordinates)
            self._refresh_hit_entry(item)
            self._invalidate_snap_candidates()
            self.refresh_topology(feature_id)

    def _apply_ring_coordinates(
        self,
        feature_id: str,
        part_index: int,
        ring_index: int,
        coordinates: list[list[float]],
    ) -> None:
        item = self._items_by_id.get(feature_id)
        if isinstance(item, FaciesPolygonItem):
            item.set_ring_coordinates(part_index, ring_index, coordinates)
            self._refresh_hit_entry(item)
            self._invalidate_snap_candidates()
            self.refresh_topology(feature_id)

    def _apply_move_one(self, feature_id: str, dx: float, dy: float) -> None:
        item = self._items_by_id.get(feature_id)
        if item is None:
            return
        translate = getattr(item, "translate_by", None)
        if callable(translate):
            translate(dx, dy)
            self._refresh_hit_entry(item)

    def _apply_property(self, feature_id: str, key: str, value: object) -> None:
        item = self._items_by_id.get(feature_id)
        if item is None:
            return
        item.set_property(key, value)

    def _add_feature_from_record(self, record: dict[str, Any]) -> None:
        item = self._item_from_record(record)
        if item is None:
            return
        self._register_item(item)

    def _remove_feature_by_id(self, feature_id: str) -> None:
        item = self._items_by_id.pop(feature_id, None)
        self._hit_query_index.remove(feature_id)
        if item is not None and isinstance(item, QGraphicsItem):
            self.removeItem(item)
        self._invalidate_snap_candidates()

    def _register_item(self, item: FeatureItemMixin) -> None:
        if not isinstance(item, QGraphicsItem):
            return
        self.addItem(item)
        self._items_by_id[item.feature_id] = item
        if not self._loading_features:
            self._refresh_hit_entry(item)
        self._invalidate_snap_candidates()
        visible = self._layer_visible.get(item.kind, True)
        item.setVisible(visible)

    @staticmethod
    def _hit_record_for_item(item: object) -> dict[str, Any]:
        if not isinstance(item, FeatureItemMixin):
            return {}
        return item.to_record()

    def _units_per_pixel(self) -> float:
        """Scene units per screen pixel at the current view scale.

        Returns 1.0 when the scene has no attached view (offscreen tests and
        headless usage), which keeps pixel tolerances equal to scene units.
        """
        for view in self.views():
            scale = view.transform().m11()
            if scale > 0.0:
                return 1.0 / scale
        return 1.0

    def _refresh_hit_entry(self, item: FeatureItemMixin) -> None:
        self._hit_query_index.upsert(item, record_for_item=self._hit_record_for_item)

    def _single_editable_feature_id(self) -> str | None:
        ids = self.selected_feature_ids()
        if len(ids) != 1:
            return None
        item = self._items_by_id.get(ids[0])
        if isinstance(item, (FaciesPolygonItem, LineItem)):
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
        if not isinstance(item, (FaciesPolygonItem, LineItem)):
            return
        addressed_rings = (
            list(item.iter_ring_addresses())
            if isinstance(item, FaciesPolygonItem)
            else [(0, 0, item.coordinates())]
        )
        for part_index, ring_index, coords in addressed_rings:
            if len(coords) < 2:
                continue
            closed = coords[0] == coords[-1]
            count = len(coords) - 1 if closed else len(coords)
            for i in range(count):
                handle = VertexHandleItem(
                    fid,
                    i,
                    coords[i][0],
                    coords[i][1],
                    part_index=part_index,
                    ring_index=ring_index,
                )
                self.addItem(handle)
                self._vertex_handles.append(handle)

    def _sync_handle_positions(self, item: FaciesPolygonItem | LineItem) -> None:
        for handle in self._vertex_handles:
            if handle.feature_id != item.feature_id:
                continue
            idx = handle.vertex_index
            coords = (
                item.ring_coordinates(handle.part_index, handle.ring_index)
                if isinstance(item, FaciesPolygonItem)
                else item.coordinates()
            )
            if 0 <= idx < len(coords):
                handle.setPos(coords[idx][0], coords[idx][1])

    def _handle_at(self, pos: QPointF) -> VertexHandleItem | None:
        """Return the nearest vertex handle within a screen-pixel radius.

        Handles ignore view transforms (constant screen size), and
        QGraphicsScene.items() shape picking is unreliable for such items, so
        the scene scans its own handle list with a pixel-converted radius.
        """
        radius = _HANDLE_PICK_TOL * self._units_per_pixel()
        radius2 = radius * radius
        best: VertexHandleItem | None = None
        best_dist2 = radius2
        for handle in self._vertex_handles:
            dx = handle.pos().x() - pos.x()
            dy = handle.pos().y() - pos.y()
            dist2 = dx * dx + dy * dy
            if dist2 <= best_dist2:
                best = handle
                best_dist2 = dist2
        return best

    def _feature_item_at(self, pos: QPointF) -> FeatureItemMixin | None:
        """Return topmost feature item at *pos*, ignoring hidden layers."""
        for item in self.items(pos):
            if isinstance(item, FeatureItemMixin) and self.layer_is_visible(
                getattr(item, "kind", "")
            ):
                return item
        # Slight tolerance for thin edges / small wells (screen pixels).
        radius = _FEATURE_PICK_TOL * self._units_per_pixel()
        path = QPainterPath()
        path.addEllipse(pos, radius, radius)
        for item in self.items(path):
            if isinstance(item, FeatureItemMixin) and self.layer_is_visible(
                getattr(item, "kind", "")
            ):
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
            part_index = self._vertex_drag_part_index
            ring_index = self._vertex_drag_ring_index
            start = self._vertex_drag_start_xy
            # Mirror mouseReleaseEvent's part/ring addressing: restoring the
            # outer ring only moved an arbitrary vertex when the drag was on a
            # hole / non-first part (silent geometry corruption on cancel).
            if isinstance(item, (FaciesPolygonItem, LineItem)) and idx is not None:
                restored = (
                    item.ring_coordinates(part_index, ring_index)
                    if isinstance(item, FaciesPolygonItem)
                    else item.coordinates()
                )
                try:
                    api.set_vertex(restored, idx, start[0], start[1])
                except (IndexError, TypeError, ValueError):
                    pass
                else:
                    if isinstance(item, FaciesPolygonItem):
                        item.set_ring_coordinates(part_index, ring_index, restored)
                    else:
                        item.set_coordinates(restored)
                    self._refresh_hit_entry(item)
                    self._invalidate_snap_candidates()
        self._vertex_drag = False
        self._vertex_drag_feature_id = None
        self._vertex_drag_index = None
        self._vertex_drag_start_xy = None

    # --- line draft ---------------------------------------------------------

    def _append_draft_point(self, x: float, y: float, kind: str = "line") -> None:
        self._draft_manager.append_point(x, y, kind=kind)

    def _update_draft_preview(
        self,
        cursor_x: float,
        cursor_y: float,
        close_preview: bool = False,
    ) -> None:
        self._draft_manager.update_preview(cursor_x, cursor_y, close_preview=close_preview)

    def _cancel_draft(self) -> None:
        self._draft_manager.cancel()

    def _cancel_line_draft(self) -> None:
        self._draft_manager.cancel()

    # --- snap ---------------------------------------------------------------

    def _snap_xy(self, x: float, y: float) -> tuple[float, float]:
        manager = self._snap_manager
        if not manager.enabled:
            return float(x), float(y)
        # Candidate preparation happens once per scene generation: the manager
        # rebuilds its cache (bumping build_count) only after geometry,
        # reference-snap, or visibility changes; the grid index follows it.
        candidates = manager.get_candidates(self._items_by_id.values(), self.layer_is_visible)
        build = manager.build_count()
        if self._snap_index is None or self._snap_index_build != build:
            self._snap_index = api.SnapCandidateIndex(candidates)
            self._snap_index_build = build
        draft = self._draft_manager.points
        extras = [tuple(p) for p in draft] if draft else []
        tolerance_units = manager.tolerance * self._units_per_pixel()
        return self._snap_index.snap(float(x), float(y), tolerance_units, extras)

    def _invalidate_snap_candidates(self) -> None:
        self._snap_manager.invalidate_candidates()
        self._snap_index = None
        self._snap_index_build = -1

    def snap_candidate_build_count(self) -> int:
        return self._snap_manager.build_count()

    def _snap_candidates(self) -> list[tuple[float, float]]:
        return self._snap_manager.get_candidates(
            self._items_by_id.values(), self.layer_is_visible, self._draft_manager.points
        )

    # --- navigation display LOD ----------------------------------------------

    def set_navigation_lod(self, active: bool) -> None:
        """Toggle low-detail navigation rendering (display-only).

        While active, path items paint simplified bounding-box geometry; stored
        coordinates and command objects are never modified.
        """
        active_b = bool(active)
        if self._navigation_lod == active_b:
            return
        self._navigation_lod = active_b
        self.update()

    def navigation_lod(self) -> bool:
        return self._navigation_lod

    def drawItems(self, painter, items, options, widget=None) -> None:
        if not self._navigation_lod:
            super().drawItems(painter, items, options, widget)
            return
        inverted, ok = painter.combinedTransform().inverted()
        exposed = (
            inverted.mapRect(QRectF(painter.viewport()))
            if ok
            else self.sceneRect()
        )
        for item, option in zip(items, options):
            if not isinstance(item, (FaciesPolygonItem, LineItem)):
                painter.save()
                painter.setWorldTransform(item.sceneTransform(), True)
                item.paint(painter, option, widget)
                painter.restore()
                continue
            # Cull against the item's existing bounding rectangle before
            # painting its simplified (bounding-box) stand-in geometry.
            if not item.sceneBoundingRect().intersects(exposed):
                continue
            painter.save()
            painter.setWorldTransform(item.sceneTransform(), True)
            painter.setPen(item.pen())
            painter.setBrush(item.brush())
            painter.drawRect(item.boundingRect())
            painter.restore()

    # --- item factories -----------------------------------------------------

    def _item_from_record(self, record: dict[str, Any]) -> FeatureItemMixin | None:
        return item_from_record(record)

    def _fit_scene_rect(self) -> None:
        if not self._items_by_id:
            self.setSceneRect(_DEFAULT_SCENE_RECT)
            return
        bounds = self.itemsBoundingRect()
        if bounds.isNull() or not bounds.isValid():
            self.setSceneRect(_DEFAULT_SCENE_RECT)
            return
        self.setSceneRect(bounds.adjusted(-_SCENE_PAD, -_SCENE_PAD, _SCENE_PAD, _SCENE_PAD))
