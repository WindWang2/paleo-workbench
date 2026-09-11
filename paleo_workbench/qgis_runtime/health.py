"""Structured QGIS runtime health probe (V10 M-A / M-Q).

``probe_qgis_runtime()`` answers, with evidence and never a silent
fallback: is the bridge importable, which recipe loaded it, which QGIS /
PROJ / GDAL versions are live, where proj.db came from, can the runtime
resolve the CRSs Paleo cares about (EPSG:4326 / 4490 / 4214 / 4610), does a
coordinate transform work, which providers are registered.

Consumers (UI backend_status, ToolContext, docs) read
:class:`QgisRuntimeStatus` instead of ``try: import qgis_render_bridge``.
Every unavailable probe carries a reason in ``unavailable_reasons`` /
``degraded_reasons`` — "canvas renders" is never accepted as proof that the
*spatial* runtime is healthy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from paleo_workbench.qgis_runtime import proj_data as _proj
from paleo_workbench.qgis_runtime.loader import LoadRecipe, prepare_bridge_load

logger = logging.getLogger(__name__)

# CRSs the Paleo domain must be able to resolve (V10 review-round-2 set):
# WGS84, CGCS2000, Beijing 1954, Xian 1980.
KEY_CRS_PROBES = ("EPSG:4326", "EPSG:4490", "EPSG:4214", "EPSG:4610")

_STATUS_CACHE: QgisRuntimeStatus | None = None


@dataclass(frozen=True)
class QgisRuntimeStatus:
    qgis_available: bool
    qgis_version: str = ""
    bridge_version: str = ""
    recipe: str = ""
    prefix_path: str = ""
    proj_available: bool = False
    proj_version: str = ""
    proj_db_path: str = ""
    proj_source: str = ""
    gdal_available: bool = False
    gdal_version: str = ""
    gdal_data: str = ""
    provider_count: int = 0
    providers: tuple[str, ...] = ()
    crs_probes: tuple[tuple[str, bool], ...] = ()
    canvas_crs_available: bool = False
    transform_available: bool = False
    svg_paths: tuple[str, ...] = ()
    snapping_available: bool = False
    topology_available: bool = False
    native_features: tuple[str, ...] = ()
    degraded_reasons: tuple[str, ...] = ()
    unavailable_reasons: tuple[str, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)

    def crs_probe_map(self) -> dict[str, bool]:
        return dict(self.crs_probes)

    def as_dict(self) -> dict[str, Any]:
        data = {
            k: (list(v) if isinstance(v, tuple) else v)
            for k, v in self.__dict__.items()
            if k != "facts"
        }
        data["facts"] = dict(self.facts)
        return data


def reset_runtime_probe_cache() -> None:
    global _STATUS_CACHE
    _STATUS_CACHE = None


def _manifest_features(bridge: Any) -> dict[str, Any]:
    try:
        manifest = bridge.capability_manifest()
        return dict(manifest.get("features", {}))
    except Exception:
        return {}


def _probe_via_runtime_facts(stack: Any) -> dict[str, Any] | None:
    """New-bridge (>=0.6.0a0) one-shot facts: no canvas needed.

    Returns ``None`` when the probe is *unavailable or failed*, so the caller
    falls through to :func:`_probe_via_canvas_roundtrip`.  V10（#1262）：探针
    抛异常时曾返回 ``{"runtime_facts_error": ...}`` 真值 dict，而调用方的
    降级判定是 ``if probed is None`` → 文档承诺的"探针失败降级"这一支永不
    可达；同时该键还会抑制 CRS 不完整的降级提示。失败原因写入模块日志，
    信号与"旧桥没有该属性"统一为 None。
    """
    probe = getattr(stack, "runtime_facts", None)
    if not callable(probe):
        return None
    try:
        return dict(probe())
    except Exception as exc:
        logger.warning("runtime_facts() 探测失败，降级到 canvas roundtrip: %s", exc)
        return None


def _probe_via_canvas_roundtrip(stack: Any) -> dict[str, Any] | None:
    """Legacy-bridge (0.5.x) fallback: canvas CRS set/read round-trip.

    Needs a live QApplication (canvas is a QWidget); honestly reports
    None when there is none (headless CLI probes degrade, not fabricate).
    """
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return None
    if QApplication.instance() is None:
        return None
    # V10（#1262）：transform_available 不再硬编码 False——本路径逐个 CRS
    # 做 set/read 往返，往返本身即一次真实坐标变换；全部成功才声明可用。
    # （旧实现在函数内从不更新该键，旧桥环境恒定报告变换不可用。）
    facts: dict[str, Any] = {"crs_probes": {}}
    try:
        addr = stack.create_canvas()
        try:
            for authid in KEY_CRS_PROBES:
                try:
                    stack.set_destination_crs(addr, authid)
                    facts["crs_probes"][authid] = (
                        stack.canvas_destination_crs(addr) == authid
                    )
                except Exception:
                    facts["crs_probes"][authid] = False
        finally:
            stack.destroy_canvas(addr)
    except Exception as exc:
        facts["probe_error"] = str(exc)
    facts["transform_available"] = (
        bool(facts["crs_probes"])
        and all(facts["crs_probes"].values())
        and "probe_error" not in facts
    )
    return facts


def probe_qgis_runtime(*, refresh: bool = False) -> QgisRuntimeStatus:
    """Probe the full QGIS runtime; cached after the first call."""
    global _STATUS_CACHE
    if _STATUS_CACHE is not None and not refresh:
        return _STATUS_CACHE

    degraded: list[str] = []
    unavailable: list[str] = []

    report = prepare_bridge_load()
    proj = _proj.ensure_proj_data(report.paths, recipe=report.recipe)

    try:
        import qgis_render_bridge as bridge
    except Exception as exc:
        unavailable.append(f"qgis_render_bridge 不可导入: {exc}")
        for warning in report.warnings:
            unavailable.append(f"loader: {warning}")
        if not proj.ok:
            degraded.append(
                f"proj.db 不可达（{proj.note or proj.source or '未找到'}）"
            )
        status = QgisRuntimeStatus(
            qgis_available=False,
            recipe=report.recipe.value,
            proj_available=proj.ok,
            proj_db_path=str(proj.proj_db) if proj.proj_db else "",
            proj_source=proj.source,
            degraded_reasons=tuple(degraded),
            unavailable_reasons=tuple(unavailable),
        )
        _STATUS_CACHE = status
        return status

    bridge_version = str(getattr(bridge, "__version__", "unknown"))
    features = _manifest_features(bridge)
    snapping_available = bool(features.get("snapping_push"))
    topology_available = bool(features.get("snapping_topological_editing"))
    native_features = tuple(sorted(str(k) for k, v in features.items() if v))

    # Initialize the runtime (needs a QCoreApplication; the app and the test
    # suite always have one — a bare CLI probe degrades honestly).
    facts: dict[str, Any] = {}
    try:
        from PySide6.QtCore import QCoreApplication

        if QCoreApplication.instance() is None:
            raise RuntimeError("requires a QCoreApplication")
        from qgis_render_bridge import mapstack

        stack = mapstack.QgisMapStack()
        stack.initialize(display=True)
        try:
            probed = _probe_via_runtime_facts(stack)
            if probed is None:
                probed = _probe_via_canvas_roundtrip(stack)
            if probed is not None:
                facts.update(probed)
        finally:
            stack.shutdown()
    except Exception as exc:
        degraded.append(f"运行时初始化/探测失败: {exc}")

    crs_probe_map: dict[str, bool] = {
        str(k): bool(v) for k, v in (facts.get("crs_probes") or {}).items()
    }
    for authid in KEY_CRS_PROBES:
        crs_probe_map.setdefault(authid, False)
    canvas_crs_available = all(crs_probe_map.get(a, False) for a in KEY_CRS_PROBES)
    if not canvas_crs_available and "probe_error" not in facts:
        missing = [a for a in KEY_CRS_PROBES if not crs_probe_map.get(a)]
        degraded.append(
            "CRS 解析不完整（"
            + ", ".join(missing)
            + "）— proj 链路断裂，canvas_destination_crs 将返回空串"
        )
    transform_available = bool(facts.get("transform_available"))

    if not proj.ok:
        degraded.append(f"proj.db 不可达（{proj.note or '未找到'}）")

    # The bridge's own resolution is more authoritative than the Python-side
    # file lookup: report what the live proj library actually resolved.
    bridge_proj_db = str(facts.get("proj_db_path", "") or "")
    if facts.get("proj_db_reachable"):
        proj_db_path = bridge_proj_db or (str(proj.proj_db) if proj.proj_db else "")
        proj_source = proj.source or "bridge"
    else:
        proj_db_path = str(proj.proj_db) if proj.proj_db else ""
        proj_source = proj.source
        if bridge_proj_db:
            degraded.append(
                f"PROJ 解析的 proj.db 不可达: {bridge_proj_db}（CRS 将解析失败）"
            )

    status = QgisRuntimeStatus(
        qgis_available=True,
        qgis_version=str(facts.get("qgis_version", "")),
        bridge_version=bridge_version,
        recipe=report.recipe.value,
        prefix_path=str(facts.get("prefix_path", "")),
        proj_available=proj.ok or bool(facts.get("proj_db_reachable")),
        proj_version=str(facts.get("proj_version", "")),
        proj_db_path=proj_db_path,
        proj_source=proj_source,
        gdal_available=bool(facts.get("gdal_version")),
        gdal_version=str(facts.get("gdal_version", "")),
        gdal_data=str(facts.get("gdal_data", "")),
        provider_count=int(facts.get("provider_count", 0) or 0),
        providers=tuple(str(p) for p in (facts.get("providers") or [])),
        crs_probes=tuple(sorted(crs_probe_map.items())),
        canvas_crs_available=canvas_crs_available,
        transform_available=transform_available,
        svg_paths=tuple(str(p) for p in (facts.get("svg_paths") or [])),
        snapping_available=snapping_available,
        topology_available=topology_available,
        native_features=native_features,
        degraded_reasons=tuple(degraded),
        unavailable_reasons=tuple(unavailable),
        facts=facts,
    )
    _STATUS_CACHE = status
    return status
