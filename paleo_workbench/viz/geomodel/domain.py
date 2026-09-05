"""Geological 3D domain model V2 (authority layer).

Scientific objects are the **single source of truth** for the 3D geological
workspace; scene nodes are disposable rebuildable views of them (see
``scene_adapter.py``). Identity, CRS / unit / domain metadata, provenance and
QC live here — never in the renderer.

Serialization contract (``to_meta`` / ``from_meta``):

* metadata (identity, provenance, CRS, units, stats, display hints) is
  JSON-safe and round-trips exactly — this is what the project file stores;
* vertex / grid arrays are **not** serialized here. Bulk geometry is persisted
  through Catalog versioned artifacts (ADR-03); ``demo=True`` objects are
  explicitly non-persistent.

Every concrete object carries:

* ``object_id``   — stable, unique within the assembly (``<kind>:<slug>``);
* ``name``        — display name (not an identity);
* ``crs``         — coordinate reference string of the geometry (may be
  ``"unknown"`` but must be stated);
* provenance      — ``source_kind`` (catalog / derived / imported / demo),
  ``source_version_ids`` (Catalog DataVersion ids), ``created_from`` note.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Sequence
import re
import threading

import numpy as np

__all__ = [
    "DomainError",
    "DomainObject",
    "WellTrajectory",
    "HorizonSurface",
    "FaultSurface",
    "StratigraphicVolume",
    "TunnelSection",
    "MeasurementRecord",
    "ModelAssembly",
]

_SLUG_RE = re.compile(r"[^a-z0-9_.-]+")


class DomainError(ValueError):
    """Invalid domain object construction (fail-loud, no silent repair)."""


def _slugify(text: str, fallback: str) -> str:
    slug = _SLUG_RE.sub("-", str(text).strip().lower()).strip("-.")
    return slug or fallback


def _clean_ids(ids: Sequence[str] | None) -> tuple[str, ...]:
    return tuple(str(i) for i in (ids or ()))


@dataclass(frozen=True)
class Provenance:
    """Where an object came from and what it was built from."""

    source_kind: str = "derived"  # catalog | derived | imported | demo
    source_version_ids: tuple[str, ...] = ()
    created_from: str = ""
    demo: bool = False

    def to_meta(self) -> dict[str, Any]:
        return {
            "source_kind": self.source_kind,
            "source_version_ids": list(self.source_version_ids),
            "created_from": self.created_from,
            "demo": self.demo,
        }

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any] | None) -> "Provenance":
        meta = meta or {}
        return cls(
            source_kind=str(meta.get("source_kind", "derived")),
            source_version_ids=_clean_ids(meta.get("source_version_ids")),
            created_from=str(meta.get("created_from", "")),
            demo=bool(meta.get("demo", False)),
        )


@dataclass(frozen=True)
class DomainObject:
    """Common identity / metadata header of every geological object.

    Frozen: geometry-bearing subclasses treat their arrays as immutable by
    convention; mutations produce new objects via ``dataclasses.replace`` so
    a scene adapter can diff by identity + version counter.
    """

    object_id: str
    name: str
    crs: str = "unknown"
    vertical_domain: str = "depth"  # depth | twt | tvdss
    unit: str = "m"
    provenance: Provenance = field(default_factory=Provenance)
    version: int = 1

    def __post_init__(self) -> None:
        if not self.object_id or ":" not in self.object_id:
            raise DomainError(
                f"object_id must be '<kind>:<slug>', got {self.object_id!r}"
            )
        kind = self.object_id.split(":", 1)[0]
        if not self.name:
            raise DomainError(f"{self.object_id}: name must be non-empty")

    def meta(self) -> dict[str, Any]:
        raise NotImplementedError

    @classmethod
    def kind(cls) -> str:
        raise NotImplementedError


def _require_finite(name: str, arr: np.ndarray) -> None:
    if arr.size and not np.all(np.isfinite(arr)):
        raise DomainError(f"{name}: array contains non-finite values")


# ---------------------------------------------------------------------------
# WellTrajectory
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WellTrajectory(DomainObject):
    """A 3D well trajectory with its own CRS/unit contract.

    ``stations`` is an (N, 4) float array of ``[md, x, y, z]`` rows in the
    well's own units (``unit`` for lengths; z shares the horizontal unit
    unless ``z_unit`` is given). Wells with only a head + total depth are
    represented with ``representation="simplified_vertical"`` and exactly two
    stations (head, TD straight down) — never presented as a real measured
    trajectory.
    """

    stations: np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))
    representation: str = "measured"  # measured | simplified_vertical
    z_unit: str | None = None
    well_asset_id: str = ""  # Catalog asset reference, when cataloged
    formation_tops: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.object_id.startswith("well:"):
            raise DomainError(f"well object_id must start with 'well:'")
        st = np.asarray(self.stations, dtype=np.float64)
        if st.ndim != 2 or (st.size and st.shape[1] != 4):
            raise DomainError(
                f"{self.object_id}: stations must be (N, 4) [md,x,y,z], got {st.shape}"
            )
        if st.size:
            _require_finite(f"{self.object_id}.stations", st)
        if self.representation not in ("measured", "simplified_vertical"):
            raise DomainError(
                f"{self.object_id}: unknown representation {self.representation!r}"
            )
        if self.representation == "measured" and st.shape[0] >= 2:
            md = st[:, 0]
            if np.any(np.diff(md) <= 0):
                raise DomainError(
                    f"{self.object_id}: measured stations need strictly "
                    "increasing MD (QC rejects duplicates/non-monotonic input)"
                )

    @classmethod
    def kind(cls) -> str:
        return "well"

    def meta(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "name": self.name,
            "crs": self.crs,
            "vertical_domain": self.vertical_domain,
            "unit": self.unit,
            "z_unit": self.z_unit or self.unit,
            "representation": self.representation,
            "well_asset_id": self.well_asset_id,
            "formation_tops": [list(t) for t in self.formation_tops],
            "provenance": self.provenance.to_meta(),
            "version": self.version,
            "stats": geometry_stats(self),
        }

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any]) -> "WellTrajectory":
        return cls(
            object_id=str(meta["object_id"]),
            name=str(meta["name"]),
            crs=str(meta.get("crs", "unknown")),
            vertical_domain=str(meta.get("vertical_domain", "depth")),
            unit=str(meta.get("unit", "m")),
            z_unit=meta.get("z_unit"),
            representation=str(meta.get("representation", "measured")),
            well_asset_id=str(meta.get("well_asset_id", "")),
            formation_tops=tuple(
                (str(t[0]), float(t[1])) for t in meta.get("formation_tops", ())
            ),
            provenance=Provenance.from_meta(meta.get("provenance")),
            version=int(meta.get("version", 1)),
        )


# ---------------------------------------------------------------------------
# HorizonSurface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HorizonSurface(DomainObject):
    """A structurally-gridded surface: regular XY lattice, z per node.

    ``z_grid`` is (nI, nX); NaN marks holes (no interpolation across large
    gaps is ever fabricated by the builders). ``origin`` = (x0, y0) world
    coordinates of node [0, 0]; ``spacing`` = (dy, dx) lattice steps.
    """

    z_grid: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))
    origin: tuple[float, float] = (0.0, 0.0)
    spacing: tuple[float, float] = (1.0, 1.0)
    grid_crs: str = ""  # when the lattice is il/xl in a survey grid
    horizon_asset_id: str = ""
    confidence: np.ndarray | None = None  # (nI, nX) 0..1, same holes
    attributes: tuple[tuple[str, np.ndarray], ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.object_id.startswith("horizon:"):
            raise DomainError("horizon object_id must start with 'horizon:'")
        g = np.asarray(self.z_grid, dtype=np.float64)
        if g.ndim != 2:
            raise DomainError(f"{self.object_id}: z_grid must be 2-D")
        _require_finite_structured(f"{self.object_id}.z_grid", g)
        if self.confidence is not None:
            c = np.asarray(self.confidence, dtype=np.float64)
            if c.shape != g.shape:
                raise DomainError(
                    f"{self.object_id}: confidence shape {c.shape} != grid {g.shape}"
                )
        for attr_name, arr in self.attributes:
            a = np.asarray(arr, dtype=np.float64)
            if a.shape != g.shape:
                raise DomainError(
                    f"{self.object_id}: attribute {attr_name!r} shape {a.shape} != grid {g.shape}"
                )

    @classmethod
    def kind(cls) -> str:
        return "horizon"

    def meta(self) -> dict[str, Any]:
        g = np.asarray(self.z_grid, dtype=np.float64)
        finite = np.isfinite(g)
        return {
            "object_id": self.object_id,
            "name": self.name,
            "crs": self.crs,
            "grid_crs": self.grid_crs,
            "vertical_domain": self.vertical_domain,
            "unit": self.unit,
            "origin": list(self.origin),
            "spacing": list(self.spacing),
            "shape": list(g.shape),
            "horizon_asset_id": self.horizon_asset_id,
            "attribute_names": [n for n, _ in self.attributes],
            "provenance": self.provenance.to_meta(),
            "version": self.version,
            "stats": geometry_stats(self),
            "stats_extra": {
                "node_count": int(g.size),
                "nan_fraction": float(1.0 - finite.mean()) if g.size else 0.0,
            },
        }

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any]) -> "HorizonSurface":
        return cls(
            object_id=str(meta["object_id"]),
            name=str(meta["name"]),
            crs=str(meta.get("crs", "unknown")),
            grid_crs=str(meta.get("grid_crs", "")),
            vertical_domain=str(meta.get("vertical_domain", "depth")),
            unit=str(meta.get("unit", "m")),
            origin=tuple(float(v) for v in meta.get("origin", (0.0, 0.0))),
            spacing=tuple(float(v) for v in meta.get("spacing", (1.0, 1.0))),
            horizon_asset_id=str(meta.get("horizon_asset_id", "")),
            provenance=Provenance.from_meta(meta.get("provenance")),
            version=int(meta.get("version", 1)),
            # z_grid itself arrives from the Catalog artifact loader
        )


def _require_finite_structured(name: str, arr: np.ndarray) -> None:
    """Structured grids may carry NaN holes; other non-finites are bugs."""
    if arr.size:
        bad = ~np.isfinite(arr) & ~np.isnan(arr)
        if np.any(bad):
            raise DomainError(f"{name}: contains +/-inf (NaN is the only allowed hole)")


# ---------------------------------------------------------------------------
# FaultSurface
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FaultSurface(DomainObject):
    """A fault as an explicit triangulated mesh or 2.5D curtain.

    ``representation`` must be stated honestly:

    * ``"triangulated_3d"`` — a real 3-D surface (verts/faces);
    * ``"curtain_2p5d"``   — a vertical curtain swept from a 2-D trace
      (map polyline × [z_top, z_bottom]); displayed and exported as the
      curtain it is, never as a mapped 3-D fault surface.

    ``strike_dip`` (degrees, right-hand rule) only when it has a source;
    ``None`` otherwise.
    """

    verts: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    faces: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.int64))
    representation: str = "triangulated_3d"
    trace_xy: np.ndarray | None = None  # source 2-D trace for curtains
    z_extent: tuple[float, float] | None = None  # curtain top/bottom
    throw_m: float | None = None
    strike_dip: tuple[float, float] | None = None
    fault_asset_id: str = ""
    intersects_horizons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.object_id.startswith("fault:"):
            raise DomainError("fault object_id must start with 'fault:'")
        v = np.asarray(self.verts, dtype=np.float64)
        f = np.asarray(self.faces, dtype=np.int64)
        if v.ndim != 2 or (v.size and v.shape[1] != 3):
            raise DomainError(f"{self.object_id}: verts must be (N, 3)")
        _require_finite(f"{self.object_id}.verts", v)
        if f.size:
            if f.ndim != 2 or f.shape[1] != 3:
                raise DomainError(f"{self.object_id}: faces must be (M, 3)")
            if f.min() < 0 or f.max() >= max(len(v), 1):
                raise DomainError(f"{self.object_id}: face indices out of range")
        if self.representation not in ("triangulated_3d", "curtain_2p5d"):
            raise DomainError(
                f"{self.object_id}: unknown representation {self.representation!r}"
            )
        if self.representation == "curtain_2p5d" and self.z_extent is None:
            raise DomainError(
                f"{self.object_id}: curtain representation requires z_extent"
            )

    @classmethod
    def kind(cls) -> str:
        return "fault"

    def meta(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "name": self.name,
            "crs": self.crs,
            "vertical_domain": self.vertical_domain,
            "unit": self.unit,
            "representation": self.representation,
            "z_extent": list(self.z_extent) if self.z_extent else None,
            "throw_m": self.throw_m,
            "strike_dip": list(self.strike_dip) if self.strike_dip else None,
            "fault_asset_id": self.fault_asset_id,
            "intersects_horizons": list(self.intersects_horizons),
            "provenance": self.provenance.to_meta(),
            "version": self.version,
            "stats": geometry_stats(self),
        }

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any]) -> "FaultSurface":
        zd = meta.get("z_extent")
        sd = meta.get("strike_dip")
        return cls(
            object_id=str(meta["object_id"]),
            name=str(meta["name"]),
            crs=str(meta.get("crs", "unknown")),
            vertical_domain=str(meta.get("vertical_domain", "depth")),
            unit=str(meta.get("unit", "m")),
            representation=str(meta.get("representation", "triangulated_3d")),
            z_extent=tuple(float(v) for v in zd) if zd else None,
            throw_m=meta.get("throw_m"),
            strike_dip=tuple(float(v) for v in sd) if sd else None,
            fault_asset_id=str(meta.get("fault_asset_id", "")),
            intersects_horizons=_clean_ids(meta.get("intersects_horizons")),
            provenance=Provenance.from_meta(meta.get("provenance")),
            version=int(meta.get("version", 1)),
        )


# ---------------------------------------------------------------------------
# StratigraphicVolume
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StratigraphicVolume(DomainObject):
    """A closed geologic volume between a top and a base surface.

    ``verts``/``faces`` form the **closed display shell** (top + base + side
    wall, per ``build_volume_shell``). ``top_id``/``base_id`` reference the
    HorizonSurface objects it was built from; ``boundary`` is the (M, 2)
    closed world-XY polygon closing the sides. ``quality`` mirrors the QC
    summary at build time (see qc.py).
    """

    verts: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    faces: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), dtype=np.int64))
    top_id: str = ""
    base_id: str = ""
    boundary: np.ndarray | None = None
    formation: str = ""
    facies: np.ndarray | None = None  # per-vertex categorical id (or None)
    properties: tuple[tuple[str, np.ndarray], ...] = ()
    cell_mesh: dict[str, np.ndarray] | None = None  # computational hex mesh
    quality: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.object_id.startswith("volume:"):
            raise DomainError("volume object_id must start with 'volume:'")
        v = np.asarray(self.verts, dtype=np.float64)
        f = np.asarray(self.faces, dtype=np.int64)
        if v.ndim != 2 or (v.size and v.shape[1] != 3):
            raise DomainError(f"{self.object_id}: verts must be (N, 3)")
        _require_finite(f"{self.object_id}.verts", v)
        if f.size:
            if f.ndim != 2 or f.shape[1] != 3:
                raise DomainError(f"{self.object_id}: faces must be (M, 3)")
            if f.min() < 0 or f.max() >= max(len(v), 1):
                raise DomainError(f"{self.object_id}: face indices out of range")
        if self.facies is not None and len(np.asarray(self.facies)) != len(v):
            raise DomainError(f"{self.object_id}: facies length must match verts")
        for pname, arr in self.properties:
            if len(np.asarray(arr)) != len(v):
                raise DomainError(
                    f"{self.object_id}: property {pname!r} length must match verts"
                )

    @classmethod
    def kind(cls) -> str:
        return "volume"

    def meta(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "name": self.name,
            "crs": self.crs,
            "vertical_domain": self.vertical_domain,
            "unit": self.unit,
            "top_id": self.top_id,
            "base_id": self.base_id,
            "formation": self.formation,
            "property_names": [n for n, _ in self.properties],
            "has_cell_mesh": self.cell_mesh is not None,
            "provenance": self.provenance.to_meta(),
            "version": self.version,
            "stats": geometry_stats(self),
            "quality": dict(self.quality),
        }

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any]) -> "StratigraphicVolume":
        return cls(
            object_id=str(meta["object_id"]),
            name=str(meta["name"]),
            crs=str(meta.get("crs", "unknown")),
            vertical_domain=str(meta.get("vertical_domain", "depth")),
            unit=str(meta.get("unit", "m")),
            top_id=str(meta.get("top_id", "")),
            base_id=str(meta.get("base_id", "")),
            formation=str(meta.get("formation", "")),
            provenance=Provenance.from_meta(meta.get("provenance")),
            version=int(meta.get("version", 1)),
            quality=dict(meta.get("quality", {})),
        )


# ---------------------------------------------------------------------------
# TunnelSection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TunnelSection(DomainObject):
    """A tunnel / adt as a swept tube along a 3-D path."""

    path: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    radius: float = 3.0

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.object_id.startswith("tunnel:"):
            raise DomainError("tunnel object_id must start with 'tunnel:'")
        p = np.asarray(self.path, dtype=np.float64)
        if p.ndim != 2 or (p.size and p.shape[1] != 3):
            raise DomainError(f"{self.object_id}: path must be (N, 3)")
        _require_finite(f"{self.object_id}.path", p)
        if not (self.radius > 0.0):
            raise DomainError(f"{self.object_id}: radius must be positive")

    @classmethod
    def kind(cls) -> str:
        return "tunnel"

    def meta(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "name": self.name,
            "crs": self.crs,
            "vertical_domain": self.vertical_domain,
            "unit": self.unit,
            "radius": self.radius,
            "provenance": self.provenance.to_meta(),
            "version": self.version,
            "stats": geometry_stats(self),
        }

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any]) -> "TunnelSection":
        return cls(
            object_id=str(meta["object_id"]),
            name=str(meta["name"]),
            crs=str(meta.get("crs", "unknown")),
            vertical_domain=str(meta.get("vertical_domain", "depth")),
            unit=str(meta.get("unit", "m")),
            radius=float(meta.get("radius", 3.0)),
            provenance=Provenance.from_meta(meta.get("provenance")),
            version=int(meta.get("version", 1)),
        )


# ---------------------------------------------------------------------------
# MeasurementRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MeasurementRecord(DomainObject):
    """A saved measurement (point / distance / polyline / vert-diff / thickness).

    ``points`` are world XYZ in the record's CRS/unit; ``result`` is the
    scalar (or per-leg array) value in ``unit``. Pixel distances never enter
    here — creation happens in domain space only.
    """

    measurement_kind: str = "distance"  # point | distance | polyline | vertical_difference | thickness | plane_orientation
    points: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    result: float | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.object_id.startswith("measure:"):
            raise DomainError("measurement object_id must start with 'measure:'")
        allowed = {
            "point",
            "distance",
            "polyline",
            "vertical_difference",
            "thickness",
            "plane_orientation",
        }
        if self.measurement_kind not in allowed:
            raise DomainError(
                f"{self.object_id}: unknown measurement kind {self.measurement_kind!r}"
            )
        p = np.asarray(self.points, dtype=np.float64)
        if p.ndim != 2 or (p.size and p.shape[1] != 3):
            raise DomainError(f"{self.object_id}: points must be (N, 3)")
        _require_finite(f"{self.object_id}.points", p)

    @classmethod
    def kind(cls) -> str:
        return "measure"

    def meta(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "name": self.name,
            "crs": self.crs,
            "vertical_domain": self.vertical_domain,
            "unit": self.unit,
            "measurement_kind": self.measurement_kind,
            # Measurements are lightweight: the points themselves persist.
            "points": [[float(c) for c in row] for row in np.asarray(self.points)],
            "result": self.result,
            "extra": dict(self.extra),
            "provenance": self.provenance.to_meta(),
            "version": self.version,
        }

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any]) -> "MeasurementRecord":
        return cls(
            object_id=str(meta["object_id"]),
            name=str(meta["name"]),
            crs=str(meta.get("crs", "unknown")),
            vertical_domain=str(meta.get("vertical_domain", "depth")),
            unit=str(meta.get("unit", "m")),
            measurement_kind=str(meta.get("measurement_kind", "distance")),
            points=np.asarray(meta.get("points", []), dtype=np.float64),
            result=meta.get("result"),
            extra=dict(meta.get("extra", {})),
            provenance=Provenance.from_meta(meta.get("provenance")),
            version=int(meta.get("version", 1)),
        )


# ---------------------------------------------------------------------------
# ModelAssembly
# ---------------------------------------------------------------------------


class ModelAssembly:
    """Ordered, unique-id container of geological objects (the workspace).

    Not a dataclass: it owns mutation policy. All mutations go through
    ``add`` / ``remove`` / ``replace``; arrays of member objects are treated
    as immutable (mutate via ``replace`` + ``replace_object``). This is the
    authority a scene adapter rebuilds from — no scene/GPU state ever lands
    here.
    """

    _KIND_TO_CLS = {
        "well": WellTrajectory,
        "horizon": HorizonSurface,
        "fault": FaultSurface,
        "volume": StratigraphicVolume,
        "tunnel": TunnelSection,
        "measure": MeasurementRecord,
    }

    def __init__(self, name: str = "geo3d") -> None:
        self.name = name
        self._objects: dict[str, DomainObject] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()
        self.frame: str = "world"
        self.display: dict[str, dict[str, Any]] = {}  # object_id → display hints

    # -- queries ---------------------------------------------------------

    def __len__(self) -> int:
        return len(self._order)

    def __contains__(self, object_id: str) -> bool:
        return object_id in self._objects

    def objects(self, kind: str | None = None) -> list[DomainObject]:
        with self._lock:
            if kind is None:
                return [self._objects[i] for i in self._order]
            return [
                self._objects[i]
                for i in self._order
                if i.split(":", 1)[0] == kind
            ]

    def get(self, object_id: str) -> DomainObject | None:
        return self._objects.get(object_id)

    def ids(self, kind: str | None = None) -> list[str]:
        return [o.object_id for o in self.objects(kind)]

    # -- mutation --------------------------------------------------------

    def add(self, obj: DomainObject) -> DomainObject:
        cls = self._KIND_TO_CLS.get(obj.object_id.split(":", 1)[0])
        if cls is None or not isinstance(obj, cls):
            raise DomainError(f"unknown object kind for {obj.object_id!r}")
        with self._lock:
            if obj.object_id in self._objects:
                raise DomainError(
                    f"duplicate object_id {obj.object_id!r} — use replace()"
                )
            self._objects[obj.object_id] = obj
            self._order.append(obj.object_id)
        return obj

    def replace(self, obj: DomainObject) -> DomainObject:
        with self._lock:
            if obj.object_id not in self._objects:
                raise DomainError(f"unknown object_id {obj.object_id!r}")
            self._objects[obj.object_id] = obj
        return obj

    def remove(self, object_id: str) -> bool:
        with self._lock:
            if object_id not in self._objects:
                return False
            del self._objects[object_id]
            self._order.remove(object_id)
            self.display.pop(object_id, None)
        return True

    def clear(self, kind: str | None = None) -> int:
        with self._lock:
            doomed = [
                i
                for i in self._order
                if kind is None or i.split(":", 1)[0] == kind
            ]
            for i in doomed:
                del self._objects[i]
                self._order.remove(i)
                self.display.pop(i, None)
            return len(doomed)

    def bump_version(self, object_id: str) -> DomainObject:
        """Return the object with ``version`` incremented (immutably)."""
        obj = self._objects[object_id]
        bumped = replace(obj, version=obj.version + 1)
        return self.replace(bumped)

    # -- persistence -----------------------------------------------------

    def to_meta(self) -> dict[str, Any]:
        """Metadata-only snapshot (arrays excluded; ADR-03)."""
        with self._lock:
            return {
                "name": self.name,
                "frame": self.frame,
                "display": {
                    k: dict(v) for k, v in self.display.items()
                },
                "objects": [
                    self._objects[i].meta() for i in self._order
                ],
            }

    def apply_meta(self, meta: Mapping[str, Any]) -> list[str]:
        """Restore objects from a :meth:`to_meta` snapshot.

        Returns ids of objects that could not be restored (unknown kind /
        malformed entry) instead of raising — a project file must always
        open; broken entries are reported, not swallowed.
        """
        self.name = str(meta.get("name", self.name))
        self.frame = str(meta.get("frame", "world"))
        self.display = {
            str(k): dict(v) for k, v in meta.get("display", {}).items()
        }
        restored: list[str] = []
        for entry in meta.get("objects", ()):
            object_id = str(entry.get("object_id", ""))
            kind = object_id.split(":", 1)[0]
            cls = self._KIND_TO_CLS.get(kind)
            if cls is None:
                continue
            try:
                self.add(cls.from_meta(entry))
                restored.append(object_id)
            except (DomainError, KeyError, TypeError, ValueError):
                continue
        return restored


# ---------------------------------------------------------------------------
# shared stats
# ---------------------------------------------------------------------------


def geometry_stats(obj: DomainObject) -> dict[str, Any]:
    """Lightweight geometric summary used by inspectors and exports."""
    verts: np.ndarray | None = None
    if isinstance(obj, (WellTrajectory,)):
        verts = obj.stations[:, 1:4] if len(obj.stations) else None
    elif isinstance(obj, (FaultSurface, StratigraphicVolume)):
        verts = obj.verts if len(obj.verts) else None
    elif isinstance(obj, TunnelSection):
        verts = obj.path if len(obj.path) else None
    elif isinstance(obj, HorizonSurface):
        g = np.asarray(obj.z_grid, dtype=np.float64)
        if g.size:
            finite = g[np.isfinite(g)]
            verts = np.array(
                [
                    [obj.origin[0], obj.origin[1], float(finite.min())],
                    [
                        obj.origin[0] + (g.shape[1] - 1) * obj.spacing[1],
                        obj.origin[1] + (g.shape[0] - 1) * obj.spacing[0],
                        float(finite.max()),
                    ],
                ]
            )
    elif isinstance(obj, MeasurementRecord):
        verts = obj.points if len(obj.points) else None
    if verts is None or len(verts) == 0:
        return {"vertex_count": 0}
    return {
        "vertex_count": int(len(verts)),
        "bounds": [float(v) for v in verts.min(axis=0)]
        + [float(v) for v in verts.max(axis=0)],
    }
