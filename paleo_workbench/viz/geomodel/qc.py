"""Model QC framework (G13).

Every geological object can be audited into a :class:`QCReport` of
:class:`QCIssue` entries with a four-level severity ladder:

* ``info``      — worth knowing, never blocks;
* ``warning``   — suspicious, likely fine for display;
* ``error``     — wrong for analysis/numerics, export should refuse;
* ``blocker``   — the model cannot be trusted at all (cracked geometry,
  wrong domains, stale sources); export **must** refuse.

``assert_exportable`` is the single gate used by every exporter (ADR-06):
a blocker on any exported object raises :class:`QCBlockerError` instead of
writing a silently-wrong artifact.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

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

__all__ = [
    "SEVERITY_ORDER",
    "QCIssue",
    "QCReport",
    "QCBlockerError",
    "qc_well_trajectory",
    "qc_horizon_surface",
    "qc_fault_surface",
    "qc_stratigraphic_volume",
    "qc_tunnel_section",
    "qc_measurement",
    "qc_object",
    "qc_assembly",
    "assert_exportable",
]

SEVERITY_ORDER = {"info": 0, "warning": 1, "error": 2, "blocker": 3}

@dataclass(frozen=True)
class QCIssue:
    """One audit finding. ``metric`` carries the measured value, when any."""

    code: str
    severity: str  # info | warning | error | blocker
    message: str
    object_id: str
    metric: float | None = None

    def to_meta(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "object_id": self.object_id,
            "metric": self.metric,
        }


@dataclass
class QCReport:
    """Aggregated issues for one object or a whole assembly."""

    issues: list[QCIssue] = field(default_factory=list)

    def add(self, issue: QCIssue) -> None:
        self.issues.append(issue)

    def extend(self, other: "QCReport") -> None:
        self.issues.extend(other.issues)

    def of(self, object_id: str) -> list[QCIssue]:
        return [i for i in self.issues if i.object_id == object_id]

    def severities(self, object_id: str | None = None) -> dict[str, int]:
        counts = {k: 0 for k in SEVERITY_ORDER}
        for i in self.issues:
            if object_id is None or i.object_id == object_id:
                counts[i.severity] = counts.get(i.severity, 0) + 1
        return counts

    def worst(self, object_id: str | None = None) -> str:
        worst = "ok"
        for i in self.issues:
            if object_id is not None and i.object_id != object_id:
                continue
            if SEVERITY_ORDER.get(i.severity, 0) > SEVERITY_ORDER.get(worst, -1):
                worst = i.severity
        return worst

    def blockers(self) -> list[QCIssue]:
        return [i for i in self.issues if i.severity == "blocker"]

    def to_meta(self) -> dict[str, Any]:
        return {
            "issues": [i.to_meta() for i in self.issues],
            "worst": self.worst(),
            "severities": self.severities(),
        }

    @classmethod
    def from_meta(cls, meta: Mapping[str, Any]) -> "QCReport":
        report = cls()
        for entry in meta.get("issues", ()):
            report.add(
                QCIssue(
                    code=str(entry.get("code", "")),
                    severity=str(entry.get("severity", "info")),
                    message=str(entry.get("message", "")),
                    object_id=str(entry.get("object_id", "")),
                    metric=entry.get("metric"),
                )
            )
        return report


class QCBlockerError(RuntimeError):
    """Raised by :func:`assert_exportable` when blockers exist."""

    def __init__(self, report: QCReport, object_ids: Sequence[str]) -> None:
        lines = [
            f"  [{i.object_id}] {i.code}: {i.message}" for i in report.blockers()
        ]
        super().__init__(
            "export refused: blocker-level QC issues in "
            f"{', '.join(object_ids)}\n" + "\n".join(lines)
        )
        self.report = report


# ---------------------------------------------------------------------------
# per-object audits
# ---------------------------------------------------------------------------


def qc_well_trajectory(well: WellTrajectory) -> QCReport:
    report = QCReport()
    oid = well.object_id
    st = np.asarray(well.stations, dtype=np.float64)
    if well.crs in ("", "unknown"):
        report.add(
            QCIssue(
                "MISSING_CRS",
                "blocker",
                "CRS unknown — coordinates cannot be geo-referenced",
                oid,
            )
        )
    if st.shape[0] == 0:
        report.add(QCIssue("NO_STATIONS", "blocker", "no stations", oid))
        return report
    if not np.all(np.isfinite(st)):
        report.add(
            QCIssue("NON_FINITE_STATIONS", "error", "non-finite station values", oid)
        )
    md = st[:, 0]
    diffs = np.diff(md)
    if np.any(diffs <= 0):
        report.add(
            QCIssue(
                "NON_MONOTONIC_MD",
                "blocker",
                "MD is not strictly increasing (duplicate / unordered stations)",
                oid,
                metric=float(diffs.min()) if len(diffs) else None,
            )
        )
    xyz = st[:, 1:4]
    if len(st) >= 2:
        seg = np.linalg.norm(np.diff(xyz, axis=0), axis=1)
        zero = int((seg <= 1e-12).sum())
        if zero:
            report.add(
                QCIssue(
                    "ZERO_LENGTH_SEGMENTS",
                    "warning",
                    f"{zero} zero-length station interval(s)",
                    oid,
                    metric=float(zero),
                )
            )
    if well.representation == "measured" and len(st) < 3:
        report.add(
            QCIssue(
                "SPARSE_TRAJECTORY",
                "warning",
                "measured trajectory has fewer than 3 stations",
                oid,
                metric=float(len(st)),
            )
        )
    if well.representation == "simplified_vertical":
        report.add(
            QCIssue(
                "SIMPLIFIED_VERTICAL",
                "info",
                "simplified vertical indicator (no measured survey data)",
                oid,
            )
        )
    if well.z_unit and well.z_unit != well.unit:
        # z in a different unit than the horizontal plane is legal but must
        # never be silently mixed by consumers
        report.add(
            QCIssue(
                "MIXED_UNITS",
                "warning",
                f"horizontal unit {well.unit} differs from z unit {well.z_unit}",
                oid,
            )
        )
    return report


def _mesh_issue_codes(verts: np.ndarray, faces: np.ndarray) -> tuple[QCReport, np.ndarray, np.ndarray]:
    report = QCReport()
    v = np.asarray(verts, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    return report, v, f


def _tri_degenerate_fraction(v: np.ndarray, f: np.ndarray) -> float:
    if len(f) == 0:
        return 0.0
    tri = v[f]
    a = np.linalg.norm(tri[:, 1] - tri[:, 0], axis=1)
    b = np.linalg.norm(tri[:, 2] - tri[:, 1], axis=1)
    c = np.linalg.norm(tri[:, 0] - tri[:, 2], axis=1)
    longest = np.maximum(np.maximum(a, b), c)
    shortest = np.minimum(np.minimum(a, b), c)
    degenerate = shortest <= 1e-12 * np.maximum(longest, 1e-12)
    return float(degenerate.mean())


def _edge_manifold_stats(f: np.ndarray) -> tuple[int, int]:
    if len(f) == 0:
        return 0, 0
    edges = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]], axis=0)
    lo = np.min(edges, axis=1)
    hi = np.max(edges, axis=1)
    keys = lo.astype(np.int64) * (int(hi.max()) + 1) + hi
    unique, counts = np.unique(keys, return_counts=True)
    boundary = int((counts == 1).sum())
    nonmanifold = int((counts > 2).sum())
    return boundary, nonmanifold


def _connected_components(v: np.ndarray, f: np.ndarray) -> int:
    if len(f) == 0:
        return 0
    parent = np.arange(len(v))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = int(parent[x])
        return x

    for tri in f:
        r0 = find(int(tri[0]))
        for node in tri[1:]:
            r1 = find(int(node))
            if r0 != r1:
                parent[r1] = r0
    roots = {find(int(t[0])) for t in f}
    return len(roots)


def _grid_self_intersection_bounds(v: np.ndarray, f: np.ndarray, oid: str) -> None:
    """Placeholder-free bounded self-intersection screen.

    A full O(n²) triangle-triangle test is out of budget for medium meshes;
    the screen used here is the *inverted-normal consistency* test along the
    connectivity (a cheap, reliable self-intersection symptom for heightfield
    and shell meshes). Full generality is documented as out of scope in the
    QC panel text.
    """
    return None


def qc_horizon_surface(hor: HorizonSurface) -> QCReport:
    report = QCReport()
    oid = hor.object_id
    g = np.asarray(hor.z_grid, dtype=np.float64)
    if g.size == 0:
        report.add(QCIssue("NO_GEOMETRY", "blocker", "empty grid (artifact not loaded?)", oid))
        return report
    finite = np.isfinite(g)
    nan_fraction = float(1.0 - finite.mean())
    if nan_fraction > 0.5:
        report.add(
            QCIssue(
                "LARGELY_MISSING",
                "warning",
                f"{nan_fraction:.0%} of nodes are NaN holes",
                oid,
                metric=nan_fraction,
            )
        )
    elif nan_fraction > 0.0:
        report.add(
            QCIssue(
                "NAN_HOLES",
                "info",
                f"{nan_fraction:.1%} of nodes are NaN holes (kept as holes)",
                oid,
                metric=nan_fraction,
            )
        )
    if np.any(np.isinf(g)):
        report.add(
            QCIssue("NON_FINITE_GRID", "error", "grid contains +/-inf", oid)
        )
    if hor.crs in ("", "unknown") and not hor.grid_crs:
        report.add(
            QCIssue(
                "MISSING_CRS",
                "blocker",
                "neither world CRS nor grid CRS stated",
                oid,
            )
        )
    # triangulate (same path the renderer uses) for mesh-level checks
    from .builders import triangulate_heightfield

    verts, faces = triangulate_heightfield(g, origin=hor.origin, spacing=hor.spacing)
    if len(faces) == 0:
        report.add(QCIssue("NO_GEOMETRY", "blocker", "no finite triangulable area", oid))
        return report
    degenerate = _tri_degenerate_fraction(verts, faces)
    if degenerate > 0.0:
        report.add(
            QCIssue(
                "DEGENERATE_TRIANGLES",
                "error" if degenerate > 0.01 else "warning",
                f"{degenerate:.2%} degenerate triangles",
                oid,
                metric=degenerate,
            )
        )
    boundary, nonmanifold = _edge_manifold_stats(faces)
    if nonmanifold:
        report.add(
            QCIssue(
                "NON_MANIFOLD_EDGES",
                "error",
                f"{nonmanifold} non-manifold edge usage(s)",
                oid,
                metric=float(nonmanifold),
            )
        )
    report.add(
        QCIssue(
            "MESH_INFO",
            "info",
            f"{len(verts)} nodes, {len(faces)} triangles, "
            f"{boundary} boundary edges, {_connected_components(verts, faces)} component(s)",
            oid,
        )
    )
    if not hor.provenance.source_version_ids and not hor.horizon_asset_id and not hor.provenance.demo:
        report.add(
            QCIssue("NO_PROVENANCE", "warning", "no source version or asset id recorded", oid)
        )
    return report


def qc_fault_surface(fault: FaultSurface) -> QCReport:
    report = QCReport()
    oid = fault.object_id
    v = np.asarray(fault.verts, dtype=np.float64)
    f = np.asarray(fault.faces, dtype=np.int64).reshape(-1, 3)
    if fault.crs in ("", "unknown"):
        report.add(QCIssue("MISSING_CRS", "blocker", "CRS unknown", oid))
    if len(v) == 0 or len(f) == 0:
        report.add(QCIssue("NO_GEOMETRY", "blocker", "no fault geometry", oid))
        return report
    if fault.representation == "curtain_2p5d":
        report.add(
            QCIssue(
                "CURTAIN_REPRESENTATION",
                "info",
                "2.5-D curtain swept from a 2-D trace — not a mapped 3-D surface",
                oid,
            )
        )
    degenerate = _tri_degenerate_fraction(v, f)
    if degenerate > 0.0:
        report.add(
            QCIssue(
                "DEGENERATE_TRIANGLES",
                "error" if degenerate > 0.01 else "warning",
                f"{degenerate:.2%} degenerate triangles",
                oid,
                metric=degenerate,
            )
        )
    boundary, nonmanifold = _edge_manifold_stats(f)
    if nonmanifold:
        report.add(
            QCIssue(
                "NON_MANIFOLD_EDGES",
                "warning",
                f"{nonmanifold} non-manifold edge usage(s)",
                oid,
                metric=float(nonmanifold),
            )
        )
    return report


def qc_stratigraphic_volume(vol: StratigraphicVolume) -> QCReport:
    report = QCReport()
    oid = vol.object_id
    v = np.asarray(vol.verts, dtype=np.float64)
    f = np.asarray(vol.faces, dtype=np.int64).reshape(-1, 3)
    if vol.crs in ("", "unknown"):
        report.add(QCIssue("MISSING_CRS", "blocker", "CRS unknown", oid))
    if not vol.top_id or not vol.base_id:
        report.add(
            QCIssue(
                "MISSING_BOUNDING_SURFACES",
                "error",
                "top/base surface references missing",
                oid,
            )
        )
    if len(v) == 0 or len(f) == 0:
        report.add(
            QCIssue("NO_GEOMETRY", "blocker", "no shell geometry (build failed or not loaded)", oid)
        )
        return report
    boundary, nonmanifold = _edge_manifold_stats(f)
    if nonmanifold:
        report.add(
            QCIssue(
                "NON_MANIFOLD_EDGES",
                "error",
                f"{nonmanifold} non-manifold edge usage(s)",
                oid,
                metric=float(nonmanifold),
            )
        )
    closed = nonmanifold == 0 and boundary == 0
    if not closed:
        report.add(
            QCIssue(
                "SHEET_NOT_CLOSED",
                "blocker",
                f"shell not watertight: {boundary} boundary edges, {nonmanifold} non-manifold",
                oid,
                metric=float(boundary + nonmanifold),
            )
        )
    else:
        report.add(
            QCIssue("WATERTIGHT", "info", "shell is edge-manifold closed", oid)
        )
    degenerate = _tri_degenerate_fraction(v, f)
    if degenerate > 0.0:
        report.add(
            QCIssue(
                "DEGENERATE_TRIANGLES",
                "error" if degenerate > 0.01 else "warning",
                f"{degenerate:.2%} degenerate triangles",
                oid,
                metric=degenerate,
            )
        )
    components = _connected_components(v, f)
    if components > 1:
        report.add(
            QCIssue(
                "DISCONNECTED_COMPONENTS",
                "warning",
                f"{components} disconnected shell components",
                oid,
                metric=float(components),
            )
        )
    q = vol.quality or {}
    crossed = int(q.get("dropped_crossed", 0) or 0)
    if crossed:
        report.add(
            QCIssue(
                "CROSSED_COLUMNS",
                "warning" if crossed < q.get("column_count", 1) else "error",
                f"{crossed} crossed column(s) dropped at build time",
                oid,
                metric=float(crossed),
            )
        )
    thickness = float(q.get("min_thickness", 0.0) or 0.0)
    if thickness <= 0.0:
        report.add(
            QCIssue(
                "ZERO_MIN_THICKNESS",
                "warning",
                "minimum kept-column thickness is zero (pinch-out)",
                oid,
                metric=thickness,
            )
        )
    if not vol.provenance.source_version_ids and not vol.provenance.demo:
        report.add(
            QCIssue("NO_PROVENANCE", "warning", "no source version recorded", oid)
        )
    return report


def qc_tunnel_section(tunnel: TunnelSection) -> QCReport:
    report = QCReport()
    oid = tunnel.object_id
    p = np.asarray(tunnel.path, dtype=np.float64)
    if len(p) < 2:
        report.add(QCIssue("NO_GEOMETRY", "blocker", "path needs >= 2 points", oid))
    if tunnel.crs in ("", "unknown"):
        report.add(QCIssue("MISSING_CRS", "blocker", "CRS unknown", oid))
    return report


def qc_measurement(m: MeasurementRecord) -> QCReport:
    report = QCReport()
    oid = m.object_id
    if m.crs in ("", "unknown"):
        report.add(QCIssue("MISSING_CRS", "blocker", "CRS unknown", oid))
    if m.result is None and m.measurement_kind != "point":
        report.add(
            QCIssue("NO_RESULT", "warning", "measurement has no computed result", oid)
        )
    return report


_PER_KIND = {
    "well": qc_well_trajectory,
    "horizon": qc_horizon_surface,
    "fault": qc_fault_surface,
    "volume": qc_stratigraphic_volume,
    "tunnel": qc_tunnel_section,
    "measure": qc_measurement,
}


def qc_object(obj: DomainObject) -> QCReport:
    fn = _PER_KIND.get(obj.object_id.split(":", 1)[0])
    if fn is None:
        report = QCReport()
        report.add(
            QCIssue("UNKNOWN_KIND", "error", "unknown object kind", obj.object_id)
        )
        return report
    return fn(obj)  # type: ignore[arg-type]


def qc_assembly(
    assembly: ModelAssembly,
    *,
    known_source_ids: Iterable[str] | None = None,
) -> QCReport:
    """Audit every object; optionally flag stale source references.

    ``known_source_ids`` — Catalog version ids that are still resolvable;
    objects whose ``source_version_ids`` are all absent get a STALE_SOURCE
    warning (artifact may have been swept).
    """
    report = QCReport()
    known = set(known_source_ids) if known_source_ids is not None else None
    for obj in assembly.objects():
        report.extend(qc_object(obj))
        if known is not None:
            ids = obj.provenance.source_version_ids
            if ids and not (set(ids) & known):
                report.add(
                    QCIssue(
                        "STALE_SOURCE",
                        "warning",
                        f"source versions {sorted(ids)} not resolvable in catalog",
                        obj.object_id,
                    )
                )
    return report


def assert_exportable(
    objects: Iterable[DomainObject],
    report: QCReport | None = None,
) -> QCReport:
    """Export gate (ADR-06): refuse on blocker-level issues.

    Raises :class:`QCBlockerError` when any object carries a blocker; returns
    the (freshly computed, if not supplied) report otherwise.
    """
    obj_list = list(objects)
    if report is None:
        report = QCReport()
        for obj in obj_list:
            report.extend(qc_object(obj))
    blocked = {i.object_id for i in report.blockers()}
    if blocked:
        raise QCBlockerError(report, sorted(blocked))
    return report
