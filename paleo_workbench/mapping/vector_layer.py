"""Authoritative GeoJSON-compatible vector layers and QGIS-style edit buffers.

Vector data stays host-owned. A QGIS layer may mirror it for rendering, and Qt graphics
items may mirror it for temporary overlays, but neither becomes edit authority.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping

__all__ = [
    "AddFeatureCommand",
    "AddRingCommand",
    "ChangeAttributeCommand",
    "DeleteFeatureCommand",
    "DeleteRingCommand",
    "DeleteVertexCommand",
    "EditCommand",
    "InsertVertexCommand",
    "MergeFeaturesCommand",
    "MoveFeatureCommand",
    "SetGeometryCommand",
    "SetVertexCommand",
    "SplitFeatureCommand",
    "VectorEditSession",
    "VectorFeature",
    "VectorLayer",
]


def _point(value: object) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError("coordinate must contain x and y")
    x, y = float(value[0]), float(value[1])
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("coordinate must be finite")
    return x, y


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _freeze(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _validate_geometry(geometry: Mapping[str, Any]) -> dict[str, object]:
    kind = str(geometry.get("type") or "")
    if kind not in {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}:
        raise ValueError(f"unsupported geometry type {kind!r}")
    if "coordinates" not in geometry:
        raise ValueError("geometry coordinates are required")
    # Validate every leaf coordinate pair while retaining the standard GeoJSON nesting.
    def validate(value: object) -> object:
        if isinstance(value, (list, tuple)) and len(value) >= 2 and not isinstance(value[0], (list, tuple)):
            return list(_point(value))
        if not isinstance(value, (list, tuple)):
            raise ValueError("geometry coordinates must be nested arrays")
        return [validate(item) for item in value]

    coordinates = validate(geometry["coordinates"])
    return {"type": kind, "coordinates": coordinates}


def _translate(value: object, dx: float, dy: float) -> object:
    if isinstance(value, (list, tuple)) and len(value) >= 2 and not isinstance(value[0], (list, tuple)):
        x, y = _point(value)
        return [x + dx, y + dy]
    if not isinstance(value, (list, tuple)):
        raise ValueError("invalid geometry coordinates")
    return [_translate(item, dx, dy) for item in value]


def _path_parent(value: object, path: tuple[int, ...]) -> tuple[list, int]:
    if not path:
        raise ValueError("vertex path is required")
    current = value
    for index in path[:-1]:
        if not isinstance(current, list) or index < 0 or index >= len(current):
            raise IndexError("vertex path is outside the geometry")
        current = current[index]
    if not isinstance(current, list) or path[-1] < 0 or path[-1] >= len(current):
        raise IndexError("vertex path is outside the geometry")
    return current, path[-1]


@dataclass(frozen=True, slots=True)
class VectorFeature:
    """Immutable semantic feature with GeoJSON geometry and host attributes."""

    feature_id: str
    geometry: Mapping[str, Any]
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.feature_id):
            raise ValueError("feature_id is required")
        object.__setattr__(self, "feature_id", str(self.feature_id))
        object.__setattr__(self, "geometry", _freeze(_validate_geometry(self.geometry)))
        object.__setattr__(self, "attributes", _freeze(dict(self.attributes)))

    def as_record(self) -> dict[str, object]:
        return {
            "id": self.feature_id,
            "geometry": _thaw(self.geometry),
            "properties": _thaw(self.attributes),
        }


@dataclass(frozen=True, slots=True)
class EditCommand:
    """A deterministic before/after working-copy patch, independent of UI lifetime."""

    command_type: str
    before: Mapping[str, VectorFeature | None]
    after: Mapping[str, VectorFeature | None]

    @property
    def feature_ids(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.before) | set(self.after)))

    def apply(self, target: dict[str, VectorFeature]) -> None:
        for feature_id, feature in self.after.items():
            if feature is None:
                target.pop(feature_id, None)
            else:
                target[feature_id] = feature

    def revert(self, target: dict[str, VectorFeature]) -> None:
        for feature_id, feature in self.before.items():
            if feature is None:
                target.pop(feature_id, None)
            else:
                target[feature_id] = feature

    def audit_record(self) -> dict[str, object]:
        return {"command_type": self.command_type, "feature_ids": list(self.feature_ids)}


class AddFeatureCommand(EditCommand):
    def __init__(self, feature: VectorFeature):
        super().__init__("add_feature", {feature.feature_id: None}, {feature.feature_id: feature})


class DeleteFeatureCommand(EditCommand):
    def __init__(self, feature: VectorFeature):
        super().__init__("delete_feature", {feature.feature_id: feature}, {feature.feature_id: None})


class MoveFeatureCommand(EditCommand):
    def __init__(self, before: VectorFeature, after: VectorFeature):
        super().__init__("move_feature", {before.feature_id: before}, {after.feature_id: after})


class SetGeometryCommand(EditCommand):
    def __init__(self, before: VectorFeature, after: VectorFeature):
        super().__init__("set_geometry", {before.feature_id: before}, {after.feature_id: after})


class SetVertexCommand(SetGeometryCommand):
    def __init__(self, before: VectorFeature, after: VectorFeature):
        EditCommand.__init__(self, "set_vertex", {before.feature_id: before}, {after.feature_id: after})


class InsertVertexCommand(SetGeometryCommand):
    def __init__(self, before: VectorFeature, after: VectorFeature):
        EditCommand.__init__(self, "insert_vertex", {before.feature_id: before}, {after.feature_id: after})


class DeleteVertexCommand(SetGeometryCommand):
    def __init__(self, before: VectorFeature, after: VectorFeature):
        EditCommand.__init__(self, "delete_vertex", {before.feature_id: before}, {after.feature_id: after})


class ChangeAttributeCommand(EditCommand):
    def __init__(self, before: VectorFeature, after: VectorFeature):
        super().__init__("change_attribute", {before.feature_id: before}, {after.feature_id: after})


class SplitFeatureCommand(EditCommand):
    def __init__(self, before: Mapping[str, VectorFeature | None], after: Mapping[str, VectorFeature | None]):
        super().__init__("split_feature", before, after)


class MergeFeaturesCommand(EditCommand):
    def __init__(self, before: Mapping[str, VectorFeature | None], after: Mapping[str, VectorFeature | None]):
        super().__init__("merge_features", before, after)


class AddRingCommand(SetGeometryCommand):
    def __init__(self, before: VectorFeature, after: VectorFeature):
        EditCommand.__init__(self, "add_ring", {before.feature_id: before}, {after.feature_id: after})


class DeleteRingCommand(SetGeometryCommand):
    def __init__(self, before: VectorFeature, after: VectorFeature):
        EditCommand.__init__(self, "delete_ring", {before.feature_id: before}, {after.feature_id: after})


class VectorLayer:
    """Host-owned vector resource/version with selection and one edit session."""

    def __init__(
        self,
        *,
        id: str,
        name: str,
        crs: str = "",
        source_ref: str = "",
        schema: Mapping[str, object] | None = None,
        features: Iterable[VectorFeature] = (),
        style: Mapping[str, object] | None = None,
        labels: Mapping[str, object] | None = None,
    ) -> None:
        if not id:
            raise ValueError("vector layer id is required")
        self.id = str(id)
        self.name = str(name)
        self.crs = str(crs)
        self.source_ref = str(source_ref)
        self.schema = dict(schema or {})
        self.style = dict(style or {})
        self.labels = dict(labels or {})
        self.data_revision = 1
        self.style_revision = 1
        self._features: dict[str, VectorFeature] = {}
        for feature in features:
            if feature.feature_id in self._features:
                raise ValueError(f"duplicate vector feature id {feature.feature_id!r}")
            self._features[feature.feature_id] = feature
        self._selection: set[str] = set()
        self.edit_session: VectorEditSession | None = None

    def feature_ids(self) -> tuple[str, ...]:
        return tuple(self._features)

    def features(self) -> tuple[VectorFeature, ...]:
        return tuple(self._features.values())

    def feature(self, feature_id: str) -> VectorFeature:
        try:
            return self._features[str(feature_id)]
        except KeyError as exc:
            raise KeyError(f"unknown feature {feature_id!r}") from exc

    def _selectable_feature_ids(self) -> set[str]:
        session = self.edit_session
        return {
            feature.feature_id
            for feature in (session.features() if session is not None else self.features())
        }

    @property
    def selection(self) -> set[str]:
        return set(self._selection)

    def set_selection(self, feature_ids: Iterable[str]) -> set[str]:
        selectable = self._selectable_feature_ids()
        self._selection = {str(feature_id) for feature_id in feature_ids if str(feature_id) in selectable}
        return self.selection

    def toggle_selection(self, feature_id: str) -> set[str]:
        feature_id = str(feature_id)
        if feature_id not in self._selectable_feature_ids():
            return self.selection
        if feature_id in self._selection:
            self._selection.remove(feature_id)
        else:
            self._selection.add(feature_id)
        return self.selection

    def select_all(self) -> set[str]:
        return self.set_selection(self._selectable_feature_ids())

    def invert_selection(self) -> set[str]:
        return self.set_selection(
            feature_id for feature_id in self._selectable_feature_ids() if feature_id not in self._selection
        )

    def start_editing(self) -> "VectorEditSession":
        if self.edit_session is None:
            self.edit_session = VectorEditSession(self)
        return self.edit_session

    def _commit(self, features: Mapping[str, VectorFeature]) -> None:
        self._features = dict(features)
        self._selection.intersection_update(self._features)
        self.data_revision += 1
        self.edit_session = None

    def _discard_session(self, session: "VectorEditSession") -> None:
        if self.edit_session is session:
            self.edit_session = None
            self._selection.intersection_update(self._features)


class VectorEditSession:
    """QGIS-inspired edit buffer: working state, undo/redo, commit, rollback."""

    # Journal retention: enough revision entries for snapshot consumers that
    # settle on a debounce; older watermarks fall back to a full rebuild.
    JOURNAL_LIMIT = 1024

    def __init__(self, layer: VectorLayer) -> None:
        self.layer = layer
        self._working: dict[str, VectorFeature] = dict(layer._features)
        self.undo_stack: list[EditCommand] = []
        self.redo_stack: list[EditCommand] = []
        self._open_command: list[EditCommand] | None = None
        self.revision = 0
        # (revision, touched feature ids) per mutation, in application order.
        # Contiguous suffix of all revisions that ever bumped; rolled back or
        # trimmed-away history yields None from changes_since (full rebuild).
        self._journal: list[tuple[int, tuple[str, ...]]] = []

    def _bump_revision(self, touched: Iterable[str] = ()) -> None:
        self.revision += 1
        self._journal.append((self.revision, tuple(touched)))
        if len(self._journal) > self.JOURNAL_LIMIT:
            del self._journal[: len(self._journal) - self.JOURNAL_LIMIT]

    def changes_since(self, revision: int) -> tuple[tuple[str, ...], ...] | None:
        """Journal entries with revision > ``revision`` (oldest first).

        ``None`` when the span is unrecoverable (revision never seen, journal
        trimmed, or the session rolled back wholesale). Empty tuple means the
        working copy provably did not move past ``revision``.
        """
        if revision > self.revision:
            return None
        if revision == self.revision:
            return ()
        if not self._journal or self._journal[0][0] > revision + 1:
            return None
        return tuple(ids for entry_revision, ids in self._journal if entry_revision > revision)

    @property
    def is_dirty(self) -> bool:
        return bool(self.undo_stack)

    def feature(self, feature_id: str) -> VectorFeature:
        try:
            return self._working[str(feature_id)]
        except KeyError as exc:
            raise KeyError(f"unknown working feature {feature_id!r}") from exc

    def features(self) -> tuple[VectorFeature, ...]:
        return tuple(self._working.values())

    def begin_edit_command(self) -> None:
        if self._open_command is not None:
            raise RuntimeError("an edit command is already open")
        self._open_command = []

    def end_edit_command(self) -> None:
        if self._open_command is None:
            raise RuntimeError("no edit command is open")
        commands = self._open_command
        self._open_command = None
        if not commands:
            return
        before: dict[str, VectorFeature | None] = {}
        after: dict[str, VectorFeature | None] = {}
        for command in commands:
            for feature_id, value in command.before.items():
                before.setdefault(feature_id, value)
            after.update(command.after)
        self._record(EditCommand("compound", before, after), already_applied=True)

    def destroy_edit_command(self) -> None:
        if self._open_command is None:
            raise RuntimeError("no edit command is open")
        touched: set[str] = set()
        for command in reversed(self._open_command):
            command.revert(self._working)
            touched.update(command.feature_ids)
        self._open_command = None
        self._bump_revision(touched)

    def _record(self, command: EditCommand, *, already_applied: bool = False) -> None:
        if not already_applied:
            command.apply(self._working)
        if self._open_command is not None:
            self._open_command.append(command)
            return
        self.undo_stack.append(command)
        self.redo_stack.clear()
        self._bump_revision(command.feature_ids)

    def add_feature(self, feature: VectorFeature) -> None:
        if feature.feature_id in self._working:
            raise ValueError(f"feature {feature.feature_id!r} already exists")
        self._record(AddFeatureCommand(feature))

    def delete_feature(self, feature_id: str) -> None:
        self._record(DeleteFeatureCommand(self.feature(feature_id)))

    def move_feature(self, feature_id: str, dx: float, dy: float) -> None:
        before = self.feature(feature_id)
        moved = _translate(_thaw(before.geometry["coordinates"]), float(dx), float(dy))
        after = VectorFeature(before.feature_id, {"type": before.geometry["type"], "coordinates": moved}, before.attributes)
        self._record(MoveFeatureCommand(before, after))

    def set_geometry(self, feature_id: str, geometry: Mapping[str, Any]) -> None:
        before = self.feature(feature_id)
        after = VectorFeature(before.feature_id, geometry, before.attributes)
        self._record(SetGeometryCommand(before, after))

    def set_vertex(self, feature_id: str, path: tuple[int, ...], coordinate: object) -> None:
        before = self.feature(feature_id)
        geometry = _thaw(before.geometry)
        if not path and geometry["type"] == "Point":
            geometry["coordinates"] = list(_point(coordinate))
            after = VectorFeature(before.feature_id, geometry, before.attributes)
            self._record(SetVertexCommand(before, after))
            return
        parent, index = _path_parent(geometry["coordinates"], tuple(path))
        parent[index] = list(_point(coordinate))
        after = VectorFeature(before.feature_id, geometry, before.attributes)
        self._record(SetVertexCommand(before, after))

    def insert_vertex(self, feature_id: str, path: tuple[int, ...], coordinate: object) -> None:
        before = self.feature(feature_id)
        geometry = _thaw(before.geometry)
        parent, index = _path_parent(geometry["coordinates"], tuple(path))
        parent.insert(index, list(_point(coordinate)))
        after = VectorFeature(before.feature_id, geometry, before.attributes)
        self._record(InsertVertexCommand(before, after))

    def delete_vertex(self, feature_id: str, path: tuple[int, ...]) -> None:
        before = self.feature(feature_id)
        geometry = _thaw(before.geometry)
        parent, index = _path_parent(geometry["coordinates"], tuple(path))
        del parent[index]
        after = VectorFeature(before.feature_id, geometry, before.attributes)
        self._record(DeleteVertexCommand(before, after))

    def change_attribute(self, feature_id: str, key: str, value: object) -> None:
        before = self.feature(feature_id)
        attributes = _thaw(before.attributes)
        attributes[str(key)] = deepcopy(value)
        after = VectorFeature(before.feature_id, before.geometry, attributes)
        self._record(ChangeAttributeCommand(before, after))

    def add_ring(self, feature_id: str, ring: Iterable[object]) -> None:
        before = self.feature(feature_id)
        if before.geometry["type"] != "Polygon":
            raise ValueError("rings can only be added to Polygon features")
        points = [list(_point(point)) for point in ring]
        if len(points) < 3:
            raise ValueError("a ring needs at least three vertices")
        if points[0] != points[-1]:
            points.append(list(points[0]))
        geometry = _thaw(before.geometry)
        geometry["coordinates"].append(points)
        after = VectorFeature(before.feature_id, geometry, before.attributes)
        self._record(AddRingCommand(before, after))

    def delete_ring(self, feature_id: str, ring_index: int) -> None:
        before = self.feature(feature_id)
        if before.geometry["type"] != "Polygon":
            raise ValueError("rings can only be deleted from Polygon features")
        geometry = _thaw(before.geometry)
        rings = geometry["coordinates"]
        if ring_index <= 0 or ring_index >= len(rings):
            raise ValueError("only interior Polygon rings may be deleted")
        del rings[ring_index]
        after = VectorFeature(before.feature_id, geometry, before.attributes)
        self._record(DeleteRingCommand(before, after))

    def split_feature(self, feature_id: str, replacements: Iterable[VectorFeature]) -> None:
        before_feature = self.feature(feature_id)
        next_features = tuple(replacements)
        if len(next_features) < 2:
            raise ValueError("splitting requires at least two replacement features")
        if len({feature.feature_id for feature in next_features}) != len(next_features):
            raise ValueError("split replacement feature ids must be unique")
        if any(feature.feature_id in self._working and feature.feature_id != feature_id for feature in next_features):
            raise ValueError("split replacement feature id already exists")
        before: dict[str, VectorFeature | None] = {feature_id: before_feature}
        after: dict[str, VectorFeature | None] = {feature_id: None}
        for feature in next_features:
            before.setdefault(feature.feature_id, None)
            after[feature.feature_id] = feature
        self._record(SplitFeatureCommand(before, after))

    def merge_features(self, feature_ids: Iterable[str], merged: VectorFeature) -> None:
        ids = tuple(dict.fromkeys(str(feature_id) for feature_id in feature_ids))
        if len(ids) < 2:
            raise ValueError("merging requires at least two features")
        originals = {feature_id: self.feature(feature_id) for feature_id in ids}
        if merged.feature_id in self._working and merged.feature_id not in originals:
            raise ValueError("merged feature id already exists")
        before: dict[str, VectorFeature | None] = dict(originals)
        after: dict[str, VectorFeature | None] = {feature_id: None for feature_id in ids}
        before.setdefault(merged.feature_id, None)
        after[merged.feature_id] = merged
        self._record(MergeFeaturesCommand(before, after))

    def undo(self) -> bool:
        if not self.undo_stack or self._open_command is not None:
            return False
        command = self.undo_stack.pop()
        command.revert(self._working)
        self.redo_stack.append(command)
        self._bump_revision(command.feature_ids)
        # 撤销可能移除要素：选集不得残留已不存在的 id（否则宿主的
        # O(selection) 计数与几何命令会命中缺失要素）。
        self.layer._selection.intersection_update(self._working)
        return True

    def redo(self) -> bool:
        if not self.redo_stack or self._open_command is not None:
            return False
        command = self.redo_stack.pop()
        command.apply(self._working)
        self.undo_stack.append(command)
        self._bump_revision(command.feature_ids)
        self.layer._selection.intersection_update(self._working)
        return True

    def commit_changes(self) -> None:
        if self._open_command is not None:
            raise RuntimeError("cannot commit while an edit command is open")
        self.layer._commit(self._working)

    def rollback_changes(self) -> None:
        self._open_command = None
        self._working = dict(self.layer._features)
        self.undo_stack.clear()
        self.redo_stack.clear()
        # 工作副本整体替换：任何旧修订的增量跨度都不可恢复。bump 之后再
        # 清空日志——若留下这条空条目，changes_since(旧修订) 会误判为
        # 「零变更」而保留过期 records；空日志使其返回 None → 全量重建。
        self._bump_revision()
        self._journal = []
        self.layer._discard_session(self)

    def audit_history(self) -> list[dict[str, object]]:
        return [command.audit_record() for command in self.undo_stack]
