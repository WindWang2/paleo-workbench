"""Scene adapter: the single bridge between the domain model and the
engine's named scene objects (G2).

Layering contract::

    ModelAssembly (authority, this repo)
        → GeologicalSceneAdapter (this module: transform + payload + diff)
            → WellSeismicJointWidget.add_scene_object (engine public API)
                → Renderer3D scene objects → GL items

* **Deterministic**: the same assembly state + view state produces the same
  scene objects; payloads are content-addressed by a version token so
  unchanged objects are never rebuilt (no per-frame Python geometry).
* **Renderer stays a view**: no domain state lives in the renderer; the
  adapter can rebuild everything from the assembly + mapping at any time.
* **Engine-space isolation**: the adapter owns the domain→render transform
  (``scene.world_to_render_xyz_array`` + ``widget.index_xyz_to_world``) and
  its inverse for picking; the engine never interprets CRS/units.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

from .domain import (
    DomainObject,
    FaultSurface,
    HorizonSurface,
    MeasurementRecord,
    ModelAssembly,
    StratigraphicVolume,
    TunnelSection,
    WellTrajectory,
)
from .builders import triangulate_heightfield

logger = logging.getLogger(__name__)

__all__ = ["ObjectStyle", "SceneSyncReport", "DomainPick", "GeologicalSceneAdapter"]

# display decimation ceiling per horizon axis (see _build_horizon)
_MAX_HORIZON_DIM = 512


@dataclass
class ObjectStyle:
    """View-state styling applied at payload build time."""

    color: tuple[float, float, float, float] = (0.85, 0.85, 0.9, 1.0)
    opacity: float = 1.0
    well_color: tuple[float, float, float, float] = (0.98, 0.75, 0.18, 1.0)
    well_width: float = 3.0
    horizon_color: tuple[float, float, float, float] = (0.98, 0.9, 0.3, 0.65)
    fault_color: tuple[float, float, float, float] = (0.9, 0.25, 0.25, 0.6)
    volume_color: tuple[float, float, float, float] = (0.35, 0.65, 0.9, 0.8)
    tunnel_color: tuple[float, float, float, float] = (0.7, 0.7, 0.75, 1.0)
    measurement_color: tuple[float, float, float, float] = (0.2, 0.95, 0.6, 1.0)
    selected_color: tuple[float, float, float, float] = (0.3, 1.0, 1.0, 1.0)
    label_color: tuple[float, float, float, float] = (1.0, 0.88, 0.28, 1.0)
    show_well_labels: bool = True


@dataclass
class SceneSyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    unchanged: int = 0

    def __len__(self) -> int:
        return len(self.added) + len(self.updated) + len(self.removed)

    def __str__(self) -> str:  # pragma: no cover
        return (
            f"+{len(self.added)} ~{len(self.updated)} "
            f"-{len(self.removed)} ={self.unchanged}"
        )


@dataclass(frozen=True)
class DomainPick:
    """A pick resolved back into domain space."""

    object_id: str
    kind: str
    domain_xyz: tuple[float, float, float]
    distance: float


class GeologicalSceneAdapter:
    """Syncs a :class:`ModelAssembly` into engine scene objects.

    ``widget_provider`` returns the live :class:`WellSeismicJointWidget`
    (or ``None`` while torn down / GL unavailable) — the adapter never
    caches the widget beyond a sync call, so project switches and viewport
    rebuilds degrade to no-ops instead of touching destroyed C++ objects.
    """

    def __init__(
        self,
        widget_provider: Callable[[], Any | None],
        *,
        styles: ObjectStyle | None = None,
    ) -> None:
        self._widget_provider = widget_provider
        self.styles = styles or ObjectStyle()
        # object_id → payload token at last sync (content address)
        self._synced_tokens: dict[str, tuple[Any, ...]] = {}
        # derived scene object names registered per domain object
        self._derived: dict[str, list[str]] = {}
        self._visibility: dict[str, bool] = {}
        self._opacity: dict[str, float] = {}
        self._clip_planes: list[tuple[float, float, float, float]] | None = None
        self._overlays: dict[str, list[str]] = {}
        self._selected: str | None = None

    # ------------------------------------------------------------------
    # public sync API
    # ------------------------------------------------------------------

    def sync(self, assembly: ModelAssembly) -> SceneSyncReport:
        """Diff the assembly against the last sync; rebuild only changes."""
        report = SceneSyncReport()
        widget = self._widget_provider()
        if widget is None:
            return report
        # Scene identity participates in every payload token: when the joint
        # scene is rebound (project switch / LOD reload / domain flip) the
        # domain→render transform changes, so payloads must rebuild even
        # though the domain objects themselves are unchanged.
        self._scene_token = self._current_scene_token(widget)
        live_ids = set(assembly.ids())
        # removals first (also drops derived names)
        for oid in list(self._synced_tokens):
            if oid not in live_ids:
                self._remove_tree(widget, oid)
                self._synced_tokens.pop(oid, None)
                report.removed.append(oid)
        for obj in assembly.objects():
            token = self._payload_token(obj)
            if token is None:
                # not renderable right now (e.g. arrays not yet loaded):
                # skip without destroying an existing payload
                continue
            prev = self._synced_tokens.get(obj.object_id)
            if prev == token:
                report.unchanged += 1
                continue
            derived = self._build_payloads(widget, obj, token)
            if derived is not None:
                if not derived and not _scene_objects_reachable(widget):
                    # GL-less viewport: nothing was actually built; do NOT
                    # record the token or a later renderer would never build
                    # this object (stale-cache lockout).
                    continue
                had_previous = obj.object_id in self._synced_tokens
                self._derived[obj.object_id] = derived
                self._synced_tokens[obj.object_id] = token
                if had_previous:
                    report.updated.append(obj.object_id)
                else:
                    report.added.append(obj.object_id)
        self._prune_state(live_ids)
        return report

    def display_state(self, object_id: str) -> dict:
        """Public snapshot of one object's view state (save path)."""
        return {
            "visible": self.visibility(object_id),
            "opacity": self._opacity.get(object_id, 1.0),
        }

    def restore_display(self, display: dict) -> None:
        """Public bulk restore of view state (clamped)."""
        for oid, state in (display or {}).items():
            oid = str(oid)
            self._visibility[oid] = bool(state.get("visible", True))
            self._opacity[oid] = float(
                min(max(float(state.get("opacity", 1.0)), 0.0), 1.0)
            )

    def reset(self) -> None:
        """Drop every scene object and all sync state (project switch)."""
        widget = self._widget_provider()
        if widget is not None:
            for oid in list(self._synced_tokens):
                self._remove_tree(widget, oid)
        self._synced_tokens.clear()
        self._derived.clear()
        self._visibility.clear()
        self._opacity.clear()
        self._overlays.clear()
        self._selected = None

    # ------------------------------------------------------------------
    # view-state API
    # ------------------------------------------------------------------

    def set_visibility(self, object_id: str, visible: bool) -> None:
        self._visibility[object_id] = bool(visible)
        widget = self._widget_provider()
        if widget is None:
            return
        for name in self._derived.get(object_id, []):
            widget.set_scene_object_visibility(name, visible)
        if visible and self._clip_planes:
            # set_clip_planes skips invisible objects; re-apply on reveal so
            # an object hidden during a clip edit is not left unclipped.
            for name in self._derived.get(object_id, []):
                widget.set_scene_object_clip_planes(name, self._clip_planes)

    def visibility(self, object_id: str) -> bool:
        return self._visibility.get(object_id, True)

    def set_opacity(self, object_id: str, opacity: float) -> None:
        self._opacity[object_id] = float(min(max(float(opacity), 0.0), 1.0))
        widget = self._widget_provider()
        if widget is None:
            return
        for name in self._derived.get(object_id, []):
            widget.set_scene_object_opacity(name, self._opacity[object_id])

    def set_selected(self, object_id: str | None) -> None:
        """Selection highlight = rebuild the affected objects' payloads."""
        prev = self._selected
        self._selected = object_id
        widget = self._widget_provider()
        if widget is None:
            return
        assembly_objects: list[str] = [
            oid for oid in (prev, object_id) if oid and oid in self._synced_tokens
        ]
        for oid in assembly_objects:
            token = self._synced_tokens.get(oid)
            # token carries selection state? no: selection is a view flag; the
            # highlight uses engine color update, not a payload rebuild.
            widget.set_scene_object_color(
                oid, self.styles.selected_color if oid == object_id else self._base_color(oid)
            )
            for name in self._derived.get(oid, []):
                if name != oid:
                    widget.set_scene_object_color(
                        name,
                        self.styles.selected_color
                        if oid == object_id
                        else self._base_color(name),
                    )

    @property
    def clip_planes(self):
        """Current object clip equations (read-only view for overlay owners)."""
        return self._clip_planes

    def register_overlay(self, key: str, names: Sequence[str]) -> None:
        """Track page-created analysis overlays so view state (clipping)
        applies to them exactly like domain-derived objects (ADR: the
        adapter owns every scene-object lifecycle concern)."""
        self._overlays[str(key)] = [str(n) for n in names]

    def remove_overlay(self, key: str) -> None:
        self._overlays.pop(str(key), None)

    def set_clip_planes(
        self, planes: Sequence[Sequence[float]] | None
    ) -> None:
        """Apply clip equations to every derived scene object and every
        registered overlay (view state)."""
        self._clip_planes = None if planes is None else [tuple(p) for p in planes]
        widget = self._widget_provider()
        if widget is None:
            return
        targets: list[tuple[str, list[str]]] = list(self._derived.items())
        for names in self._overlays.values():
            targets.append((("__overlay__"), names))
        for oid, names in targets:
            if oid != "__overlay__" and not self.visibility(oid):
                continue
            for name in names:
                widget.set_scene_object_clip_planes(name, self._clip_planes)

    # ------------------------------------------------------------------
    # picking
    # ------------------------------------------------------------------

    def pick(self, px: float, py: float, *, kinds: Iterable[str] | None = None) -> DomainPick | None:
        """Screen pick resolved back to domain coordinates (render→world)."""
        widget = self._widget_provider()
        if widget is None:
            return None
        try:
            scene = getattr(widget, "scene", None)
            scene = scene() if callable(scene) else scene
        except Exception:
            scene = None
        try:
            hit = widget.pick_scene_object(px, py, kinds=list(kinds) if kinds else None)
        except Exception:
            logger.debug("engine pick failed", exc_info=True)
            return None
        if hit is None:
            return None
        # engine world → render indices → domain world
        try:
            idx = widget.world_xyz_to_index(np.asarray(hit.point, dtype=np.float64))
            if scene is not None:
                world = scene.render_to_world_xyz_array(np.asarray(idx).reshape(1, 3))
                domain = tuple(float(v) for v in world[0])
            else:
                domain = tuple(float(v) for v in idx)
        except Exception:
            logger.debug("pick back-transform failed", exc_info=True)
            domain = (float("nan"),) * 3
        return DomainPick(
            object_id=hit.name.split("#", 1)[0],
            kind=hit.kind,
            domain_xyz=domain,
            distance=hit.distance,
        )

    # ------------------------------------------------------------------
    # payload builders (deterministic, content-addressed)
    # ------------------------------------------------------------------

    def _current_scene_token(self, widget) -> Any:
        """Identity of the active joint scene (None when unbound/destroyed).

        A torn-down scene object may raise on access (PySide RuntimeError);
        that degrades to ``None`` — the sync proceeds and payloads simply
        rebuild once a live scene returns (the token changes back).
        """
        try:
            scene = getattr(widget, "scene", None)
            scene = scene() if callable(scene) else scene
            domain = getattr(scene, "depth_transform", lambda: None)()
            return (id(scene), str(getattr(domain, "kind", "")))
        except Exception:
            return None

    def _payload_token(self, obj: DomainObject) -> tuple | None:
        """Content token deciding rebuild; ``None`` = not renderable now."""
        style = self._style_for(obj)
        scene_token = getattr(self, "_scene_token", None)
        if isinstance(obj, WellTrajectory):
            if len(obj.stations) == 0:
                return None
            return ("well", obj.version, len(obj.stations), obj.representation,
                    float(np.asarray(obj.stations).sum()), style.well_width,
                    self.styles.show_well_labels, self.visibility(obj.object_id),
                    scene_token)
        if isinstance(obj, HorizonSurface):
            g = np.asarray(obj.z_grid)
            if g.size == 0:
                return None
            return ("horizon", obj.version, g.shape, _finite_checksum(g),
                    obj.origin, obj.spacing, self.visibility(obj.object_id),
                    scene_token)
        if isinstance(obj, FaultSurface):
            if len(obj.verts) == 0:
                return None
            return ("fault", obj.version, len(obj.verts), len(obj.faces),
                    _finite_checksum(obj.verts), obj.representation,
                    self.visibility(obj.object_id), scene_token)
        if isinstance(obj, StratigraphicVolume):
            if len(obj.verts) == 0:
                return None
            return ("volume", obj.version, len(obj.verts), len(obj.faces),
                    _finite_checksum(obj.verts), self.visibility(obj.object_id),
                    scene_token)
        if isinstance(obj, TunnelSection):
            if len(obj.path) == 0:
                return None
            return ("tunnel", obj.version, len(obj.path), obj.radius,
                    _finite_checksum(obj.path), self.visibility(obj.object_id),
                    scene_token)
        if isinstance(obj, MeasurementRecord):
            if len(obj.points) == 0:
                return None
            return ("measure", obj.version, len(obj.points),
                    _finite_checksum(np.asarray(obj.points)), obj.measurement_kind,
                    self.visibility(obj.object_id), scene_token)
        return None

    def _build_payloads(self, widget, obj: DomainObject, token: tuple) -> list[str] | None:
        """Build and submit scene objects; returns derived names."""
        # remove previous derived objects first (replace semantics per name)
        self._remove_tree(widget, obj.object_id)
        builder = self._payload_builder(obj)
        if builder is None:
            return None
        try:
            return builder(widget, obj)
        except Exception:
            logger.warning(
                "payload build failed for %s", obj.object_id, exc_info=True
            )
            return None

    def _payload_builder(self, obj: DomainObject):
        if isinstance(obj, WellTrajectory):
            return self._build_well
        if isinstance(obj, HorizonSurface):
            return self._build_horizon
        if isinstance(obj, FaultSurface):
            return self._build_fault
        if isinstance(obj, StratigraphicVolume):
            return self._build_volume
        if isinstance(obj, TunnelSection):
            return self._build_tunnel
        if isinstance(obj, MeasurementRecord):
            return self._build_measurement
        return None

    def _to_render(self, widget, verts_world: np.ndarray) -> np.ndarray | None:
        """Domain world XYZ → engine GL world XYZ (both public engine APIs)."""
        scene = getattr(widget, "scene", None)
        scene = scene() if callable(scene) else scene
        pts = np.asarray(verts_world, dtype=np.float64)
        if pts.size == 0:
            return np.zeros((0, 3), dtype=np.float32)
        if pts.ndim == 1:
            pts = pts.reshape(1, 3)
        if scene is None:
            idx = pts
        else:
            idx = scene.world_to_render_xyz_array(pts)
        return np.asarray(widget.index_xyz_to_world(np.asarray(idx, dtype=np.float64)))

    def _build_well(self, widget, well: WellTrajectory) -> list[str]:
        style = self.styles
        selected = self._selected == well.object_id
        color = style.selected_color if selected else style.well_color
        st = np.asarray(well.stations, dtype=np.float64)
        render = self._to_render(widget, st[:, 1:4])
        names = []
        if render is not None and len(render) >= 2:
            widget.add_scene_object(
                well.object_id,
                verts=render.astype(np.float32),
                mode="lines",
                line_mode="line_strip",
                color=color,
                kind="well",
                pickable=True,
                pick_radius=2.0,  # engine units (~2 grid cells click tolerance)
                width=style.well_width,
                opacity=self._opacity.get(well.object_id, 1.0),
                clip_planes=self._clip_planes,
            )
            names.append(well.object_id)
        # head marker
        head_name = f"{well.object_id}#head"
        if render is not None and len(render):
            widget.add_scene_object(
                head_name,
                verts=render[:1].astype(np.float32),
                mode="points",
                color=color,
                kind="well",
                size=9.0,
                clip_planes=self._clip_planes,
            )
            names.append(head_name)
        if self.styles.show_well_labels:
            label_name = f"{well.object_id}#label"
            widget.add_scene_object(
                label_name,
                verts=render[:1].astype(np.float32),
                mode="text",
                text=well.name,
                color=color,
                kind="well",
                clip_planes=self._clip_planes,
            )
            names.append(label_name)
        return names

    def _build_horizon(self, widget, hor: HorizonSurface) -> list[str]:
        g = np.asarray(hor.z_grid, dtype=np.float64)
        origin = hor.origin
        spacing = hor.spacing
        # Deterministic decimation ceiling (G12): a horizon larger than
        # _MAX_HORIZON_DIM per axis is stride-thinned for display so a huge
        # interpretation grid cannot explode the scene; QC always audits the
        # full-resolution grid.
        nI, nX = g.shape
        sy = max(1, -(-max(nI - 1, 1) // _MAX_HORIZON_DIM))
        sx = max(1, -(-max(nX - 1, 1) // _MAX_HORIZON_DIM))
        if sy > 1 or sx > 1:
            g = g[::sy, ::sx]
            origin = (origin[0], origin[1])
            spacing = (spacing[0] * sy, spacing[1] * sx)
        verts, faces = triangulate_heightfield(
            g, origin=origin, spacing=spacing
        )
        if len(faces) == 0:
            return []
        render = self._to_render(widget, verts)
        if render is None or len(render) == 0:
            return []
        selected = self._selected == hor.object_id
        color = self.styles.selected_color if selected else self.styles.horizon_color
        widget.add_scene_object(
            hor.object_id,
            verts=render.astype(np.float32),
            faces=faces.astype(np.int64),
            mode="mesh",
            color=color,
            kind="horizon",
            pickable=True,
            opacity=self._opacity.get(hor.object_id, 1.0),
            clip_planes=self._clip_planes,
        )
        return [hor.object_id]

    def _build_fault(self, widget, fault: FaultSurface) -> list[str]:
        render = self._to_render(widget, np.asarray(fault.verts, dtype=np.float64))
        if render is None or len(render) == 0:
            return []
        selected = self._selected == fault.object_id
        color = self.styles.selected_color if selected else self.styles.fault_color
        widget.add_scene_object(
            fault.object_id,
            verts=render.astype(np.float32),
            faces=np.asarray(fault.faces, dtype=np.int64),
            mode="mesh",
            color=color,
            kind="fault",
            pickable=True,
            opacity=self._opacity.get(fault.object_id, 1.0),
            clip_planes=self._clip_planes,
        )
        return [fault.object_id]

    def _build_volume(self, widget, vol: StratigraphicVolume) -> list[str]:
        render = self._to_render(widget, np.asarray(vol.verts, dtype=np.float64))
        if render is None or len(render) == 0:
            return []
        selected = self._selected == vol.object_id
        color = self.styles.selected_color if selected else self.styles.volume_color
        face_colors = None
        if vol.facies is not None and not selected:
            face_colors = _facies_face_colors(
                np.asarray(vol.facies), np.asarray(vol.faces, dtype=np.int64)
            )
        kwargs = dict(
            verts=render.astype(np.float32),
            faces=np.asarray(vol.faces, dtype=np.int64),
            mode="mesh",
            kind="volume",
            pickable=True,
            opacity=self._opacity.get(vol.object_id, 1.0),
            clip_planes=self._clip_planes,
        )
        if face_colors is not None:
            kwargs["face_colors"] = face_colors
            kwargs["smooth"] = False
        else:
            kwargs["color"] = color
        widget.add_scene_object(vol.object_id, **kwargs)
        return [vol.object_id]

    def _build_tunnel(self, widget, tunnel: TunnelSection) -> list[str]:
        try:
            from geoviz import generate_tube_geometry  # public facade only
        except Exception:
            logger.warning("tube generator unavailable; tunnel skipped")
            return []
        path_render = self._to_render(widget, np.asarray(tunnel.path, dtype=np.float64))
        if path_render is None or len(path_render) < 2:
            return []
        verts, faces, colors = generate_tube_geometry(
            path_render, radius=tunnel.radius, color=self.styles.tunnel_color
        )
        if len(faces) == 0:
            return []
        widget.add_scene_object(
            tunnel.object_id,
            verts=np.asarray(verts, dtype=np.float32),
            faces=np.asarray(faces, dtype=np.int64),
            mode="mesh",
            kind="tunnel",
            pickable=False,
            opacity=self._opacity.get(tunnel.object_id, 1.0),
            clip_planes=self._clip_planes,
        )
        return [tunnel.object_id]

    def _build_measurement(self, widget, m: MeasurementRecord) -> list[str]:
        style = self.styles
        pts = np.asarray(m.points, dtype=np.float64)
        render = self._to_render(widget, pts)
        if render is None or len(render) == 0:
            return []
        names = []
        widget.add_scene_object(
            m.object_id,
            verts=render.astype(np.float32),
            mode="points",
            color=style.measurement_color,
            kind="measurement",
            size=8.0,
            clip_planes=self._clip_planes,
        )
        names.append(m.object_id)
        if len(render) >= 2:
            line_name = f"{m.object_id}#line"
            widget.add_scene_object(
                line_name,
                verts=render.astype(np.float32),
                mode="lines",
                line_mode="line_strip",
                color=style.measurement_color,
                kind="measurement",
                width=2.0,
                clip_planes=self._clip_planes,
            )
            names.append(line_name)
        label_name = f"{m.object_id}#label"
        from .measurements import format_result

        widget.add_scene_object(
            label_name,
            verts=render[-1:].astype(np.float32),
            mode="text",
            text=format_result(m),
            color=style.measurement_color,
            kind="measurement",
            clip_planes=self._clip_planes,
        )
        names.append(label_name)
        return names

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _style_for(self, obj: DomainObject) -> ObjectStyle:
        return self.styles

    def _base_color(self, name_or_id: str) -> tuple[float, float, float, float]:
        oid = name_or_id.split("#", 1)[0]
        kind = oid.split(":", 1)[0]
        s = self.styles
        return {
            "well": s.well_color,
            "horizon": s.horizon_color,
            "fault": s.fault_color,
            "volume": s.volume_color,
            "tunnel": s.tunnel_color,
            "measure": s.measurement_color,
        }.get(kind, s.color)

    def _had_previous(self, oid: str) -> bool:
        return oid in self._derived

    def _remove_tree(self, widget, oid: str) -> None:
        for name in self._derived.pop(oid, []):
            widget.remove_scene_object(name)

    def _prune_state(self, live_ids: set[str]) -> None:
        for oid in list(self._synced_tokens):
            if oid not in live_ids:
                self._synced_tokens.pop(oid, None)
                self._derived.pop(oid, None)
                self._visibility.pop(oid, None)
                self._opacity.pop(oid, None)


def oid_is_unchanged(previous: tuple | None, token: tuple) -> bool:
    return previous is not None and previous == token


def _scene_objects_reachable(widget) -> bool:
    """True when the widget can actually host scene objects right now.

    The joint widget keeps its pass-through API with ``_renderer is None``
    when GL is unavailable; recording stubs in tests have no ``_renderer``
    attribute at all and count as reachable.
    """
    if not hasattr(widget, "add_scene_object"):
        return False
    return "_renderer" not in vars(widget) or getattr(widget, "_renderer", None) is not None


def _finite_checksum(arr: np.ndarray) -> tuple:
    """Content address for float arrays: full-array digest with NaN holes
    canonicalized, so a NaN anywhere (legal in heightfields) neither
    destabilizes the token (sampled-value approach) nor hides changes.
    Deterministic across processes (hashlib, not salted ``hash``)."""
    a = np.ascontiguousarray(np.asarray(arr, dtype=np.float64))
    if a.size == 0:
        return (a.shape, "")
    canonical = np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0)
    digest = hashlib.blake2b(canonical.tobytes(), digest_size=12).hexdigest()
    return (a.shape, digest)


_FACIES_PALETTE = np.array(
    [
        [0.65, 0.81, 0.89, 1.0],   # 0 sand-ish
        [0.94, 0.90, 0.55, 1.0],   # 1 silt
        [0.74, 0.62, 0.42, 1.0],   # 2 shale-ish
        [0.55, 0.71, 0.49, 1.0],   # 3 carbonate-ish
        [0.80, 0.52, 0.45, 1.0],   # 4 coal/organic
        [0.62, 0.62, 0.72, 1.0],   # 5 volcaniclastic
        [0.85, 0.85, 0.85, 1.0],   # 6 other
        [0.45, 0.55, 0.70, 1.0],   # 7 other
    ],
    dtype=np.float32,
)


def _facies_face_colors(
    facies: np.ndarray, faces: np.ndarray
) -> np.ndarray:
    """Per-face RGBA for a per-vertex categorical facies array (G7)."""
    f = facies.astype(np.int64)
    palette = _FACIES_PALETTE
    f = np.clip(f, 0, len(palette) - 1)
    vert_colors = palette[f]
    return vert_colors[np.asarray(faces, dtype=np.int64)].mean(axis=1)
