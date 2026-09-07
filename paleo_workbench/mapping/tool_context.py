"""ToolContext — the derived, serializable state consumed by the tool evaluator.

The context is a *projection* of existing authorities (edit controller, layer
state, session buffers, snapping/topology services, bridge capability). It is
frozen and Qt-free; ``evaluate_tool``/``evaluate_all`` in
``paleo_workbench.mapping.tool_availability`` are pure functions over it.

Field names follow the V7 goal contract; only additive changes are allowed
(``contract_version`` bumps on semantic change).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from paleo_workbench.mapping.capability_model import (
    QgisCapabilitySnapshot,
    probe_qgis_capability,
)

__all__ = ["ToolContext", "build_tool_context", "TOOL_CONTEXT_CONTRACT_VERSION"]

TOOL_CONTEXT_CONTRACT_VERSION = 1


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Immutable snapshot of everything the evaluator is allowed to know."""

    # Project / environment
    project_open: bool = False
    qgis_available: bool = False
    native_canvas_available: bool = False
    blocking_task: str = ""

    # Active layer
    active_layer_id: str = ""
    active_layer_kind: str = ""            # "point" | "line" | "polygon" | ""
    qgis_layer_type: str = ""              # "vector" | "raster" | ""
    wkb_type: str = ""                     # GeoJSON type actually stored
    layer_role: str = ""                   # RAW / DERIVED / ... ("" unknown)
    artifact_maturity: str = ""            # maturity label when known
    mapping_stage: str = ""                # current mapping stage id
    vector_writable: bool = False

    # Editing session
    editing: bool = False
    dirty: bool = False
    edit_gate_open: bool = True            # gate allowed for this layer
    edit_gate_reason: str = ""
    raw_locked: bool = False
    stage_locked: bool = False
    can_undo: bool = False
    can_redo: bool = False

    # Selection
    selection_count: int = 0
    selection_geometry_types: tuple[str, ...] = ()   # kinds among selection
    compatible_polygon_count: int = 0                 # polygon features selected in editable polygon layers

    # Split/merge/reshape inputs (pre-computed by host; keeps rules pure)
    split_ready: bool = False
    merge_ready: bool = False
    reshape_ready: bool = False

    # GIS state
    snapping_available: bool = True
    snapping_enabled: bool = False
    topology_available: bool = True
    topology_enabled: bool = False
    crs_valid: bool = True

    # Tool state
    current_tool: str = "pan"
    capability_flags: frozenset[str] = frozenset()

    # Extent history (canvas-level navigation state)
    can_previous_extent: bool = False
    can_next_extent: bool = False

    # Stage tool profile: tool ids hidden by the current mapping stage.
    hidden_by_stage_profile: frozenset[str] = frozenset()

    contract_version: int = TOOL_CONTEXT_CONTRACT_VERSION

    # -- derivation helpers -------------------------------------------------

    def with_capability(self, snapshot: QgisCapabilitySnapshot) -> "ToolContext":
        return replace(
            self,
            qgis_available=snapshot.available,
            capability_flags=snapshot.capability_flags(),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {k: getattr(self, k) for k in self.__dataclass_fields__}
        data["selection_geometry_types"] = list(self.selection_geometry_types)
        data["capability_flags"] = sorted(self.capability_flags)
        data["hidden_by_stage_profile"] = sorted(self.hidden_by_stage_profile)
        return data


def build_tool_context(
    *,
    controller_state: dict[str, Any] | None = None,
    qgis: QgisCapabilitySnapshot | None = None,
    native_canvas_available: bool = False,
    project_open: bool = True,
    mapping_stage: str = "",
    hidden_by_stage_profile: Iterable[str] = (),
) -> ToolContext:
    """Assemble a ToolContext from the edit controller's derived state.

    ``controller_state`` is a plain dict produced by
    ``CompositeEditController.tool_context_inputs()`` — keeping the collector
    on the controller side avoids importing Qt-side modules here. All keys are
    optional; missing keys fall back to the empty context.
    """
    state: dict[str, Any] = dict(controller_state or {})
    qgis = qgis or probe_qgis_capability()

    gate_allowed = bool(state.get("edit_gate_open", True))
    return ToolContext(
        project_open=bool(project_open and state.get("project_open", True)),
        qgis_available=qgis.available,
        native_canvas_available=bool(native_canvas_available and qgis.available),
        blocking_task=str(state.get("blocking_task") or ""),
        active_layer_id=str(state.get("active_layer_id") or ""),
        active_layer_kind=str(state.get("active_layer_kind") or ""),
        qgis_layer_type=str(state.get("qgis_layer_type") or ("vector" if state.get("active_layer_kind") else "")),
        wkb_type=str(state.get("wkb_type") or ""),
        layer_role=str(state.get("layer_role") or ""),
        artifact_maturity=str(state.get("artifact_maturity") or ""),
        mapping_stage=str(mapping_stage or state.get("mapping_stage") or ""),
        vector_writable=bool(state.get("vector_writable", False)),
        editing=bool(state.get("editing", False)),
        dirty=bool(state.get("dirty", False)),
        edit_gate_open=gate_allowed,
        edit_gate_reason=str(state.get("edit_gate_reason") or ""),
        raw_locked=bool(state.get("raw_locked", False)),
        stage_locked=bool(state.get("stage_locked", False)),
        can_undo=bool(state.get("can_undo", False)),
        can_redo=bool(state.get("can_redo", False)),
        selection_count=int(state.get("selection_count", 0) or 0),
        selection_geometry_types=tuple(
            str(value) for value in state.get("selection_geometry_types", ()) or ()
        ),
        compatible_polygon_count=int(state.get("compatible_polygon_count", 0) or 0),
        split_ready=bool(state.get("split_ready", False)),
        merge_ready=bool(state.get("merge_ready", False)),
        reshape_ready=bool(state.get("reshape_ready", False)),
        snapping_available=bool(state.get("snapping_available", True)),
        snapping_enabled=bool(state.get("snapping_enabled", False)),
        topology_available=bool(state.get("topology_available", True)),
        topology_enabled=bool(state.get("topology_enabled", False)),
        crs_valid=bool(state.get("crs_valid", True)),
        current_tool=str(state.get("current_tool") or "pan"),
        capability_flags=qgis.capability_flags(),
        hidden_by_stage_profile=frozenset(str(t) for t in hidden_by_stage_profile),
        can_previous_extent=bool(state.get("can_previous_extent", False)),
        can_next_extent=bool(state.get("can_next_extent", False)),
    )
