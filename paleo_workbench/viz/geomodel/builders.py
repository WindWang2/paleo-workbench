"""Pure-geometry builders: domain objects from raw inputs.

No Qt, no GL, no renderer — everything here is numpy geometry with honest
failure modes:

* heightfield triangulation keeps NaN holes as holes (no fabricated triangles
  spanning gaps);
* volume shells refuse to silently reorder crossed top/base surfaces (the
  crossing is reported through ``build_volume_shell``'s QC output);
* simplified vertical wells are exactly that — two stations straight down.

Domain object construction validates aggressively (``DomainError``) because
these objects are the authority the whole 3D workspace rebuilds from.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from .domain import (
    DomainError,
    FaultSurface,
    HorizonSurface,
    Provenance,
    StratigraphicVolume,
    WellTrajectory,
)

__all__ = [
    "build_well_trajectory",
    "build_simplified_vertical_well",
    "build_horizon_from_grid",
    "triangulate_heightfield",
    "build_fault_from_mesh",
    "build_fault_curtain_from_trace",
    "build_volume_shell",
    "build_columnar_hex_mesh",
]


# ---------------------------------------------------------------------------
# z-direction conventions
# ---------------------------------------------------------------------------


def _z_sign(vertical_domain: str) -> float:
    """+1 when z grows downward (depth / TWT), -1 for subsea elevation.

    The project's TVDSS convention is ``TVDSS = KB - TVD``
    (``CoordinateTransformHub.well_depth_to_tvdss``): deeper is *more
    negative*. Crossing / curtain-direction checks must respect this, or a
    perfectly healthy TVDSS pair is flagged as crossed.
    """
    return -1.0 if vertical_domain == "tvdss" else 1.0


# ---------------------------------------------------------------------------
# Wells
# ---------------------------------------------------------------------------


def build_well_trajectory(
    name: str,
    stations: Sequence[Sequence[float]],
    *,
    crs: str = "unknown",
    unit: str = "m",
    vertical_domain: str = "depth",
    well_asset_id: str = "",
    formation_tops: Sequence[tuple[str, float]] = (),
    provenance: Provenance | None = None,
    object_id: str | None = None,
) -> WellTrajectory:
    """Build a measured well trajectory from ``[md, x, y, z]`` stations.

    MD must be strictly increasing; duplicate / non-monotonic stations are a
    caller bug (deviated-survey convention) and raise ``DomainError`` — use
    ``dedupe_stations`` first when importing loose files.
    """
    st = np.asarray(stations, dtype=np.float64)
    if st.ndim != 2 or (st.size and st.shape[1] != 4):
        raise DomainError(f"{name}: stations must be (N, 4) [md,x,y,z]")
    if st.shape[0] >= 2 and np.any(np.diff(st[:, 0]) <= 0):
        raise DomainError(f"{name}: MD must be strictly increasing")
    oid = object_id or f"well:{_unique_slug(name)}"
    return WellTrajectory(
        object_id=oid,
        name=name,
        crs=crs,
        unit=unit,
        vertical_domain=vertical_domain,
        stations=st,
        representation="measured",
        well_asset_id=well_asset_id,
        formation_tops=tuple(formation_tops),
        provenance=provenance or Provenance(),
    )


def build_simplified_vertical_well(
    name: str,
    head_xyz: Sequence[float],
    total_depth: float,
    *,
    crs: str = "unknown",
    unit: str = "m",
    vertical_domain: str = "depth",
    well_asset_id: str = "",
    formation_tops: Sequence[tuple[str, float]] = (),
    provenance: Provenance | None = None,
    object_id: str | None = None,
) -> WellTrajectory:
    """Head-only well: an explicit two-station vertical indicator.

    The representation field makes the simplification visible everywhere
    (inspector, export, QC) — this is never presented as a measured
    trajectory.
    """
    head = np.asarray(head_xyz, dtype=np.float64)
    if head.shape != (3,):
        raise DomainError(f"{name}: head_xyz must be (x, y, z)")
    if not np.all(np.isfinite(head)):
        raise DomainError(f"{name}: head_xyz must be finite")
    if not (total_depth > 0.0):
        raise DomainError(f"{name}: total_depth must be positive")
    if vertical_domain in ("depth", "tvdss"):
        td_xyz = np.array([head[0], head[1], head[2] + total_depth])
    else:  # twt domain: head z is 0 ms by convention, TD is the two-way time
        td_xyz = np.array([head[0], head[1], float(total_depth)])
    st = np.array(
        [
            [0.0, head[0], head[1], head[2]],
            [float(total_depth), td_xyz[0], td_xyz[1], td_xyz[2]],
        ]
    )
    oid = object_id or f"well:{_unique_slug(name)}"
    return WellTrajectory(
        object_id=oid,
        name=name,
        crs=crs,
        unit=unit,
        vertical_domain=vertical_domain,
        stations=st,
        representation="simplified_vertical",
        well_asset_id=well_asset_id,
        formation_tops=tuple(formation_tops),
        provenance=provenance or Provenance(),
    )


def dedupe_stations(stations: Sequence[Sequence[float]], *, tol: float = 1e-9):
    """Sort by MD and drop duplicate / zero-length stations (import helper).

    Returns ``(stations, dropped_count)``; raises on non-finite rows.
    """
    st = np.asarray(stations, dtype=np.float64)
    if st.ndim != 2 or (st.size and st.shape[1] != 4):
        raise DomainError("stations must be (N, 4)")
    if st.size and not np.all(np.isfinite(st)):
        raise DomainError("stations contain non-finite values")
    order = np.argsort(st[:, 0], kind="stable")
    st = st[order]
    kept = [st[0]] if len(st) else []
    dropped = 0
    for row in st[1:]:
        if abs(row[0] - kept[-1][0]) <= tol * max(1.0, abs(kept[-1][0])):
            dropped += 1
            continue
        kept.append(row)
    return (np.asarray(kept, dtype=np.float64), dropped)


# ---------------------------------------------------------------------------
# Horizons
# ---------------------------------------------------------------------------


def build_horizon_from_grid(
    name: str,
    z_grid: Sequence[Sequence[float]],
    *,
    origin: tuple[float, float] = (0.0, 0.0),
    spacing: tuple[float, float] = (1.0, 1.0),
    crs: str = "unknown",
    grid_crs: str = "",
    vertical_domain: str = "depth",
    unit: str = "m",
    horizon_asset_id: str = "",
    confidence: Sequence[Sequence[float]] | None = None,
    attributes: Sequence[tuple[str, Sequence[Sequence[float]]]] = (),
    provenance: Provenance | None = None,
    object_id: str | None = None,
) -> HorizonSurface:
    """Structured-grid horizon. NaN nodes are holes and stay holes."""
    g = np.asarray(z_grid, dtype=np.float64)
    if g.ndim != 2 or g.size == 0:
        raise DomainError(f"{name}: z_grid must be a non-empty 2-D array")
    conf = None if confidence is None else np.asarray(confidence, dtype=np.float64)
    attrs = tuple((str(n), np.asarray(a, dtype=np.float64)) for n, a in attributes)
    oid = object_id or f"horizon:{_unique_slug(name)}"
    return HorizonSurface(
        object_id=oid,
        name=name,
        crs=crs,
        grid_crs=grid_crs,
        vertical_domain=vertical_domain,
        unit=unit,
        z_grid=g,
        origin=tuple(float(v) for v in origin),
        spacing=tuple(float(v) for v in spacing),
        horizon_asset_id=horizon_asset_id,
        confidence=conf,
        attributes=attrs,
        provenance=provenance or Provenance(),
    )


def triangulate_heightfield(
    z_grid: np.ndarray,
    *,
    origin: tuple[float, float] = (0.0, 0.0),
    spacing: tuple[float, float] = (1.0, 1.0),
) -> tuple[np.ndarray, np.ndarray]:
    """Triangulate a structured heightfield, honouring NaN holes.

    Each finite quad splits into two triangles. Quads touching a NaN node are
    dropped entirely — triangulating across a hole would fabricate surface
    where the interpreter said there is none. Returns ``(verts (N, 3), faces
    (M, 3))`` with compacted vertex indexing.
    """
    g = np.asarray(z_grid, dtype=np.float64)
    if g.ndim != 2:
        raise DomainError("z_grid must be 2-D")
    dy, dx = float(spacing[0]), float(spacing[1])
    x0, y0 = float(origin[0]), float(origin[1])
    nI, nX = g.shape
    # Valid nodes and their compacted indices
    valid = np.isfinite(g)
    idx = np.full(g.shape, -1, dtype=np.int64)
    idx[valid] = np.arange(int(valid.sum()), dtype=np.int64)
    xs = x0 + np.arange(nX) * dx
    ys = y0 + np.arange(nI) * dy
    xx, yy = np.meshgrid(xs, ys)
    verts = np.column_stack((xx[valid], yy[valid], g[valid])).astype(np.float64)

    quads = valid[:-1, :-1] & valid[:-1, 1:] & valid[1:, :-1] & valid[1:, 1:]
    qi, qj = np.nonzero(quads)
    a = idx[qi, qj]
    b = idx[qi, qj + 1]
    c = idx[qi + 1, qj + 1]
    d = idx[qi + 1, qj]
    # Winding: (a, b, c) + (a, c, d) keeps a consistent outward-up orientation
    faces = np.empty((len(qi) * 2, 3), dtype=np.int64)
    faces[0::2] = np.column_stack((a, b, c))
    faces[1::2] = np.column_stack((a, c, d))
    return verts, faces


# ---------------------------------------------------------------------------
# Faults
# ---------------------------------------------------------------------------


def build_fault_from_mesh(
    name: str,
    verts: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
    *,
    crs: str = "unknown",
    unit: str = "m",
    vertical_domain: str = "depth",
    throw_m: float | None = None,
    strike_dip: tuple[float, float] | None = None,
    fault_asset_id: str = "",
    provenance: Provenance | None = None,
    object_id: str | None = None,
) -> FaultSurface:
    """A real 3-D triangulated fault surface (imported or derived)."""
    v = np.asarray(verts, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64)
    if v.ndim != 2 or (v.size and v.shape[1] != 3):
        raise DomainError(f"{name}: verts must be (N, 3)")
    if f.ndim != 2 or (f.size and f.shape[1] != 3):
        raise DomainError(f"{name}: faces must be (M, 3)")
    oid = object_id or f"fault:{_unique_slug(name)}"
    return FaultSurface(
        object_id=oid,
        name=name,
        crs=crs,
        unit=unit,
        vertical_domain=vertical_domain,
        verts=v,
        faces=f,
        representation="triangulated_3d",
        throw_m=throw_m,
        strike_dip=strike_dip,
        fault_asset_id=fault_asset_id,
        provenance=provenance or Provenance(),
    )


def build_fault_curtain_from_trace(
    name: str,
    trace_xy: Sequence[Sequence[float]],
    z_top: float,
    z_bottom: float,
    *,
    crs: str = "unknown",
    unit: str = "m",
    vertical_domain: str = "depth",
    provenance: Provenance | None = None,
    object_id: str | None = None,
) -> FaultSurface:
    """2.5-D curtain fault swept from a 2-D trace between two z levels.

    The representation is explicitly ``curtain_2p5d``: everywhere the fault
    surfaces (inspector, QC, export) it is labelled as what it is.
    """
    t = np.asarray(trace_xy, dtype=np.float64)
    if t.ndim != 2 or len(t) < 2 or t.shape[1] != 2:
        raise DomainError(f"{name}: trace_xy must be (M, 2) with M >= 2")
    if not np.all(np.isfinite(t)):
        raise DomainError(f"{name}: trace_xy must be finite")
    if (z_bottom - z_top) <= 0.0:
        raise DomainError(
            f"{name}: z_bottom must be below z_top (depth-positive convention)"
        )
    n = len(t)
    verts = np.empty((2 * n, 3), dtype=np.float64)
    verts[:n, :2] = t
    verts[:n, 2] = z_top
    verts[n:, :2] = t
    verts[n:, 2] = z_bottom
    quads = np.arange(n - 1)
    a, b = quads, quads + 1
    c, d = quads + n + 1, quads + n
    faces = np.empty(((n - 1) * 2, 3), dtype=np.int64)
    faces[0::2] = np.column_stack((a, b, c))
    faces[1::2] = np.column_stack((a, c, d))
    oid = object_id or f"fault:{_unique_slug(name)}"
    return FaultSurface(
        object_id=oid,
        name=name,
        crs=crs,
        unit=unit,
        vertical_domain=vertical_domain,
        verts=verts,
        faces=faces,
        representation="curtain_2p5d",
        trace_xy=t,
        z_extent=(float(z_top), float(z_bottom)),
        provenance=provenance or Provenance(),
    )


# ---------------------------------------------------------------------------
# Stratigraphic volumes
# ---------------------------------------------------------------------------


def build_volume_shell(
    top: HorizonSurface,
    base: HorizonSurface,
    boundary: Sequence[Sequence[float]],
    *,
    object_id: str,
    name: str | None = None,
    formation: str = "",
    provenance: Provenance | None = None,
) -> tuple[StratigraphicVolume, dict[str, Any]]:
    """Build a closed volume shell between two surfaces inside a boundary.

    Columns are the finite lattice cells of the shared grid whose centre is
    inside ``boundary`` and whose top/base are **not crossed** (crossed
    columns are dropped and counted — never silently reordered).

    Construction (kept-cell corner sets):

    * top sheet  — up-facing triangles over each kept cell;
    * base sheet — down-facing triangles over each kept cell;
    * side walls — quads across every kept-cell edge whose neighbour cell is
      not kept (outside, NaN, or crossed).

    Returns ``(volume, qc_summary)``; ``qc["closed"]`` is an edge-manifold
    check of the assembled shell.
    """
    if top.vertical_domain != base.vertical_domain or top.unit != base.unit:
        raise DomainError(
            f"{object_id}: top/base surfaces must share vertical domain and unit"
        )
    bnd = np.asarray(boundary, dtype=np.float64)
    if bnd.ndim != 2 or len(bnd) < 3 or bnd.shape[1] != 2:
        raise DomainError(f"{object_id}: boundary must be (M, 2) with M >= 3")
    if not np.all(np.isfinite(bnd)):
        raise DomainError(f"{object_id}: boundary must be finite")

    tg = np.asarray(top.z_grid, dtype=np.float64)
    bg = np.asarray(base.z_grid, dtype=np.float64)
    if tg.shape != bg.shape or top.origin != base.origin or top.spacing != base.spacing:
        raise DomainError(
            f"{object_id}: top/base grids must share shape/origin/spacing for "
            "column construction (resample first)"
        )

    dy, dx = top.spacing
    x0, y0 = top.origin
    nI, nX = tg.shape
    if nI < 2 or nX < 2:
        raise DomainError(f"{object_id}: grid needs at least a 2x2 node lattice")
    xs = x0 + np.arange(nX) * dx
    ys = y0 + np.arange(nI) * dy
    xx, yy = np.meshgrid(xs, ys)  # (nI, nX)

    # Kept cells: finite pair, cell centre inside the boundary, not crossed.
    # A cell (i, j) owns corners (i, j), (i, j+1), (i+1, j), (i+1, j+1).
    node_finite = np.isfinite(tg) & np.isfinite(bg)
    cell_ok = (
        node_finite[:-1, :-1]
        & node_finite[:-1, 1:]
        & node_finite[1:, :-1]
        & node_finite[1:, 1:]
    )
    ci, cj = np.nonzero(cell_ok)
    centre_x = 0.25 * (xx[ci, cj] + xx[ci, cj + 1] + xx[ci + 1, cj] + xx[ci + 1, cj + 1])
    centre_y = 0.25 * (yy[ci, cj] + yy[ci, cj + 1] + yy[ci + 1, cj] + yy[ci + 1, cj + 1])
    inside = _points_in_polygon_grid(centre_x, centre_y, bnd)
    # Crossed anywhere within the cell: "base above top" in the domain's z
    # sense at any corner means an inverted (invalid) column.
    zsign = _z_sign(top.vertical_domain)
    crossed = (
        ((bg[ci, cj] - tg[ci, cj]) * zsign < 0)
        | ((bg[ci, cj + 1] - tg[ci, cj + 1]) * zsign < 0)
        | ((bg[ci + 1, cj] - tg[ci + 1, cj]) * zsign < 0)
        | ((bg[ci + 1, cj + 1] - tg[ci + 1, cj + 1]) * zsign < 0)
    )
    finite_cells = set()
    for k in range(len(ci)):
        if crossed[k]:
            continue
        if inside[k]:
            finite_cells.add((int(ci[k]), int(cj[k])))
    dropped_crossed = int(crossed.sum())
    dropped_nan = int((~node_finite).sum())

    if not finite_cells:
        empty_qc = {
            "column_count": 0,
            "dropped_crossed": dropped_crossed,
            "dropped_nan_nodes": dropped_nan,
            "negative_thickness_count": 0,
            "min_thickness": 0.0,
            "max_thickness": 0.0,
            "mean_thickness": 0.0,
            "closed": False,
            "unit": top.unit,
        }
        volume = StratigraphicVolume(
            object_id=object_id,
            name=name or object_id.split(":", 1)[1],
            crs=top.crs,
            vertical_domain=top.vertical_domain,
            unit=top.unit,
            top_id=top.object_id,
            base_id=base.object_id,
            boundary=bnd,
            formation=formation,
            provenance=provenance or Provenance(source_kind="derived"),
            quality=empty_qc,
        )
        return volume, empty_qc

    # Node mask: corners of kept cells, compacted.
    node_mask = np.zeros((nI, nX), dtype=bool)
    for (i, j) in finite_cells:
        node_mask[i, j] = True
        node_mask[i, j + 1] = True
        node_mask[i + 1, j] = True
        node_mask[i + 1, j + 1] = True
    node_ids = np.full((nI, nX), -1, dtype=np.int64)
    gi, gj = np.nonzero(node_mask)
    node_ids[gi, gj] = np.arange(len(gi))
    n_shared = len(gi)

    verts = np.empty((2 * n_shared, 3), dtype=np.float64)
    verts[:n_shared, 0] = xx[gi, gj]
    verts[:n_shared, 1] = yy[gi, gj]
    verts[:n_shared, 2] = tg[gi, gj]
    verts[n_shared:, 0] = xx[gi, gj]
    verts[n_shared:, 1] = yy[gi, gj]
    verts[n_shared:, 2] = bg[gi, gj]

    faces: list[tuple[int, int, int]] = []
    thicknesses: list[float] = []

    def nid(i: int, j: int, sheet_offset: int) -> int:
        return int(node_ids[i, j]) + sheet_offset

    for (i, j) in sorted(finite_cells):
        t00, t01 = nid(i, j, 0), nid(i, j + 1, 0)
        t10, t11 = nid(i + 1, j, 0), nid(i + 1, j + 1, 0)
        b00, b01 = nid(i, j, n_shared), nid(i, j + 1, n_shared)
        b10, b11 = nid(i + 1, j, n_shared), nid(i + 1, j + 1, n_shared)
        # top sheet (up), base sheet (down)
        faces += [(t00, t01, t11), (t00, t11, t10)]
        faces += [(b00, b11, b01), (b00, b10, b11)]
        thicknesses.append(
            0.25
            * abs(
                float(
                    (tg[i, j] - bg[i, j])
                    + (tg[i, j + 1] - bg[i, j + 1])
                    + (tg[i + 1, j] - bg[i + 1, j])
                    + (tg[i + 1, j + 1] - bg[i + 1, j + 1])
                )
            )
        )

        # Side walls across edges whose neighbour cell is not kept.
        # (corner order along each edge chosen so walls face outward)
        edges = (
            (t00, t01, b00, b01, (i - 1, j)),      # -i edge
            (t01, t11, b01, b11, (i, j + 1)),      # +j edge
            (t11, t10, b11, b10, (i + 1, j)),      # +i edge
            (t10, t00, b10, b00, (i, j - 1)),      # -j edge
        )
        for ta, tb, ba, bb_, neighbour in edges:
            if neighbour in finite_cells:
                continue
            faces += [(ta, tb, bb_), (ta, bb_, ba)]

    verts_arr = verts
    faces_arr = _orient_faces_outward(verts, np.asarray(faces, dtype=np.int64).reshape(-1, 3))
    thickness_arr = np.asarray(thicknesses, dtype=np.float64)

    qc: dict[str, Any] = {
        "column_count": len(finite_cells),
        "dropped_crossed": dropped_crossed,
        "dropped_nan_nodes": dropped_nan,
        "negative_thickness_count": 0,
        "min_thickness": float(thickness_arr.min()),
        "max_thickness": float(thickness_arr.max()),
        "mean_thickness": float(thickness_arr.mean()),
        "closed": _shell_is_closed(verts_arr, faces_arr),
        "unit": top.unit,
    }

    volume = StratigraphicVolume(
        object_id=object_id,
        name=name or object_id.split(":", 1)[1],
        crs=top.crs,
        vertical_domain=top.vertical_domain,
        unit=top.unit,
        verts=verts_arr,
        faces=faces_arr,
        top_id=top.object_id,
        base_id=base.object_id,
        boundary=bnd,
        formation=formation,
        provenance=provenance
        or Provenance(
            source_kind="derived",
            source_version_ids=tuple(
                dict.fromkeys(
                    list(top.provenance.source_version_ids)
                    + list(base.provenance.source_version_ids)
                )
            ),
        ),
        quality=qc,
    )
    return volume, qc


def _points_in_polygon_grid(
    px: np.ndarray, py: np.ndarray, poly: np.ndarray
) -> np.ndarray:
    """Vectorized ray-casting point-in-polygon for matched point grids."""
    px = np.asarray(px, dtype=np.float64)
    py = np.asarray(py, dtype=np.float64)
    shape = np.broadcast_shapes(px.shape, py.shape)
    px = np.broadcast_to(px, shape).ravel()
    py = np.broadcast_to(py, shape).ravel()
    x = poly[:, 0]
    y = poly[:, 1]
    inside = np.zeros(px.shape, dtype=bool)
    n = len(poly)
    j = n - 1
    for k in range(n):
        yk, yj = y[k], y[j]
        xk, xj = x[k], x[j]
        cond = (yk > py) != (yj > py)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (xj - xk) * (py - yk) / np.where(yj != yk, yj - yk, 1.0) + xk
        inside ^= cond & (px < xint)
        j = k
    return inside.reshape(shape)


def _orient_faces_outward(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Reorient every triangle to face away from the shell centroid.

    The prismatic shells this module builds are star-shaped w.r.t. their
    centroid, so the per-face centroid test is a reliable outward test and
    is independent of the vertical-domain z convention (depth positive-down
    vs TVDSS negative-down), which the hand-wound sheets/walls could not
    satisfy simultaneously. Non-star-shaped inputs fall back to unflipped
    faces — QC's manifold/watertight checks are orientation-independent.
    """
    if len(faces) == 0 or len(verts) == 0:
        return faces
    tri = verts[faces]
    centroids = tri.mean(axis=1)
    shell_centroid = verts.mean(axis=0)
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    outward = centroids - shell_centroid
    flip = np.einsum("ij,ij->i", normals, outward) < 0
    out = faces.copy()
    out[flip] = out[flip][:, [0, 2, 1]]
    return out


def _shell_is_closed(verts: np.ndarray, faces: np.ndarray) -> bool:
    """Edge-manifold check: every undirected edge shared by exactly 2 faces."""
    if len(faces) == 0:
        return False
    f = np.asarray(faces, dtype=np.int64)
    edges = np.concatenate(
        [f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]], axis=0
    )
    lo = np.min(edges, axis=1)
    hi = np.max(edges, axis=1)
    keys = lo.astype(np.int64) * max(int(hi.max()) + 1, 1) + hi
    _, counts = np.unique(keys, return_counts=True)
    return bool(np.all(counts == 2))


# ---------------------------------------------------------------------------
# Computational mesh (hexahedral columns) for FLAC3D / Abaqus export
# ---------------------------------------------------------------------------


def build_columnar_hex_mesh(
    top: HorizonSurface,
    base: HorizonSurface,
    boundary: Sequence[Sequence[float]],
    *,
    n_layers: int = 4,
) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Columnar hexahedral mesh following top/base between the horizons.

    Each kept cell becomes ``n_layers`` hexahedra stacked between the top and
    base surfaces. Cells own **private** nodes (faces across columns are not
    merged) which keeps every column watertight by construction; the export
    sidecar documents ``merge: none`` so downstream simulators that need
    shared faces can merge on coordinates.

    Returns ``(nodes (N, 3), hexes (M, 8), info)``. Node order per hex:
    bottom loop ``[(i,j), (i+1,j), (i+1,j+1), (i,j+1)]`` then top loop with
    the same order (FLAC3D B8 / Abaqus C3D8 convex-column convention).
    Crossed columns are skipped and counted in ``info``.
    """
    if n_layers < 1:
        raise DomainError("n_layers must be >= 1")
    bnd = np.asarray(boundary, dtype=np.float64)
    if bnd.ndim != 2 or len(bnd) < 3 or bnd.shape[1] != 2:
        raise DomainError("boundary must be (M, 2) with M >= 3")
    if not np.all(np.isfinite(bnd)):
        raise DomainError("boundary must be finite")
    if top.vertical_domain != base.vertical_domain or top.unit != base.unit:
        raise DomainError("top/base surfaces must share vertical domain and unit")
    tg = np.asarray(top.z_grid, dtype=np.float64)
    bg = np.asarray(base.z_grid, dtype=np.float64)
    if tg.shape != bg.shape or top.origin != base.origin or top.spacing != base.spacing:
        raise DomainError("top/base grids must share shape/origin/spacing")

    dy, dx = top.spacing
    x0, y0 = top.origin
    nI, nX = tg.shape
    if nI < 2 or nX < 2:
        raise DomainError("grid needs at least a 2x2 node lattice")
    xx, yy = np.meshgrid(
        x0 + np.arange(nX) * dx, y0 + np.arange(nI) * dy
    )
    node_finite = np.isfinite(tg) & np.isfinite(bg)
    cell_ok = (
        node_finite[:-1, :-1]
        & node_finite[:-1, 1:]
        & node_finite[1:, :-1]
        & node_finite[1:, 1:]
    )
    ci, cj = np.nonzero(cell_ok)
    centre_x = 0.25 * (xx[ci, cj] + xx[ci, cj + 1] + xx[ci + 1, cj] + xx[ci + 1, cj + 1])
    centre_y = 0.25 * (yy[ci, cj] + yy[ci, cj + 1] + yy[ci + 1, cj] + yy[ci + 1, cj + 1])
    inside = _points_in_polygon_grid(centre_x, centre_y, bnd)
    # Crossed anywhere within the cell, in the domain's z sense: drop,
    # never reorder.
    zsign = _z_sign(top.vertical_domain)
    crossed = (
        ((bg[ci, cj] - tg[ci, cj]) * zsign < 0)
        | ((bg[ci, cj + 1] - tg[ci, cj + 1]) * zsign < 0)
        | ((bg[ci + 1, cj] - tg[ci + 1, cj]) * zsign < 0)
        | ((bg[ci + 1, cj + 1] - tg[ci + 1, cj + 1]) * zsign < 0)
    )
    keep = inside & ~crossed
    cell_i = ci[keep]
    cell_j = cj[keep]
    n_cells = len(cell_i)

    corners_i = np.array([0, 1, 1, 0])
    corners_j = np.array([0, 0, 1, 1])
    frac = np.linspace(0.0, 1.0, n_layers + 1)

    nodes = np.empty((n_cells * (n_layers + 1) * 4, 3), dtype=np.float64)
    hexes = np.empty((n_cells * n_layers, 8), dtype=np.int64)
    cell_node_base = np.arange(n_cells) * (n_layers + 1) * 4
    top_z = tg[cell_i, cell_j]
    bot_z = bg[cell_i, cell_j]
    for corner in range(4):
        cx = xx[cell_i + corners_i[corner], cell_j + corners_j[corner]]
        cy = yy[cell_i + corners_i[corner], cell_j + corners_j[corner]]
        zt = tg[cell_i + corners_i[corner], cell_j + corners_j[corner]]
        zb = bg[cell_i + corners_i[corner], cell_j + corners_j[corner]]
        for layer in range(n_layers + 1):
            f = frac[layer]
            idx = cell_node_base + layer * 4 + corner
            nodes[idx, 0] = cx
            nodes[idx, 1] = cy
            nodes[idx, 2] = zt + (zb - zt) * f
    for layer in range(n_layers):
        lo = cell_node_base + layer * 4
        hi = lo + 4
        hexes[layer::n_layers, 0:4] = np.column_stack(
            [lo + c for c in range(4)]
        )
        hexes[layer::n_layers, 4:8] = np.column_stack(
            [hi + c for c in range(4)]
        )

    info = {
        "n_cells": int(n_cells),
        "n_layers": int(n_layers),
        "n_hexes": int(len(hexes)),
        "skipped_crossed": int(crossed.sum()),
        "unit": top.unit,
        "merge": "none",
    }
    return nodes, hexes, info


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _unique_slug(name: str) -> str:
    """Deterministic id slug derived from the display name.

    Uniqueness is the assembly's job (``ModelAssembly.add`` rejects
    duplicates); builders stay stateless so identical input always yields
    the identical object_id.
    """
    from .domain import _slugify

    return _slugify(name, "obj")
