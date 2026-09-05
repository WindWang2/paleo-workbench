"""Geo3D workspace controller — V5 page-side bridge (G9/G16/G17).

Owns the page's :class:`ModelAssembly` + :class:`GeologicalSceneAdapter`
and the workspace UI logic that stays out of the legacy page monolith:

* scene-tree section for geological objects (visibility → adapter);
* selection ↔ inspector ↔ :class:`SelectionContext` broadcast loop;
* QC panel data (severity ladder);
* measurement tool state machine (point/distance/polyline/vert/thickness);
* object clip planes driven by view-space axis controls (bounds-derived,
  not hardcoded);
* named camera view presets and workspace persistence.

The controller holds **no GL state**: everything renderable goes through the
adapter into engine scene objects, so project switch / viewport teardown are
provider-None no-ops by construction.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Sequence

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QTreeWidgetItem

from paleo_workbench import tokens
from paleo_workbench.viz.geomodel import measurements as geo_measure
from paleo_workbench.viz.geomodel.domain import (
    DomainError,
    DomainObject,
    FaultSurface,
    HorizonSurface,
    MeasurementRecord,
    ModelAssembly,
    StratigraphicVolume,
    TunnelSection,
    WellTrajectory,
)
from paleo_workbench.viz.geomodel.qc import (
    QCReport,
    qc_assembly,
    qc_object,
)
from paleo_workbench.viz.geomodel.scene_adapter import (
    GeologicalSceneAdapter,
    ObjectStyle,
)
from paleo_workbench.viz.geomodel.section import Plane, axis_plane

logger = logging.getLogger(__name__)

__all__ = ["Geo3DWorkspaceController", "GEO_TREE_ROOT_LABEL"]

GEO_TREE_ROOT_LABEL = "地质模型对象 (V5)"

_KIND_LABELS: tuple[tuple[str, str], ...] = (
    ("well", "井轨迹"),
    ("horizon", "层位面"),
    ("fault", "断层面"),
    ("volume", "地层体"),
    ("tunnel", "隧道"),
    ("measure", "测量"),
)

_MEASURE_MODES: dict[str, tuple[str, int]] = {
    # mode → (label, points needed to finish)
    "point": ("点坐标", 1),
    "distance": ("距离", 2),
    "polyline": ("折线长度", 3),
    "vertical_difference": ("高差", 2),
    "thickness": ("厚度", 1),
    "plane_orientation": ("产状", 3),
}


class Geo3DWorkspaceController(QObject):
    """Page-facing facade over the V5 geological workspace."""

    selection_changed = Signal(str)  # object_id ("" = cleared)
    qc_updated = Signal(object)  # QCReport
    measurements_changed = Signal()
    status_message = Signal(str)

    def __init__(
        self,
        widget_provider: Callable[[], Any | None],
        *,
        source_widget_id: str = "geo3d",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._widget_provider = widget_provider
        self.assembly = ModelAssembly("page-geo3d")
        self.adapter = GeologicalSceneAdapter(widget_provider)
        self.qc_report = QCReport()
        self._selected_id: str | None = None
        self._measure_mode: str | None = None
        self._measure_points: list[tuple[float, float, float]] = []
        # view state (persisted)
        self.clip_state: dict[str, Any] = {
            "x": {"enabled": False, "value": 0.5, "invert": False},
            "y": {"enabled": False, "value": 0.5, "invert": False},
            "z": {"enabled": False, "value": 0.5, "invert": False},
        }
        self.view_presets: dict[str, dict[str, float]] = {}
        self.camera: dict[str, float] = {}
        self.source_widget_id = source_widget_id
        self._last_bounds: tuple[np.ndarray, np.ndarray] | None = None
        # injected by the host page
        self.publish_selection: Callable[[str], None] | None = None

    # ------------------------------------------------------------------
    # object management
    # ------------------------------------------------------------------

    def add_object(self, obj: DomainObject) -> DomainObject:
        """Add (or replace) a domain object, resync the scene and QC."""
        if obj.object_id in self.assembly:
            self.assembly.replace(obj)
        else:
            try:
                self.assembly.add(obj)
            except DomainError as exc:
                self.status_message.emit(f"对象被拒绝: {exc}")
                return obj
        self.sync_scene()
        self.refresh_qc()
        return obj

    def remove_object(self, object_id: str) -> bool:
        removed = self.assembly.remove(object_id)
        if removed:
            if self._selected_id == object_id:
                self._selected_id = None
            self.sync_scene()
            self.refresh_qc()
        return removed

    def clear(self, kind: str | None = None) -> int:
        n = self.assembly.clear(kind)
        if n:
            self.sync_scene()
            self.refresh_qc()
        return n

    def reset(self) -> None:
        """Drop every domain object + scene object (project switch)."""
        self.assembly = ModelAssembly("page-geo3d")
        self.adapter.reset()
        self.qc_report = QCReport()
        self._selected_id = None
        self._measure_mode = None
        self._measure_points = []
        self.refresh_qc()

    def set_visibility(self, object_id: str, visible: bool) -> None:
        self.adapter.set_visibility(object_id, visible)

    def visibility(self, object_id: str) -> bool:
        return self.adapter.visibility(object_id)

    def set_opacity(self, object_id: str, opacity: float) -> None:
        self.adapter.set_opacity(object_id, opacity)

    def sync_scene(self) -> None:
        report = self.adapter.sync(self.assembly)
        if len(report):
            logger.debug("geo3d scene sync: %s", report)

    # ------------------------------------------------------------------
    # demo modeling ingestion (honest demo provenance)
    # ------------------------------------------------------------------

    def ingest_demo_result(self, result: dict) -> dict:
        """Convert a legacy GeologicalModelingWorker result into domain
        objects with explicit demo provenance (never real-data impersonation).

        Returns a summary dict {wells, tunnels, faults}.
        """
        from paleo_workbench.viz.geomodel.domain import Provenance

        prov = Provenance(
            source_kind="demo",
            demo=True,
            created_from=str(result.get("source", "synthetic/demo")),
        )
        counts = {"wells": 0, "tunnels": 0, "faults": 0}
        for bh in result.get("bh_raw", []) or []:
            try:
                tops = tuple(
                    (str(layer.get("lithology", "Layer")), float(layer.get("top", 0.0)))
                    for layer in (bh.get("layers") or [])
                    if isinstance(layer, dict)
                )
                well = geo_well_from_head(
                    str(bh.get("name", f"well-{counts['wells']}")),
                    float(bh.get("x", 0.0)),
                    float(bh.get("y", 0.0)),
                    float(bh.get("td", 0.0) or 0.0),
                    formation_tops=tops,
                    provenance=prov,
                )
                self.add_object(well)
                counts["wells"] += 1
            except (DomainError, TypeError, ValueError):
                logger.debug("demo well ingest failed", exc_info=True)
        for tn in result.get("tunnels_raw", []) or []:
            try:
                path = np.asarray(tn["path"], dtype=np.float64)
                self.add_object(
                    TunnelSection(
                        object_id=f"tunnel:{_slug(str(tn.get('name', f'tunnel-{counts["tunnels"]}')))}",
                        name=str(tn.get("name", "tunnel")),
                        path=path,
                        crs="demo",
                        provenance=prov,
                    )
                )
                counts["tunnels"] += 1
            except (DomainError, KeyError, TypeError, ValueError):
                logger.debug("demo tunnel ingest failed", exc_info=True)
        for flt in result.get("faults_raw", []) or []:
            try:
                self.add_object(
                    demo_fault_curtain(
                        str(flt.get("name", f"fault-{counts['faults']}")),
                        normal=tuple(float(v) for v in flt.get("normal", (0, 0, 1))),
                        d=float(flt.get("d", 0.0)),
                        extent=tuple(float(v) for v in result.get("extent", (-80, 80, -80, 80))),
                        provenance=prov,
                    )
                )
                counts["faults"] += 1
            except (DomainError, TypeError, ValueError):
                logger.debug("demo fault ingest failed", exc_info=True)
        self.status_message.emit(
            f"演示建模对象已加入场景: 井 {counts['wells']} · 隧道 {counts['tunnels']} · 断层 {counts['faults']} (demo)"
        )
        return counts

    # ------------------------------------------------------------------
    # QC
    # ------------------------------------------------------------------

    def refresh_qc(self) -> QCReport:
        self.qc_report = qc_assembly(self.assembly)
        self.qc_updated.emit(self.qc_report)
        return self.qc_report

    def inspector_text(self, object_id: str | None = None) -> str:
        """Identity / provenance / geometry / QC summary for the inspector."""
        oid = object_id if object_id is not None else self._selected_id
        if not oid or oid not in self.assembly:
            return "未选中对象"
        obj = self.assembly.get(oid)
        meta = obj.meta()
        stats = meta.get("stats", {})
        lines = [
            f"<b>{_html_escape(str(meta.get('name', oid)))}</b>",
            f"ID: {_html_escape(oid)}",
            f"CRS: {_html_escape(str(meta.get('crs', 'unknown')))} · 域: "
            f"{_html_escape(str(meta.get('vertical_domain', 'depth')))} · 单位: "
            f"{_html_escape(str(meta.get('unit', 'm')))}",
        ]
        if oid.startswith("well:"):
            lines.append(f"表示: {_html_escape(str(meta.get('representation', '')))}")
        if oid.startswith("fault:"):
            lines.append(f"表示: {_html_escape(str(meta.get('representation', '')))}")
        prov = meta.get("provenance", {})
        lines.append(
            f"来源: {_html_escape(str(prov.get('source_kind', 'derived')))}{' (demo)' if prov.get('demo') else ''}"
        )
        versions = prov.get("source_version_ids") or []
        if versions:
            lines.append(f"源版本: {_html_escape(', '.join(str(v) for v in versions))}")
        if stats.get("vertex_count") is not None:
            lines.append(f"顶点数: {stats.get('vertex_count', 0)}")
        for key, label in (
            ("column_count", "柱数"),
            ("closed", "闭合"),
            ("min_thickness", "最小厚度"),
        ):
            if key in (meta.get("quality") or {}):
                lines.append(f"{label}: {meta['quality'][key]}")
        obj_report = qc_object(obj)
        worst = obj_report.worst()
        lines.append(f"QC: {worst}")
        for issue in obj_report.issues:
            if issue.severity in ("error", "blocker", "warning"):
                lines.append(
                    f"&nbsp;&nbsp;[{issue.severity}] {_html_escape(issue.code)}: "
                    f"{_html_escape(issue.message)}"
                )
        return "<br>".join(lines)

    # ------------------------------------------------------------------
    # selection
    # ------------------------------------------------------------------

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    def set_selected(self, object_id: str | None, *, broadcast: bool = True) -> None:
        self._selected_id = object_id
        self.adapter.set_selected(object_id)
        self.selection_changed.emit(object_id or "")
        if broadcast and object_id:
            if object_id.startswith("well:") and self.publish_selection is not None:
                obj = self.assembly.get(object_id)
                well_name = obj.name if obj is not None else object_id
                try:
                    self.publish_selection(str(well_name))
                except Exception:
                    logger.debug("selection broadcast failed", exc_info=True)

    # ------------------------------------------------------------------
    # measurement tool
    # ------------------------------------------------------------------

    @property
    def measure_mode(self) -> str | None:
        return self._measure_mode

    def set_measure_mode(self, mode: str | None) -> bool:
        if mode is not None and mode not in _MEASURE_MODES:
            return False
        self._measure_mode = mode
        self._measure_points = []
        if mode:
            label = _MEASURE_MODES[mode][0]
            self.status_message.emit(f"测量模式: {label}（在 3D 视图点击对象）")
        return True

    def handle_viewport_click(self, px: float, py: float) -> bool:
        """Pick filter hook: measurement or select-on-click. True = consumed."""
        pick = self.adapter.pick(px, py)
        if pick is None:
            if self._measure_mode is not None:
                self.status_message.emit("未命中可拾取对象")
                return True
            return False
        if self._measure_mode is None:
            self.set_selected(pick.object_id)
            obj = self.assembly.get(pick.object_id)
            if obj is not None:
                self.status_message.emit(f"选中: {obj.name}")
            return True
        kind = self._measure_mode
        self._measure_points.append(pick.domain_xyz)
        needed = _MEASURE_MODES[kind][1]
        if kind == "thickness":
            return self._finish_thickness_pick()
        if len(self._measure_points) >= needed:
            self._finish_measurement(kind)
        else:
            self.status_message.emit(
                f"测量: 已选 {len(self._measure_points)}/{needed} 点"
            )
        return True

    def _finish_thickness_pick(self) -> bool:
        (x, y, _z) = self._measure_points[-1]
        top = self._first_of_kind("horizon", name_hint=("top", "顶"))
        base = self._first_of_kind("horizon", name_hint=("base", "底"))
        if top is None or base is None:
            self.status_message.emit("厚度测量需要 top/base 两个层位面对象")
            self._measure_points = []
            return True
        try:
            record = geo_measure.thickness_at(x, y, top, base)
        except DomainError as exc:
            self.status_message.emit(f"测量失败: {exc}")
            self._measure_points = []
            return True
        self._emit_measurement(record)
        return True

    def _finish_measurement(self, kind: str) -> None:
        pts = self._measure_points
        self._measure_points = []
        crs = self._assembly_crs()
        try:
            if kind == "point":
                record = geo_measure.point_coordinate(pts[0], crs=crs)
            elif kind == "distance":
                record = geo_measure.distance(pts[0], pts[1], crs=crs)
            elif kind == "polyline":
                record = geo_measure.polyline_length(pts, crs=crs)
            elif kind == "vertical_difference":
                record = geo_measure.vertical_difference(pts[0], pts[1], crs=crs)
            elif kind == "plane_orientation":
                record = geo_measure.plane_orientation(pts, crs=crs)
            else:  # pragma: no cover
                return
        except DomainError as exc:
            self.status_message.emit(f"测量失败: {exc}")
            return
        self._emit_measurement(record)

    def _emit_measurement(self, record: MeasurementRecord) -> None:
        self.assembly.add(record)
        self.sync_scene()
        self.measurements_changed.emit()
        self.status_message.emit(
            f"{record.name}: {geo_measure.format_result(record)}"
        )

    def _first_of_kind(
        self, kind: str, *, name_hint: Sequence[str] = ()
    ) -> DomainObject | None:
        objs = self.assembly.objects(kind)
        if not objs:
            return None
        for hint in name_hint:
            for obj in objs:
                if hint.lower() in obj.name.lower():
                    return obj
        return objs[0]

    def _assembly_crs(self) -> str:
        for obj in self.assembly.objects():
            crs = getattr(obj, "crs", "unknown")
            if crs and crs not in ("unknown", "demo"):
                return str(crs)
        return "unknown"

    # ------------------------------------------------------------------
    # clipping (view state, bounds-derived — no ±80 hardcoding)
    # ------------------------------------------------------------------

    def _scene_bounds(self) -> tuple[np.ndarray, np.ndarray] | None:
        widget = self._widget_provider()
        if widget is None:
            return None
        b = widget.scene_objects_bounds(visible_only=False)
        if b is None:
            return None
        return np.asarray(b[0], dtype=np.float64), np.asarray(b[1], dtype=np.float64)

    def set_axis_clip(self, axis: str, enabled: bool, value01: float, invert: bool) -> None:
        """UI 0-1 slider → world plane over the current scene bounds."""
        if axis not in ("x", "y", "z"):
            return
        state = self.clip_state.setdefault(
            axis, {"enabled": False, "value": 0.5, "invert": False}
        )
        state.update(enabled=bool(enabled), value=float(value01), invert=bool(invert))
        self.apply_clip_state()

    def apply_clip_state(self) -> None:
        planes: list[tuple[float, float, float, float]] = []
        bounds = self._scene_bounds()
        for axis in ("x", "y", "z"):
            state = self.clip_state.get(axis) or {}
            if not state.get("enabled"):
                continue
            lo, hi = (
                (bounds[0][{"x": 0, "y": 1, "z": 2}[axis]],
                 bounds[1][{"x": 0, "y": 1, "z": 2}[axis]])
                if bounds is not None else (-80.0, 80.0)
            )
            value = lo + (hi - lo) * float(state.get("value", 0.5))
            plane = axis_plane(axis, float(value))
            planes.append(plane.as_clip_equation(invert=bool(state.get("invert"))))
        self.adapter.set_clip_planes(planes or None)

    def reset_clip(self) -> None:
        for axis in ("x", "y", "z"):
            self.clip_state[axis] = {
                "enabled": False, "value": 0.5, "invert": False,
            }
        self.apply_clip_state()

    # ------------------------------------------------------------------
    # camera / view presets
    # ------------------------------------------------------------------

    def capture_camera(self) -> dict[str, float]:
        widget = self._widget_provider()
        if widget is None or not hasattr(widget, "camera_pose"):
            return dict(self.camera)
        try:
            self.camera = dict(widget.camera_pose())
        except Exception:
            logger.debug("camera_pose read failed", exc_info=True)
        return dict(self.camera)

    def save_view_preset(self, name: str) -> bool:
        pose = self.capture_camera()
        if not pose.get("distance"):
            self.status_message.emit("视口未就绪，无法保存视图")
            return False
        self.view_presets[str(name)] = pose
        return True

    def restore_view_preset(self, name: str) -> bool:
        pose = self.view_presets.get(str(name))
        if not pose:
            return False
        widget = self._widget_provider()
        if widget is None:
            return False
        try:
            widget.set_camera_pose(
                distance=float(pose.get("distance", 250.0)),
                elevation=float(pose.get("elevation", 30.0)),
                azimuth=float(pose.get("azimuth", -45.0)),
            )
            return True
        except Exception:
            logger.debug("restore preset failed", exc_info=True)
            return False

    def fit_all(self) -> bool:
        widget = self._widget_provider()
        if widget is None:
            return False
        try:
            return bool(widget.fit_to_scene_objects())
        except Exception:
            logger.debug("fit_all failed", exc_info=True)
            return False

    def fit_selected(self) -> bool:
        widget = self._widget_provider()
        if widget is None or not self._selected_id:
            return False
        try:
            return bool(
                widget.fit_to_scene_objects(kinds=[self._selected_id.split(":", 1)[0]])
            )
        except Exception:
            return False

    # ------------------------------------------------------------------
    # tree integration
    # ------------------------------------------------------------------

    def rebuild_tree(self, tree: QTreeWidgetItem) -> None:
        """Populate ``tree`` (the 地质模型对象 root item) with per-object rows."""
        tree.takeChildren()
        self._tree_items: dict[str, QTreeWidgetItem] = {}
        by_kind: dict[str, list[DomainObject]] = {}
        for obj in self.assembly.objects():
            by_kind.setdefault(obj.object_id.split(":", 1)[0], []).append(obj)
        for kind, label in _KIND_LABELS:
            objs = by_kind.get(kind, [])
            if not objs:
                continue
            branch = QTreeWidgetItem(tree, [f"{label} ({len(objs)})"])
            branch.setFlags(branch.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            branch.setCheckState(0, Qt.Checked)
            for obj in objs:
                item = QTreeWidgetItem(branch, [self._object_label(obj)])
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                item.setData(0, Qt.ItemDataRole.UserRole, obj.object_id)
                visible = self.adapter.visibility(obj.object_id)
                item.setCheckState(0, Qt.Checked if visible else Qt.Unchecked)
                worst = self.qc_report.worst(obj.object_id) if self.qc_report.issues else "ok"
                if worst in ("error", "blocker"):
                    item.setForeground(
                        0, _severity_brush(tokens.ERROR_RED if worst == "blocker" else tokens.WARNING)
                    )
                self._tree_items[obj.object_id] = item
                if self._selected_id == obj.object_id:
                    item.setSelected(True)
        tree.setExpanded(True)

    def _object_label(self, obj: DomainObject) -> str:
        label = obj.name
        prov = obj.provenance
        if prov.demo:
            label += " (demo)"
        elif obj.object_id.startswith("well:") and obj.representation == "simplified_vertical":
            label += " (简化垂直)"
        elif obj.object_id.startswith("fault:") and obj.representation == "curtain_2p5d":
            label += " (2.5D 幕帘)"
        return label

    def on_tree_check(self, object_id: str, visible: bool) -> None:
        self.adapter.set_visibility(object_id, visible)

    # ------------------------------------------------------------------
    # persistence (G17)
    # ------------------------------------------------------------------

    def save_state(self, project: Any) -> dict:
        """Persist workspace state onto ``project.geo3d_workspace`` (view +
        reference state only; arrays live in the assembly/Catalog)."""
        from paleo_workbench.viz.geomodel.domain import MeasurementRecord

        section = getattr(project, "geo3d_workspace", None)
        if section is None:
            return {}
        meta_objects = []
        measurements = []
        for obj in self.assembly.objects():
            if isinstance(obj, MeasurementRecord):
                measurements.append(obj.meta())
                continue
            if obj.provenance.demo:
                continue  # demo objects are never persisted (honest)
            meta_objects.append(obj.meta())
        payload = {
            "objects": meta_objects,
            "measurements": measurements,
            "display": {
                oid: {
                    "visible": self.adapter.visibility(oid),
                    "opacity": self.adapter._opacity.get(oid, 1.0),
                }
                for oid in self.assembly.ids()
            },
            "clip": {
                axis: dict(state) for axis, state in self.clip_state.items()
            },
            "camera": self.capture_camera(),
            "views": [
                {"name": name, **pose}
                for name, pose in sorted(self.view_presets.items())
            ],
            "selected": self._selected_id or "",
        }
        try:
            section.replace(payload)
        except Exception:
            logger.debug("geo3d workspace persist failed", exc_info=True)
        return payload

    def restore_state(self, project: Any) -> list[str]:
        """Restore from ``project.geo3d_workspace``; returns restored ids.

        Missing entries degrade to informational status — a project must
        always open (ADR-03).
        """
        section = getattr(project, "geo3d_workspace", None)
        if section is None:
            return []
        payload = section.as_dict()
        if not payload:
            return []
        self.assembly = ModelAssembly("page-geo3d")
        restored = []
        from paleo_workbench.viz.geomodel.domain import MeasurementRecord

        for entry in payload.get("objects", []) or []:
            oid = str(entry.get("object_id", ""))
            kind = oid.split(":", 1)[0]
            cls = {
                "well": WellTrajectory,
                "horizon": HorizonSurface,
                "fault": FaultSurface,
                "volume": StratigraphicVolume,
                "tunnel": TunnelSection,
            }.get(kind)
            if cls is None:
                continue
            try:
                obj = cls.from_meta(entry)
                if not obj.provenance.demo:
                    self.assembly.add(obj)
                    restored.append(oid)
            except (DomainError, KeyError, TypeError, ValueError):
                logger.debug("restore failed for %s", oid, exc_info=True)
        for entry in payload.get("measurements", []) or []:
            try:
                record = MeasurementRecord.from_meta(entry)
                self.assembly.add(record)
                restored.append(record.object_id)
            except (DomainError, KeyError, TypeError, ValueError):
                logger.debug("measurement restore failed", exc_info=True)
        display = payload.get("display", {}) or {}
        for oid, state in display.items():
            self.adapter._visibility[oid] = bool(state.get("visible", True))
            self.adapter._opacity[oid] = float(state.get("opacity", 1.0))
        clip = payload.get("clip", {}) or {}
        for axis in ("x", "y", "z"):
            if axis in clip:
                self.clip_state[axis] = dict(clip[axis])
        self.camera = dict(payload.get("camera", {}) or {})
        self.view_presets = {
            str(v.get("name", f"view-{i}")): {
                "distance": float(v.get("distance", 250.0)),
                "elevation": float(v.get("elevation", 30.0)),
                "azimuth": float(v.get("azimuth", -45.0)),
            }
            for i, v in enumerate(payload.get("views", []) or [])
        }
        self.sync_scene()
        self.apply_clip_state()
        self.refresh_qc()
        return restored


# ---------------------------------------------------------------------------
# module-level domain construction helpers (page/demo ingest)
# ---------------------------------------------------------------------------


def geo_well_from_head(
    name: str,
    x: float,
    y: float,
    total_depth: float,
    *,
    formation_tops: Sequence[tuple[str, float]] = (),
    crs: str = "unknown",
    provenance=None,
) -> WellTrajectory:
    from paleo_workbench.viz.geomodel.builders import (
        build_simplified_vertical_well,
    )

    return build_simplified_vertical_well(
        name,
        (x, y, 0.0),
        total_depth,
        crs=crs,
        formation_tops=formation_tops,
        provenance=provenance,
    )


def demo_fault_curtain(
    name: str,
    *,
    normal: tuple[float, float, float],
    d: float,
    extent: tuple[float, float, float, float],
    provenance=None,
) -> FaultSurface:
    """Finite curtain cut of a demo fault plane over an XY extent.

    Demo-only (provenance carries demo=True): the plane is sampled where it
    crosses the extent box — a visualization cut, not mapped fault data.
    """
    from paleo_workbench.viz.geomodel.builders import build_fault_curtain_from_trace

    a, b, c = (float(v) for v in normal)
    x0, x1, y0, y1 = extent
    if abs(b) < 1e-9:
        b = 1e-9
    pts: list[tuple[float, float]] = []
    for x in np.linspace(x0, x1, 8):
        y = (d - a * x) / b
        if y0 - 1e-6 <= y <= y1 + 1e-6:
            pts.append((float(x), float(y)))
    if len(pts) < 2:
        for y in np.linspace(y0, y1, 8):
            x = (d - b * y) / max(abs(a), 1e-9) * (1 if a >= 0 else -1)
            if x0 - 1e-6 <= x <= x1 + 1e-6:
                pts.append((float(x), float(y)))
    if len(pts) < 2:
        pts = [(x0, y0), (x1, y1)]
    return build_fault_curtain_from_trace(
        name,
        pts,
        0.0,
        160.0,
        crs="demo",
        provenance=provenance,
    )


def _slug(text: str) -> str:
    import re

    slug = re.sub(r"[^a-z0-9_.-]+", "-", text.strip().lower()).strip("-.")
    return slug or "obj"


# ---------------------------------------------------------------------------
# small Qt helpers (kept local to avoid importing the page)
# ---------------------------------------------------------------------------


def _html_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _severity_brush(color: str):
    from PySide6.QtGui import QBrush, QColor

    return QBrush(QColor(color))
