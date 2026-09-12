"""Authoritative GeoJSON-compatible vector layers and QGIS-style edit buffers.

Vector data stays host-owned. A QGIS layer may mirror it for rendering, and Qt graphics
items may mirror it for temporary overlays, but neither becomes edit authority.
"""

from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass, field
import math
import uuid
from typing import Any, Iterable, Iterator, Mapping

from paleo_workbench.mapping.edit_delta import (
    DELTA_JOURNAL_LIMIT,
    EditDelta,
    delta_from_command,
)

__all__ = [
    "AddFeatureCommand",
    "AddPartCommand",
    "AddRingCommand",
    "ChangeAttributeCommand",
    "DeleteFeatureCommand",
    "DeletePartCommand",
    "DeleteRingCommand",
    "DeleteVertexCommand",
    "DuplicateFeatureCommand",
    "EditCommand",
    "InsertVertexCommand",
    "MergeFeaturesCommand",
    "MoveFeatureCommand",
    "MovePartCommand",
    "SetGeometryCommand",
    "SetVertexCommand",
    "SplitFeatureCommand",
    "VectorEditSession",
    "VectorFeature",
    "VectorLayer",
    "DELTA_JOURNAL_LIMIT",
    "EditDelta",
]


def _point(value: object) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError("coordinate must contain x and y")
    x, y = float(value[0]), float(value[1])
    if not math.isfinite(x) or not math.isfinite(y):
        raise ValueError("coordinate must be finite")
    return x, y


# 原生提交审计流上限（M1 §2；与 EditDelta journal 同量级）。
_COMMIT_JOURNAL_LIMIT = 1024


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


def _path_parent(value: object, path: tuple[int, ...], *, allow_append: bool = False) -> tuple[list, int]:
    if not path:
        raise ValueError("vertex path is required")
    current = value
    for index in path[:-1]:
        if not isinstance(current, list) or index < 0 or index >= len(current):
            raise IndexError("vertex path is outside the geometry")
        current = current[index]
    # allow_append：插入语义允许 index == len（追加到末位）。
    limit = len(current) + 1 if allow_append else len(current)
    if not isinstance(current, list) or path[-1] < 0 or path[-1] >= limit:
        raise IndexError("vertex path is outside the geometry")
    return current, path[-1]


def _closed_ring(parent: object) -> bool:
    """多边形 ring 坐标表是否以闭合形式存储（首 == 尾且 ≥4 点）。

    仅对 Polygon/MultiPolygon 的 ring 调用；闭合 LineString 的首尾重合是
    独立顶点（移动一端不带动另一端），不适用本判定。
    """
    return (
        isinstance(parent, list)
        and len(parent) >= 4
        and isinstance(parent[0], list)
        and parent[0] == parent[-1]
    )


def _is_ring_context(kind: str, path: tuple[int, ...]) -> bool:
    """路径末层容器是否为多边形 ring（Polygon [ring,v] / MultiPolygon [part,ring,v]）。"""
    if kind == "Polygon":
        return len(path) == 2
    if kind == "MultiPolygon":
        return len(path) == 3
    return False


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


class DuplicateFeatureCommand(EditCommand):
    """复制要素（V10）：全属性 + 几何复制，新 id；审计流与 add 区分。"""

    def __init__(self, feature: VectorFeature):
        EditCommand.__init__(self, "duplicate_feature", {feature.feature_id: None}, {feature.feature_id: feature})


class AddPartCommand(SetGeometryCommand):
    def __init__(self, before: VectorFeature, after: VectorFeature):
        EditCommand.__init__(self, "add_part", {before.feature_id: before}, {after.feature_id: after})


class DeletePartCommand(SetGeometryCommand):
    def __init__(self, before: VectorFeature, after: VectorFeature):
        EditCommand.__init__(self, "delete_part", {before.feature_id: before}, {after.feature_id: after})


class MovePartCommand(SetGeometryCommand):
    def __init__(self, before: VectorFeature, after: VectorFeature):
        EditCommand.__init__(self, "move_part", {before.feature_id: before}, {after.feature_id: after})


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
        # 原生编辑提交的审计流（M1 §2：EditCommand 同族记录；
        # 无 Python 会话——QGIS commit 后不可撤销，与镜像 undo 栈同语义）。
        self._commit_journal: list[dict[str, object]] = []

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

    def apply_committed_delta(
        self, delta: Mapping[str, object], *, session_id: str,
        source_tool: str,
    ) -> list[dict[str, object]]:
        """吸收一次原生编辑提交增量（拓扑编辑迁移 M1 §2 回写通道）。

        镜像侧已 commitChanges（QGIS undo 栈随之清空），宿主同语义：直接
        更新已提交状态，**不可撤销**；审计记录与 EditCommand 同族
        （``command_type`` + ``feature_ids`` + ``source_tool``），存于层
        级提交审计流。几何信任 QGIS 输出（闭合环等不变量由原生
        编辑保证）。返回本次产生的审计记录列表。
        """
        records: list[dict[str, object]] = []
        touched: set[str] = set()

        def _record(command_type: str, feature_ids) -> None:
            records.append({
                "command_type": command_type,
                "feature_ids": [str(fid) for fid in feature_ids],
                "session_id": session_id,
                "source_tool": source_tool,
            })

        for change in delta.get("geometry_changes") or ():
            feature_id = str(change.get("feature_id") or "")
            before = self._features.get(feature_id)
            if before is None:
                continue
            self._features[feature_id] = VectorFeature(
                feature_id, change.get("geometry") or {}, before.attributes)
            touched.add(feature_id)
            _record("set_geometry", [feature_id])
        for change in delta.get("attribute_changes") or ():
            feature_id = str(change.get("feature_id") or "")
            before = self._features.get(feature_id)
            if before is None:
                continue
            merged = dict(before.attributes)
            merged.update(change.get("changes") or {})
            self._features[feature_id] = VectorFeature(
                feature_id, before.geometry, merged)
            touched.add(feature_id)
            _record("change_attribute", [feature_id])
        removed = [str(fid) for fid in delta.get("removed") or ()]
        for feature_id in removed:
            if self._features.pop(feature_id, None) is not None:
                touched.add(feature_id)
        if removed:
            _record("delete_feature", removed)
        for feature in delta.get("added") or ():
            properties = dict(feature.get("properties") or {})
            feature_id = str(properties.pop("__pwb_fid", "")
                             or feature.get("id") or "")
            if not feature_id or feature_id in self._features:
                continue
            self._features[feature_id] = VectorFeature(
                feature_id, feature.get("geometry") or {}, properties)
            touched.add(feature_id)
            _record("add_feature", [feature_id])
        if touched:
            self.data_revision += 1
            self._selection.intersection_update(self._features)
            self._commit_journal.extend(records)
            if len(self._commit_journal) > _COMMIT_JOURNAL_LIMIT:
                del self._commit_journal[:len(self._commit_journal)
                                          - _COMMIT_JOURNAL_LIMIT]
        return records

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
        # EditDelta audit stream (Goal V7 §6): derived from the command flow,
        # never a second authority — commands remain the edit engine. The
        # journal is forward-only; undo/redo navigate history rather than
        # creating new edits and produce no deltas.
        self.session_id = uuid.uuid4().hex
        self.delta_journal: list[EditDelta] = []
        self._delta_order = 0
        self._delta_source_tool: str | None = None
        self._pending_deltas: list[EditDelta] | None = None
        # Engine provenance token (host sets from capability snapshot; the
        # literal default is honest for hosts without the bridge).
        self.qgis_capability_token: str = "unavailable"

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
        self._pending_deltas = []

    def end_edit_command(self) -> None:
        if self._open_command is None:
            raise RuntimeError("no edit command is open")
        commands = self._open_command
        self._open_command = None
        pending = self._pending_deltas
        self._pending_deltas = None
        if not commands:
            return
        before: dict[str, VectorFeature | None] = {}
        after: dict[str, VectorFeature | None] = {}
        for command in commands:
            for feature_id, value in command.before.items():
                before.setdefault(feature_id, value)
            after.update(command.after)
        self._record(EditCommand("compound", before, after), already_applied=True)
        if pending:
            # Compound commands keep their constituent deltas (one per
            # normalized operation) — e.g. vertex move + topology propagation
            # stays two deltas, not one opaque blob.
            self.delta_journal.extend(pending)
            if len(self.delta_journal) > DELTA_JOURNAL_LIMIT:
                del self.delta_journal[: len(self.delta_journal) - DELTA_JOURNAL_LIMIT]

    def destroy_edit_command(self) -> None:
        if self._open_command is None:
            raise RuntimeError("no edit command is open")
        touched: set[str] = set()
        for command in reversed(self._open_command):
            command.revert(self._working)
            touched.update(command.feature_ids)
        self._open_command = None
        # Discarded compounds discard their deltas too (nothing happened).
        self._pending_deltas = None
        if not touched:
            # 空宏（begin 后命令全部抛异常、未记录任何命令）：什么都没发生。
            # bump 会污染 revision 水位线，使 changes_since(旧水位) 返回 ()
            # 而消费方据此认为"零变更"——一次被拒手势本不该产生任何可观测
            # 变更。工作副本亦未被改动（revert 循环为空），无需通知。
            return
        self._bump_revision(touched)

    @contextmanager
    def edit_source(self, source_tool: str) -> Iterator["VectorEditSession"]:
        """Tag deltas recorded inside the block with ``source_tool``.

        Hosts wrap native-tool commit paths with e.g. ``add_polygon(native)``
        so the audit stream distinguishes QGIS-tool edits from fallback ones.
        """
        previous = self._delta_source_tool
        self._delta_source_tool = str(source_tool)
        try:
            yield self
        finally:
            self._delta_source_tool = previous

    def _record_delta(self, command: EditCommand) -> None:
        delta = delta_from_command(
            command,
            layer_id=self.layer.id,
            session_id=self.session_id,
            order=self._delta_order + 1,
            source_tool=self._delta_source_tool or "command",
            qgis_capability=self.qgis_capability_token,
            selection_context=self.layer.selection,
        )
        if delta is None:
            return
        self._delta_order += 1
        if self._pending_deltas is not None:
            self._pending_deltas.append(delta)
            return
        self.delta_journal.append(delta)
        if len(self.delta_journal) > DELTA_JOURNAL_LIMIT:
            del self.delta_journal[: len(self.delta_journal) - DELTA_JOURNAL_LIMIT]

    def deltas(self) -> tuple[EditDelta, ...]:
        """The normalized edit stream (oldest first)."""
        return tuple(self.delta_journal)

    def _record(self, command: EditCommand, *, already_applied: bool = False) -> None:
        if not already_applied:
            command.apply(self._working)
        if self._open_command is not None:
            self._open_command.append(command)
            self._record_delta(command)
            return
        self.undo_stack.append(command)
        self.redo_stack.clear()
        self._bump_revision(command.feature_ids)
        self._record_delta(command)

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
        closed = _is_ring_context(str(geometry["type"]), tuple(path)) and _closed_ring(parent)
        parent[index] = list(_point(coordinate))
        if closed:
            # 闭环不变量（V10）：拖动 ring 首顶点或闭合重复点必须同步另一端，
            # 否则权威 GeoJSON ring 不闭合（RFC 7946 违规，下游校验被打爆）。
            if index == 0:
                parent[-1] = list(parent[0])
            elif index == len(parent) - 1:
                parent[0] = list(parent[-1])
        after = VectorFeature(before.feature_id, geometry, before.attributes)
        self._record(SetVertexCommand(before, after))

    def insert_vertex(self, feature_id: str, path: tuple[int, ...], coordinate: object) -> None:
        before = self.feature(feature_id)
        geometry = _thaw(before.geometry)
        key = tuple(path)
        parent, index = _path_parent(geometry["coordinates"], key, allow_append=True)
        value = list(_point(coordinate))
        closed = _is_ring_context(str(geometry["type"]), key) and _closed_ring(parent)
        if closed and index >= len(parent) - 1:
            # 追加到闭合重复点之后会打开 ring；唯一有意义的"末尾插入"位是
            # 闭合点之前。
            index = len(parent) - 1
        parent.insert(index, value)
        if closed and index == 0:
            # 新首顶点成为环起点，闭合重复点跟随。
            parent[-1] = list(value)
        after = VectorFeature(before.feature_id, geometry, before.attributes)
        self._record(InsertVertexCommand(before, after))

    def delete_vertex(self, feature_id: str, path: tuple[int, ...]) -> None:
        before = self.feature(feature_id)
        geometry = _thaw(before.geometry)
        key = tuple(path)
        parent, index = _path_parent(geometry["coordinates"], key)
        closed = _is_ring_context(str(geometry["type"]), key) and _closed_ring(parent)
        if closed and index == len(parent) - 1:
            # 只删闭合重复点等于打开 ring；该路径语义上删除最后一个真实顶点。
            index = len(parent) - 2
        del parent[index]
        kind = str(geometry["type"])
        if closed:
            if len(parent) < 4:
                raise ValueError("a polygon ring must keep at least three vertices")
            parent[-1] = list(parent[0])
        elif kind in ("LineString", "MultiLineString") and len(parent) < 2:
            raise ValueError("a line must keep at least two vertices")
        elif kind == "MultiPoint" and not parent:
            raise ValueError("a multipoint must keep at least one vertex")
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

    def duplicate_feature(self, feature_id: str, new_feature_id: str | None = None) -> VectorFeature:
        """复制要素（V10）：几何 + 属性全拷贝，新 id（默认派生 uuid 后缀）。"""
        source = self.feature(feature_id)
        if new_feature_id and new_feature_id in self._working:
            # 显式 id 冲突即拒绝（review-2 #2）：DuplicateFeatureCommand 的
            # before={id: None} 会让 apply 覆盖既有要素、undo 删除原要素。
            raise ValueError(f"feature {new_feature_id!r} already exists")
        duplicate = VectorFeature(
            new_feature_id if new_feature_id else f"{source.feature_id}-copy-{uuid.uuid4().hex[:8]}",
            _thaw(source.geometry),
            source.attributes,
        )
        self._record(DuplicateFeatureCommand(duplicate))
        return duplicate

    def add_part(self, feature_id: str, geometry: Mapping[str, Any]) -> None:
        """附加部件（V10）：新整体几何（QGIS addPart 语义：单部件自动升多部件）
        由调用方（QGIS 几何执行）计算，本会话只落命令——事务/undo/delta 链完整。"""
        before = self.feature(feature_id)
        after = VectorFeature(before.feature_id, geometry, before.attributes)
        self._record(AddPartCommand(before, after))

    def delete_part(self, feature_id: str, geometry: Mapping[str, Any]) -> None:
        """移除部件（V10）：同 :meth:`add_part`，几何由 QGIS deletePart 计算。"""
        before = self.feature(feature_id)
        after = VectorFeature(before.feature_id, geometry, before.attributes)
        self._record(DeletePartCommand(before, after))

    def move_part(self, feature_id: str, part_index: int, dx: float, dy: float) -> None:
        """平移单个部件（V10）：纯坐标平移（无几何语义争议，会话内执行）。"""
        before = self.feature(feature_id)
        geometry = _thaw(before.geometry)
        kind = str(geometry["type"])
        if kind not in {"MultiPoint", "MultiLineString", "MultiPolygon"}:
            raise ValueError("moving a part requires a multipart geometry")
        parts = geometry["coordinates"]
        if part_index < 0 or part_index >= len(parts):
            raise IndexError("part index is outside the geometry")
        if kind == "MultiPolygon":
            parts[part_index] = [_translate(ring, dx, dy) for ring in parts[part_index]]
        else:
            parts[part_index] = _translate(parts[part_index], dx, dy)
        after = VectorFeature(before.feature_id, geometry, before.attributes)
        self._record(MovePartCommand(before, after))

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

    def pop_command(self, command: EditCommand) -> bool:
        """按身份从 undo 栈中弹出任意命令并回滚其效果（复合事务用）。

        与 :meth:`undo` 的区别：命令不进 redo 栈——跨图层复合事务把整组
        撤销的历史寄存在事务本身（TopologyService.CompoundUndoGroup），
        单层 redo 不能绕过组重新应用半组编辑。弹出序由调用方（事务）
        保证；不可用（宏打开 / 命令不在栈上）时返回 False。
        """
        if self._open_command is not None:
            return False
        # 身份匹配（review-2 P2-3）：EditCommand 是 frozen dataclass，==
        # 按值比较——快照相同的两条命令会错位互配；组语义要求对象同一。
        index = next(
            (i for i, item in enumerate(self.undo_stack) if item is command), -1
        )
        if index < 0:
            return False
        del self.undo_stack[index]
        command.revert(self._working)
        self.redo_stack.clear()
        self._bump_revision(command.feature_ids)
        self.layer._selection.intersection_update(self._working)
        return True

    def push_command_back(self, command: EditCommand) -> bool:
        """重新应用一个被 :meth:`pop_command` 弹出的命令（复合事务重做）。

        应用效果并把命令追加回 undo 栈顶（redo 栈语义仍由事务组持有，
        单层路径不可见）；宏打开时拒绝。
        """
        if self._open_command is not None:
            return False
        command.apply(self._working)
        self.undo_stack.append(command)
        self.redo_stack.clear()
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
        # 回滚 = 本会话的编辑从未落地；delta 审计流随之整段作废（与会话
        # journal 的 None 语义对齐：不留可误读的"零变更"历史）。
        self.delta_journal.clear()
        self._pending_deltas = None
        # 工作副本整体替换：任何旧修订的增量跨度都不可恢复。bump 之后再
        # 清空日志——若留下这条空条目，changes_since(旧修订) 会误判为
        # 「零变更」而保留过期 records；空日志使其返回 None → 全量重建。
        self._bump_revision()
        self._journal = []
        self.layer._discard_session(self)

    def audit_history(self) -> list[dict[str, object]]:
        return [command.audit_record() for command in self.undo_stack]
