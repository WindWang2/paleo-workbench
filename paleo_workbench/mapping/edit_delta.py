"""EditDelta — normalized, serializable audit records for map authoring edits.

Every write flows through :class:`VectorEditSession` commands (the authority).
``EditDelta`` is a **derived observability contract** layered on that command
stream — it never applies, reverts or persists anything by itself. It answers:
who (source_tool), through which engine (qgis_capability), what (operation +
geometry hashes), in what order (order token), inside which session.

Operation set (Goal V7 §6): create_feature / move_feature / move_vertex /
delete_feature / split_feature / merge_features / replace_geometry /
update_attributes.
"""

from __future__ import annotations

import hashlib
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

__all__ = [
    "DELTA_JOURNAL_LIMIT",
    "EditDelta",
    "EditOperation",
    "geometry_hash",
]

DELTA_JOURNAL_LIMIT = 1024

EditOperation = str  # one of the constants below

OP_CREATE_FEATURE = "create_feature"
OP_MOVE_FEATURE = "move_feature"
OP_MOVE_VERTEX = "move_vertex"
OP_DELETE_FEATURE = "delete_feature"
OP_SPLIT_FEATURE = "split_feature"
OP_MERGE_FEATURES = "merge_features"
OP_REPLACE_GEOMETRY = "replace_geometry"
OP_UPDATE_ATTRIBUTES = "update_attributes"

EDIT_OPERATIONS = frozenset(
    {
        OP_CREATE_FEATURE,
        OP_MOVE_FEATURE,
        OP_MOVE_VERTEX,
        OP_DELETE_FEATURE,
        OP_SPLIT_FEATURE,
        OP_MERGE_FEATURES,
        OP_REPLACE_GEOMETRY,
        OP_UPDATE_ATTRIBUTES,
    }
)

# session command_type -> EditDelta operation
_COMMAND_OPERATION: dict[str, str] = {
    "add_feature": OP_CREATE_FEATURE,
    "delete_feature": OP_DELETE_FEATURE,
    "move_feature": OP_MOVE_FEATURE,
    "set_vertex": OP_MOVE_VERTEX,
    "insert_vertex": OP_MOVE_VERTEX,
    "delete_vertex": OP_MOVE_VERTEX,
    "change_attribute": OP_UPDATE_ATTRIBUTES,
    "split_feature": OP_SPLIT_FEATURE,
    "merge_features": OP_MERGE_FEATURES,
    "set_geometry": OP_REPLACE_GEOMETRY,
    "add_ring": OP_REPLACE_GEOMETRY,
    "delete_ring": OP_REPLACE_GEOMETRY,
}


def geometry_hash(geometry: Mapping[str, Any] | None) -> str | None:
    """Stable content digest of a GeoJSON geometry (before-state anchors)."""
    if geometry is None:
        return None
    try:
        payload = json.dumps(_thaw(geometry), ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class EditDelta:
    """One normalized edit record (Goal V7 §6 field contract)."""

    layer_id: str
    feature_id: str
    operation: EditOperation
    session_id: str
    order: int
    source_tool: str = "command"
    qgis_capability: str = "unavailable"
    before_geometry_hash: str | None = None
    after_geometry: Mapping[str, Any] | None = None
    attribute_delta: Mapping[str, Any] | None = None
    selection_context: tuple[str, ...] = ()
    related_feature_ids: tuple[str, ...] = ()
    timestamp: float = field(default_factory=time.time)
    contract_version: int = 1

    def __post_init__(self) -> None:
        if self.operation not in EDIT_OPERATIONS:
            raise ValueError(f"unknown edit operation {self.operation!r}")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "layer_id": self.layer_id,
            "feature_id": self.feature_id,
            "operation": self.operation,
            "session_id": self.session_id,
            "order": self.order,
            "source_tool": self.source_tool,
            "qgis_capability": self.qgis_capability,
            "before_geometry_hash": self.before_geometry_hash,
            "after_geometry": _thaw(self.after_geometry) if self.after_geometry is not None else None,
            "attribute_delta": _thaw(self.attribute_delta) if self.attribute_delta is not None else None,
            "selection_context": list(self.selection_context),
            "related_feature_ids": list(self.related_feature_ids),
            "timestamp": self.timestamp,
            "contract_version": self.contract_version,
        }
        return data

    @property
    def from_native_tool(self) -> bool:
        return self.source_tool.endswith("(native)")


def _attribute_delta(before: Any, after: Any) -> dict[str, Any] | None:
    """Changed attributes with ``{key: [before, after]}`` entries."""
    before_attrs = dict(getattr(before, "attributes", {}) or {})
    after_attrs = dict(getattr(after, "attributes", {}) or {})
    delta = {
        key: [before_attrs.get(key), after_attrs.get(key)]
        for key in sorted(set(before_attrs) | set(after_attrs))
        if before_attrs.get(key) != after_attrs.get(key)
    }
    return delta or None


def delta_from_command(
    command: Any,
    *,
    layer_id: str,
    session_id: str,
    order: int,
    source_tool: str,
    qgis_capability: str,
    selection_context: Iterable[str] = (),
    timestamp: float | None = None,
) -> EditDelta | None:
    """Derive one EditDelta from an EditCommand (compound commands flatten upstream).

    Returns ``None`` for command types with no normalized meaning
    (``compound`` must be flattened by the caller into its constituents).
    """
    command_type = getattr(command, "command_type", "")
    operation = _COMMAND_OPERATION.get(command_type)
    if operation is None:
        return None
    before: Mapping[str, Any] = getattr(command, "before", {}) or {}
    after: Mapping[str, Any] = getattr(command, "after", {}) or {}
    before_feature = next((item for item in before.values() if item is not None), None)
    after_feature = next((item for item in after.values() if item is not None), None)
    primary_id = ""
    related: tuple[str, ...] = ()
    if command_type == "split_feature":
        # The removed original is the anchor; replacements are related.
        primary_id = next((fid for fid, value in before.items() if value is not None), "")
        related = tuple(fid for fid, value in after.items() if value is not None and fid != primary_id)
    elif command_type == "merge_features":
        primary_id = next((fid for fid, value in after.items() if value is not None), "")
        related = tuple(fid for fid, value in before.items() if value is not None and fid != primary_id)
    else:
        primary_id = after_feature.feature_id if after_feature is not None else (before_feature.feature_id if before_feature is not None else "")

    after_geometry = None
    if operation != OP_UPDATE_ATTRIBUTES and after_feature is not None:
        after_geometry = _thaw(after_feature.geometry)
    attribute_delta = None
    if operation == OP_UPDATE_ATTRIBUTES and before_feature is not None and after_feature is not None:
        attribute_delta = _attribute_delta(before_feature, after_feature)

    return EditDelta(
        layer_id=layer_id,
        feature_id=str(primary_id),
        operation=operation,
        session_id=session_id,
        order=order,
        source_tool=str(source_tool or "command"),
        qgis_capability=str(qgis_capability or "unavailable"),
        before_geometry_hash=geometry_hash(before_feature.geometry) if before_feature is not None else None,
        after_geometry=after_geometry,
        attribute_delta=attribute_delta,
        selection_context=tuple(str(fid) for fid in selection_context),
        related_feature_ids=related if command_type in {"split_feature", "merge_features"} else (),
        timestamp=time.time() if timestamp is None else timestamp,
    )


@contextmanager
def _edit_source(session: Any, source_tool: str):
    """Tag deltas recorded inside the block with ``source_tool``."""
    previous = getattr(session, "_delta_source_tool", None)
    session._delta_source_tool = str(source_tool)
    try:
        yield session
    finally:
        session._delta_source_tool = previous
