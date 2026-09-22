"""Section / clip plane intersection geometry (G8 display half).

Given a plane in world coordinates, computes the intersection **curves**
of horizon surfaces, fault meshes and well trajectories with that plane so
a section view shows the geometric truth instead of just clipping meshes.

Pure numpy; the adapter renders the returned polylines as line scene objects.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

__all__ = [
    "Plane",
    "axis_plane",
    "plane_from_normal_point",
    "clip_planes_for_box",
    "intersect_plane_with_triangles",
    "horizon_plane_intersection",
    "mesh_plane_intersection",
    "well_plane_crossing",
]


class Plane:
    """World-space plane ``n·p = d`` with a unit normal."""

    __slots__ = ("n", "d")

    def __init__(self, normal: Sequence[float], d: float) -> None:
        n = np.asarray(normal, dtype=np.float64)
        norm = float(np.linalg.norm(n))
        if norm < 1e-12:
            raise ValueError("plane normal must be non-zero")
        self.n = n / norm
        self.d = float(d) / norm

    def signed_distance(self, points: np.ndarray) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float64)
        return pts @ self.n - self.d

    def as_clip_equation(self, invert: bool = False) -> tuple[float, float, float, float]:
        """GL_CLIP_PLANE equation keeping the half-space ``n·p <= d``.

        GL keeps points where ``a·x + b·y + c·z + d >= 0``, so the plane is
        submitted as ``(-n, d)``; ``invert`` keeps ``n·p >= d`` instead.
        """
        s = 1.0 if invert else -1.0
        return (s * self.n[0], s * self.n[1], s * self.n[2], s * -self.d)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Plane(n={self.n.tolist()}, d={self.d:.4f})"


def axis_plane(axis: str, value: float) -> Plane:
    """X / Y / Z constant plane (world coordinates)."""
    n = {"x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}.get(axis)
    if n is None:
        raise ValueError(f"axis must be x/y/z, got {axis!r}")
    return Plane(n, value)


def plane_from_normal_point(normal: Sequence[float], point: Sequence[float]) -> Plane:
    return Plane(normal, float(np.asarray(normal) @ np.asarray(point)))


def clip_planes_for_box(
    bounds: Sequence[Sequence[float]], *, invert: bool = False
) -> list[tuple[float, float, float, float]]:
    """Six clip equations for an axis-aligned box (the visible inside)."""
    b = np.asarray(bounds, dtype=np.float64)
    lo, hi = b[0], b[1]
    planes = [
        Plane((1, 0, 0), hi[0]),
        Plane((-1, 0, 0), -lo[0]),
        Plane((0, 1, 0), hi[1]),
        Plane((0, -1, 0), -lo[1]),
        Plane((0, 0, 1), hi[2]),
        Plane((0, 0, -1), -lo[2]),
    ]
    return [p.as_clip_equation(invert=invert) for p in planes]


def intersect_plane_with_triangles(
    plane: Plane, verts: np.ndarray, faces: np.ndarray
) -> list[np.ndarray]:
    """Intersection segments of a plane with a triangle soup.

    Returns a list of (2, 3) segments (world coords). Unsorted.
    """
    v = np.asarray(verts, dtype=np.float64)
    f = np.asarray(faces, dtype=np.int64).reshape(-1, 3)
    if len(f) == 0:
        return []
    tri = v[f]
    dist = plane.signed_distance(tri)  # (M, 3)
    segs: list[np.ndarray] = []
    pos = dist > 0
    neg = dist < 0
    on = ~pos & ~neg
    for m in range(len(f)):
        d = dist[m]
        p = tri[m]
        plus = np.flatnonzero(pos[m])
        minus = np.flatnonzero(neg[m])
        zeros = np.flatnonzero(on[m])
        edge_pts: list[np.ndarray] = []
        if len(zeros) >= 2:
            segs.append(np.vstack([p[zeros[0]], p[zeros[1]]]))
            continue
        if len(zeros) == 1 and len(plus) and len(minus):
            edge_pts.append(p[zeros[0]])
        for a in plus:
            for b in minus:
                t = d[a] / (d[a] - d[b])
                edge_pts.append(p[a] + t * (p[b] - p[a]))
        if len(edge_pts) >= 2:
            segs.append(np.vstack([edge_pts[0], edge_pts[1]]))
    return segs


def _chain_segments(segments: list[np.ndarray]) -> list[np.ndarray]:
    """Greedy chaining of segments into polylines (section display)."""
    if not segments:
        return []
    remaining = [s.copy() for s in segments]
    # scale-aware weld tolerance: absolute 1e-9 fragments chains on UTM-scale
    # coordinates where float64 noise is ~1e-8 relative
    all_pts = np.vstack([np.vstack(s) for s in segments])
    scale = float(np.abs(all_pts).max()) if len(all_pts) else 1.0
    tol = max(1e-9, scale * 1e-9)
    chains: list[np.ndarray] = []
    while remaining:
        chain = remaining.pop(0)
        extended = True
        while extended:
            extended = False
            for k, s in enumerate(remaining):
                if np.max(np.abs(s[0] - chain[-1])) < tol:
                    chain = np.vstack([chain, s[1]])
                    remaining.pop(k)
                    extended = True
                    break
                if np.max(np.abs(s[1] - chain[-1])) < tol:
                    chain = np.vstack([chain, s[0]])
                    remaining.pop(k)
                    extended = True
                    break
                if np.max(np.abs(s[1] - chain[0])) < tol:
                    chain = np.vstack([s[0], chain])
                    remaining.pop(k)
                    extended = True
                    break
                if np.max(np.abs(s[0] - chain[0])) < tol:
                    chain = np.vstack([s[1], chain])
                    remaining.pop(k)
                    extended = True
                    break
        chains.append(chain)
    return chains


def horizon_plane_intersection(
    plane: Plane,
    z_grid: np.ndarray,
    *,
    origin: tuple[float, float] = (0.0, 0.0),
    spacing: tuple[float, float] = (1.0, 1.0),
) -> list[np.ndarray]:
    """Section curve of a structured horizon with the plane (chained polylines).

    NaN nodes punch holes in the curve exactly like they do on the surface.
    """
    from .builders import triangulate_heightfield

    verts, faces = triangulate_heightfield(
        z_grid, origin=origin, spacing=spacing
    )
    segs = intersect_plane_with_triangles(plane, verts, faces)
    return _chain_segments(segs)


def mesh_plane_intersection(
    plane: Plane, verts: np.ndarray, faces: np.ndarray
) -> list[np.ndarray]:
    """Section curves of a triangle mesh (fault / volume shell) — chained."""
    segs = intersect_plane_with_triangles(plane, verts, faces)
    return _chain_segments(segs)


def well_plane_crossing(
    plane: Plane, stations_xyz: np.ndarray
) -> np.ndarray | None:
    """First crossing point of a well polyline with the plane, or None."""
    p = np.asarray(stations_xyz, dtype=np.float64)
    if len(p) < 2:
        return None
    d = plane.signed_distance(p)
    signs = np.sign(d)
    for k in range(len(p) - 1):
        if signs[k] == 0.0:
            return p[k]
        if signs[k] != signs[k + 1] and signs[k + 1] != 0.0:
            t = d[k] / (d[k] - d[k + 1])
            return p[k] + t * (p[k + 1] - p[k])
    return None
