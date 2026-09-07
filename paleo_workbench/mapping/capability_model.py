"""Derived QGIS capability snapshots for the authoring kernel.

Single derivation chain::

    C++ capability_manifest()  (compile-time registry, zero-init probe)
        -> probe_qgis_capability() -> QgisCapabilitySnapshot
            -> LayerCapabilitySnapshot(layer state + snapshot + edit gate)
            -> ToolContext.capability_flags -> tool_availability evaluator

Rules of engagement (Goal V7):

* The snapshot is **derived**, never a second authority: it mirrors what the
  vendored bridge actually exposes. When the bridge is missing it reports
  ``unavailable`` with a human-readable reason instead of guessing.
* Every capability carries ``(available, reason)`` so UI layers can disable
  actions honestly — never a bare ``setEnabled(False)``.
* No Qt imports: this module is consumable headless (tests, CLI, UI alike).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

__all__ = [
    "BRIDGE_BUILD_HINT",
    "CapabilityFlag",
    "LayerCapabilitySnapshot",
    "QgisCapabilitySnapshot",
    "probe_qgis_capability",
    "snapshot_stable_hash",
]

BRIDGE_BUILD_HINT = (
    "qgis_render_bridge 未构建（可选组件）。构建："
    "PALEO_WITH_QGIS_RENDERER=1 pip install -e native/qgis_render_bridge"
)

# Minimum bridge API surface the authoring kernel consumes. A bridge older
# than this degrades instead of half-working (fail-honest, never fake).
_REQUIRED_MANIFEST_KEYS = ("native_tools", "geometry_ops", "dialogs", "features")

# Native map-tool kinds the kernel knows how to map Python tool ids onto.
# Must stay in sync with ``set_map_tool`` in map_stack_service.cpp; the C++
# manifest is the authority and this set only gates *consumption*.
KNOWN_NATIVE_TOOLS = frozenset(
    {
        "pan",
        "zoomIn",
        "zoomOut",
        "addPoint",
        "addLine",
        "addPolygon",
        "vertex",
        "move",
        "select",
        "identify",
        "measure",
        "reshape",
    }
)

KNOWN_GEOMETRY_OPS = frozenset(
    {
        "union",
        "split_by_line",
        "intersection",
        "difference",
        "symdifference",
        "buffer",
        "offset_curve",
        "simplify",
        "smooth",
        "densify",
        "make_valid",
        "is_valid",
        "validate",
        "reshape",
        "multipart_to_singlepart",
        "singlepart_to_multipart",
        "clip",
    }
)


@dataclass(frozen=True, slots=True)
class CapabilityFlag:
    """One capability with an honest disabled reason."""

    available: bool
    reason: str = ""

    def __post_init__(self) -> None:
        if self.available and self.reason:
            raise ValueError("an available capability must not carry a reason")

    @property
    def unavailable_reason(self) -> str:
        return "" if self.available else (self.reason or "capability unavailable")


@dataclass(frozen=True, slots=True)
class QgisCapabilitySnapshot:
    """Bridge-level capability snapshot (available / degraded / unavailable)."""

    status: str  # "available" | "degraded" | "unavailable"
    reason: str = ""
    bridge_version: str | None = None
    qgis_version: str | None = None
    native_tools: frozenset[str] = frozenset()
    geometry_ops: frozenset[str] = frozenset()
    dialogs: frozenset[str] = frozenset()
    features: frozenset[str] = frozenset()
    contract_version: int = 1

    def __post_init__(self) -> None:
        if self.status == "available" and self.reason:
            raise ValueError("an available snapshot must not carry a reason")

    @property
    def available(self) -> bool:
        return self.status != "unavailable"

    def feature(self, name: str) -> CapabilityFlag:
        """Probe a single feature flag (e.g. ``native_capture``/``snapping_push``)."""
        if self.status == "unavailable":
            return CapabilityFlag(False, self.reason or BRIDGE_BUILD_HINT)
        if name in self.features:
            return CapabilityFlag(True)
        return CapabilityFlag(False, f"qgis_render_bridge 不支持能力 {name!r}")

    def native_tool(self, kind: str) -> CapabilityFlag:
        if self.status == "unavailable":
            return CapabilityFlag(False, self.reason or BRIDGE_BUILD_HINT)
        if kind in self.native_tools:
            return CapabilityFlag(True)
        return CapabilityFlag(False, f"原生工具 {kind!r} 在当前桥版本不可用")

    def geometry_op(self, op: str) -> CapabilityFlag:
        if self.status == "unavailable":
            return CapabilityFlag(False, self.reason or BRIDGE_BUILD_HINT)
        if op in self.geometry_ops:
            return CapabilityFlag(True)
        return CapabilityFlag(False, f"几何操作 {op!r} 在当前桥版本不可用")

    def capability_flags(self) -> frozenset[str]:
        """``"qgis.<feature>"`` flag set consumed by ToolContext.

        Synthesizes ``qgis.native_tool.<kind>`` / ``qgis.geometry_op.<op>``
        from the manifest lists plus the coarse ``qgis.<feature>`` flags, so
        the evaluator can gate per-tool without re-probing.
        """
        flags = {f"qgis.{name}" for name in self.features}
        if self.available:
            flags.update(f"qgis.native_tool.{kind}" for kind in self.native_tools)
            flags.update(f"qgis.geometry_op.{op}" for op in self.geometry_ops)
        return frozenset(flags)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "bridge_version": self.bridge_version,
            "qgis_version": self.qgis_version,
            "native_tools": sorted(self.native_tools),
            "geometry_ops": sorted(self.geometry_ops),
            "dialogs": sorted(self.dialogs),
            "features": sorted(self.features),
            "contract_version": self.contract_version,
        }


def snapshot_stable_hash(snapshot: QgisCapabilitySnapshot) -> str:
    """Stable short digest recorded into EditDelta.qgis_capability."""
    import hashlib
    import json

    payload = json.dumps(
        [snapshot.status, sorted(snapshot.native_tools), sorted(snapshot.geometry_ops), sorted(snapshot.features)],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def probe_qgis_capability() -> QgisCapabilitySnapshot:
    """Assemble the bridge snapshot. Cheap: import + compile-time manifest only.

    This does **not** spin up the QGIS runtime; runtime verification stays with
    ``map_render_backend.qgis_backend_probe`` (render backend selection) —
    capability surface and runtime health are separate concerns.
    """
    try:
        import qgis_render_bridge as bridge
    except ImportError:
        return QgisCapabilitySnapshot(status="unavailable", reason=BRIDGE_BUILD_HINT)

    version = getattr(bridge, "__version__", None)
    manifest_fn = getattr(bridge, "capability_manifest", None)
    if manifest_fn is None:
        # Bridge predates the manifest API: degrade with the concrete gap
        # instead of fabricating a capability surface.
        return QgisCapabilitySnapshot(
            status="degraded",
            reason="qgis_render_bridge 版本过旧：缺少 capability_manifest（需重建桥扩展）",
            bridge_version=str(version or "unknown"),
        )
    try:
        manifest = manifest_fn()
    except Exception as exc:  # probe must never raise into callers
        return QgisCapabilitySnapshot(
            status="degraded",
            reason=f"capability_manifest() 调用失败：{exc}",
            bridge_version=str(version or "unknown"),
        )
    if not isinstance(manifest, Mapping) or any(key not in manifest for key in _REQUIRED_MANIFEST_KEYS):
        missing = [key for key in _REQUIRED_MANIFEST_KEYS if not isinstance(manifest, Mapping) or key not in manifest]
        return QgisCapabilitySnapshot(
            status="degraded",
            reason=f"capability_manifest 缺少字段：{', '.join(missing)}",
            bridge_version=str(version or "unknown"),
        )

    def _fset(value: Iterable[Any]) -> frozenset[str]:
        return frozenset(str(item) for item in (value or ()))

    return QgisCapabilitySnapshot(
        status="available",
        bridge_version=str(version or "unknown"),
        qgis_version=str(manifest.get("qgis_version") or "") or None,
        native_tools=_fset(manifest["native_tools"]),
        geometry_ops=_fset(manifest["geometry_ops"]),
        dialogs=_fset(manifest["dialogs"]),
        features=_fset(manifest["features"]),
        contract_version=int(manifest.get("contract_version", 1) or 1),
    )


# ---------------------------------------------------------------------------
# Layer-level capability derivation
# ---------------------------------------------------------------------------

_LAYER_CAPABILITIES = (
    "can_identify",
    "can_select",
    "can_edit",
    "can_add_feature",
    "can_delete_feature",
    "can_change_geometry",
    "can_change_attributes",
    "can_split",
    "can_merge",
    "can_snap",
    "can_topology",
    "can_open_properties",
    "can_symbol_edit",
)


@dataclass(frozen=True, slots=True)
class LayerCapabilitySnapshot:
    """Per-layer capability set derived from layer state + bridge + edit gate.

    ``gate_result`` is the ``(allowed, reason)`` pair from the Paleo edit gate
    (RAW / stage locks). It is *derived per layer*, never cached, because role
    and stage state change with the project lifecycle.
    """

    layer_id: str
    layer_kind: str = ""  # "point" | "line" | "polygon" | ""
    is_vector: bool = True
    writable: bool = True
    gate_allowed: bool = True
    gate_reason: str = ""
    editing: bool = False
    qgis: QgisCapabilitySnapshot = field(default_factory=lambda: QgisCapabilitySnapshot(status="unavailable", reason=BRIDGE_BUILD_HINT))

    def capability(self, name: str) -> CapabilityFlag:
        if not self.is_vector:
            return CapabilityFlag(False, "非矢量图层")
        if name in {"can_identify", "can_select", "can_open_properties", "can_symbol_edit"}:
            return CapabilityFlag(True)
        # Everything below mutates layer data or session state.
        if not self.writable:
            return CapabilityFlag(False, "图层不可写")
        if name in {"can_snap", "can_topology"}:
            # Snapping/topology participate for any vector layer; the engine
            # itself comes from the bridge but the fallback stays functional.
            return CapabilityFlag(True)
        if not self.gate_allowed:
            return CapabilityFlag(False, self.gate_reason or "图层被锁定")
        if name in {"can_edit", "can_add_feature", "can_delete_feature", "can_change_geometry", "can_change_attributes"}:
            return CapabilityFlag(True)
        if name in {"can_split", "can_merge"}:
            flag = self.qgis.geometry_op("split_by_line") if name == "can_split" else self.qgis.geometry_op("union")
            if not flag.available:
                # Python/shapely fallback keeps the command workable; the
                # professional engine is degraded but the capability itself
                # remains (fallback executes with shapely semantics).
                return CapabilityFlag(True)
            return CapabilityFlag(True)
        return CapabilityFlag(False, f"未知图层能力 {name!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer_id": self.layer_id,
            "layer_kind": self.layer_kind,
            "is_vector": self.is_vector,
            "writable": self.writable,
            "gate_allowed": self.gate_allowed,
            "gate_reason": self.gate_reason,
            "editing": self.editing,
            "capabilities": {name: self.capability(name).available for name in _LAYER_CAPABILITIES},
            "reasons": {
                name: reason
                for name in _LAYER_CAPABILITIES
                if (reason := self.capability(name).unavailable_reason)
            },
        }


def layer_capability_snapshot(
    layer: Any,
    *,
    kind: str = "",
    qgis: QgisCapabilitySnapshot | None = None,
    gate_result: tuple[bool, str] | None = None,
) -> LayerCapabilitySnapshot:
    """Build the snapshot from live layer/controller state (pure derivation)."""
    qgis = qgis or probe_qgis_capability()
    allowed, reason = gate_result if gate_result is not None else (True, "")
    editing = getattr(layer, "edit_session", None) is not None
    return LayerCapabilitySnapshot(
        layer_id=str(getattr(layer, "id", "") or ""),
        layer_kind=str(kind or getattr(layer, "kind", "") or ""),
        is_vector=True,
        writable=bool(getattr(layer, "writable", True)),
        gate_allowed=bool(allowed),
        gate_reason=str(reason or ""),
        editing=editing,
        qgis=qgis,
    )
