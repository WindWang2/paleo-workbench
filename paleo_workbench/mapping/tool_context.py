"""ToolContext — the derived, serializable state consumed by the tool evaluator.

The context is a *projection* of existing authorities (edit controller, layer
facts, session buffers, snapping/topology services, bridge capability, mapping
stage). It is frozen and Qt-free; ``evaluate_tool``/``evaluate_all`` in
``paleo_workbench.mapping.tool_availability`` are pure functions over it.

V8 canonical contract (contract_version=2, Goal M1):

* Layer facts are **flat** fields (role/kind/maturity/frozen/missing/degraded)
  — no nested presentation snapshot on the evaluator input. The UI keeps its
  own presentation projections; this type is the single evaluation input.
* ``mapping_stage`` is tri-state: ``None`` = the surface has no stage
  semantics (legacy authoring page) and stage gating is skipped; ``""`` or an
  unknown value = stage unknown → fail-closed in the evaluator.
* ``backend_mode`` carries the *runtime canvas backend* state
  (native/degraded/unavailable/unknown) — distinct from the compile-time
  bridge manifest authority in :mod:`paleo_workbench.mapping.capability_model`
  (which feeds ``qgis_available``/``capability_flags``).
* The stage tool profile is derived **inside** the evaluator (single
  derivation); the host no longer pre-computes hidden-action sets.

Only additive changes are allowed after this contract lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from paleo_workbench.mapping.capability_model import (
    QgisCapabilitySnapshot,
    probe_qgis_capability,
)

__all__ = ["ToolContext", "build_tool_context", "TOOL_CONTEXT_CONTRACT_VERSION"]

TOOL_CONTEXT_CONTRACT_VERSION = 2


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Immutable snapshot of everything the evaluator is allowed to know.

    Field policy (contract completeness): ``wkb_type``/``qgis_layer_type``/
    ``selection_geometry_types``/``compatible_polygon_count``/
    ``topology_error_count`` are carried for downstream consumers (status
    bar, palette, audit, M4 explainability) even when the current evaluator
    derives coarse checks from the ``*_ready`` flags — they are contract
    surface, not dead weight, and stay populated by the host collector.
    """

    # Project / environment
    project_open: bool = True
    qgis_available: bool = False
    native_canvas_available: bool = False
    #: Runtime canvas backend state: native | degraded | unavailable | unknown.
    backend_mode: str = "unknown"
    backend_reason: str = ""
    blocking_task: str = ""

    # Stage semantics (None = surface without stage semantics; ""/unknown = fail-closed)
    mapping_stage: str | None = None
    write_granted: bool = False

    # Active layer facts (presentation-relevant conclusions from domain authority)
    active_layer_id: str = ""
    active_layer_kind: str = ""            # "point" | "line" | "polygon" | ""
    layer_name: str = ""
    layer_role: str = ""                   # LayerRole.value ("" unknown)
    layer_role_label: str = ""
    artifact_maturity: str = ""            # raw/draft/reviewed/frozen/published
    layer_frozen: bool = False
    layer_missing: bool = False
    layer_degraded: bool = False
    qgis_layer_type: str = ""              # "vector" | "raster" | ""
    wkb_type: str = ""                     # GeoJSON type actually stored
    vector_writable: bool = False

    # Editing session
    editing: bool = False
    dirty: bool = False
    edit_gate_open: bool | None = True     # host gate conclusion; None = unknown
    edit_gate_reason: str = ""
    raw_locked: bool = False
    stage_locked: bool = False
    can_undo: bool = False
    can_redo: bool = False

    # Selection
    selection_count: int = 0
    selection_geometry_types: tuple[str, ...] = ()   # kinds among selection
    compatible_polygon_count: int = 0                 # polygon features selected in editable polygon layers
    topology_error_count: int = 0                     # open topology errors in the session

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
    #: 可查询图层计数（编修层 + 基础工区层 + 就绪引用层，宿主派生；
    #: identify 门禁的唯一图层输入——无活动层时仍可识别）。
    queryable_layer_count: int = 0

    # Extent history (canvas-level navigation state)
    can_previous_extent: bool = False
    can_next_extent: bool = False

    contract_version: int = TOOL_CONTEXT_CONTRACT_VERSION

    # -- derivation helpers -------------------------------------------------

    @property
    def has_active_layer(self) -> bool:
        return bool(self.active_layer_id)

    @property
    def has_active_vector_layer(self) -> bool:
        """A vector layer is registered as active (kind may still be unknown)."""
        return bool(self.active_layer_id) and self.qgis_layer_type != "raster"

    def to_dict(self) -> dict[str, Any]:
        data = {k: getattr(self, k) for k in self.__dataclass_fields__}
        data["selection_geometry_types"] = list(self.selection_geometry_types)
        data["capability_flags"] = sorted(self.capability_flags)
        return data


def build_tool_context(
    *,
    controller_state: dict[str, Any] | None = None,
    qgis: QgisCapabilitySnapshot | None = None,
    native_canvas_available: bool = False,
    project_open: bool = True,
    mapping_stage: str | None = None,
    layer_facts: dict[str, Any] | None = None,
    backend_mode: str = "unknown",
    backend_reason: str = "",
) -> ToolContext:
    """Assemble a ToolContext from the host's derived state (pure derivation).

    ``controller_state`` is a plain dict produced by
    ``CompositeEditController.tool_context_inputs()``; ``layer_facts`` carries
    the active layer's domain facts (role/kind/maturity/frozen/missing/
    degraded/name/label — the ``CompositeDocument`` layer projection). All
    keys are optional; missing keys fall back to safe defaults.
    """
    state: dict[str, Any] = dict(controller_state or {})
    facts: dict[str, Any] = dict(layer_facts or {})
    qgis = qgis or probe_qgis_capability()

    gate_value = state.get("edit_gate_open", True)
    gate_allowed: bool | None
    if gate_value is None:
        gate_allowed = None
    else:
        gate_allowed = bool(gate_value)
    kind = str(facts.get("active_layer_kind") or state.get("active_layer_kind") or "")
    return ToolContext(
        project_open=bool(project_open and state.get("project_open", True)),
        qgis_available=qgis.available,
        native_canvas_available=bool(native_canvas_available and qgis.available),
        backend_mode=str(backend_mode),
        backend_reason=str(backend_reason or ""),
        blocking_task=str(state.get("blocking_task") or ""),
        mapping_stage=mapping_stage if mapping_stage is not None else (
            # 显式 "" 保留（fail-closed 未知阶段）；缺键才是 None（无阶段语义）。
            str(state["mapping_stage"]) if "mapping_stage" in state else None
        ),
        write_granted=bool(facts.get("write_granted", False)),
        active_layer_id=str(facts.get("active_layer_id") or state.get("active_layer_id") or ""),
        active_layer_kind=kind,
        layer_name=str(facts.get("layer_name") or ""),
        layer_role=str(facts.get("layer_role") or ""),
        layer_role_label=str(facts.get("layer_role_label") or ""),
        artifact_maturity=str(facts.get("artifact_maturity") or ""),
        layer_frozen=bool(facts.get("layer_frozen", False)),
        layer_missing=bool(facts.get("layer_missing", False)),
        layer_degraded=bool(facts.get("layer_degraded", False)),
        qgis_layer_type=str(
            facts.get("qgis_layer_type")
            or state.get("qgis_layer_type")
            or ("vector" if kind else "")
        ),
        wkb_type=str(state.get("wkb_type") or ""),
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
        topology_error_count=int(state.get("topology_error_count", 0) or 0),
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
        queryable_layer_count=int(state.get("queryable_layer_count", 0) or 0),
        can_previous_extent=bool(state.get("can_previous_extent", False)),
        can_next_extent=bool(state.get("can_next_extent", False)),
    )
