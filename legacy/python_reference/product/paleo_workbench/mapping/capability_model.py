"""Derived QGIS capability snapshots for the authoring kernel.

Single derivation chain::

    C++ capability_manifest()  (compile-time registry, zero-init probe)
        -> probe_qgis_capability() -> QgisCapabilitySnapshot
            -> ToolContext.capability_flags -> tool_availability evaluator
    (V8 M1: per-layer gating lives in tool_availability; the manifest
     snapshot is the bridge-capability authority only)

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

# M3/M4-era bridges (pre-manifest) verifiably expose this surface — every
# shipped ``set_map_tool`` since the first workstation canvas accepted these
# kinds. Degraded (manifest-less) snapshots report it as the legacy baseline
# instead of an empty set, so existing installs keep working; V7 additions
# (measure/reshape, endpoint/intersection snapping) stay honestly absent.
# This is a baseline assertion for the degraded path only — the C++ manifest
# remains the single authority for available bridges (review-2 P2-1: no
# second Python-side capability mirror is kept).
LEGACY_NATIVE_TOOLS = frozenset(
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
        the evaluator can gate per-tool without re-probing. Degraded (legacy)
        snapshots expose the M3/M4 baseline tool set and no V7 features.
        """
        flags = {f"qgis.{name}" for name in self.features}
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
        [
            snapshot.status,
            snapshot.contract_version,
            sorted(snapshot.native_tools),
            sorted(snapshot.geometry_ops),
            sorted(snapshot.features),
        ],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def probe_qgis_capability(_import_bridge=None) -> QgisCapabilitySnapshot:
    """Assemble the bridge snapshot. Cheap: import + compile-time manifest only.

    This does **not** spin up the QGIS runtime; runtime verification stays with
    ``map_render_backend.qgis_backend_probe`` (render backend selection) —
    capability surface and runtime health are separate concerns.

    ``_import_bridge`` is an injection hook for tests (a zero-argument
    callable returning the bridge module); production always uses the real
    import. It exists because simulating "bridge missing" via sys.modules
    surgery poisons the Windows extension-loader state for later tests in
    the same process.
    """
    if _import_bridge is None:
        try:
            from paleo_workbench.mapping.qgis_style import ensure_qgis_bridge_dll_dirs

            ensure_qgis_bridge_dll_dirs()  # Windows V7: vendor DLL path before import
            import qgis_render_bridge as bridge
        except ImportError:
            return QgisCapabilitySnapshot(status="unavailable", reason=BRIDGE_BUILD_HINT)
        except Exception as exc:
            # 桥损坏（.pyd 加载失败等非 ImportError）也必须给出 degraded 判词，
            # 绝不让 probe 把异常抛进宿主构造链（P2-9）。
            return QgisCapabilitySnapshot(
                status="degraded",
                reason=f"qgis_render_bridge 加载失败：{exc}",
                native_tools=LEGACY_NATIVE_TOOLS,
            )
    else:
        try:
            bridge = _import_bridge()
        except ImportError:
            return QgisCapabilitySnapshot(status="unavailable", reason=BRIDGE_BUILD_HINT)
        except Exception as exc:
            return QgisCapabilitySnapshot(
                status="degraded",
                reason=f"qgis_render_bridge 加载失败：{exc}",
                native_tools=LEGACY_NATIVE_TOOLS,
            )

    version = getattr(bridge, "__version__", None)
    manifest_fn = getattr(bridge, "capability_manifest", None)
    if manifest_fn is None:
        # Bridge predates the manifest API: degrade with the verifiable M3/M4
        # baseline instead of fabricating a full surface — existing installs
        # keep the pre-V7 tools, V7 additions stay honestly absent (P1-2).
        return QgisCapabilitySnapshot(
            status="degraded",
            reason="qgis_render_bridge 版本过旧：缺少 capability_manifest"
            "（原生测距/重塑与 endpoint/intersection 捕捉不可用；重建桥扩展可恢复）",
            bridge_version=str(version or "unknown"),
            native_tools=LEGACY_NATIVE_TOOLS,
        )
    try:
        manifest = manifest_fn()
    except Exception as exc:  # probe must never raise into callers
        return QgisCapabilitySnapshot(
            status="degraded",
            reason=f"capability_manifest() 调用失败：{exc}",
            bridge_version=str(version or "unknown"),
            native_tools=LEGACY_NATIVE_TOOLS,
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
