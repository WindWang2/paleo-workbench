"""Direction-line strong stretch corridor (curve coordinates + influence field).

Implements Surfer-style local anisotropy while allowing multiple direction
polylines to control different map regions independently.

Design notes
------------
* Each direction line is a local depositional axis (not a single global angle).
* Within ``core_radius`` the full stretch ratio is applied; between core and
  ``influence_radius`` the influence strength ``g`` decays smoothly to 0.
* Grid–well pairs under the same controlling line use curve coordinates
  ``(s, n)`` so elongation follows bent polylines.
* Search neighborhoods stretch with the same ratio (ellipse in local axes).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

PointTuple = Tuple[float, float]


@dataclass(frozen=True)
class DirectionLineSpec:
    """Resolved direction-line parameters used by the corridor engine."""

    line_id: str
    points: Tuple[PointTuple, ...]
    active: bool = True
    ratio: float = 12.0
    influence_radius: float = 0.0  # 0 → resolve from well spacing / search radius
    priority: int = 1
    core_radius: float = 0.0  # 0 → use base search radius
    zone_id: str = ""
    extend_mode: str = "auto"  # auto | none | tangent
    transition: float = 0.0  # 0 → auto (influence - core)


@dataclass
class PolylineGeometry:
    """Precomputed polyline arc-length geometry (optionally end-extended)."""

    line_id: str
    points: np.ndarray  # (N, 2)
    cumlen: np.ndarray  # (N,) arc length at vertices
    total_length: float
    ratio: float
    core_radius: float
    influence_radius: float
    priority: int
    zone_id: str
    extend_mode: str
    transition: float
    # Extension bookkeeping (map coords of original endpoints on the chain)
    s_start: float = 0.0  # arc-length of original start (may be >0 after extend)
    s_end: float = 0.0  # arc-length of original end
    index: int = 0


@dataclass
class PointCurveCoord:
    """Projection of a point onto a direction polyline."""

    dir_index: int
    s: float
    n: float  # signed normal distance
    tx: float
    ty: float
    g: float  # influence strength in [0, 1]
    ratio: float
    distance: float  # Euclidean distance to the polyline


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _unit(dx: float, dy: float) -> Tuple[float, float]:
    length = math.hypot(dx, dy)
    if length <= 1e-15:
        return 1.0, 0.0
    return dx / length, dy / length


def _polyline_length(points: Sequence[PointTuple]) -> float:
    total = 0.0
    for i in range(1, len(points)):
        total += math.hypot(
            float(points[i][0]) - float(points[i - 1][0]),
            float(points[i][1]) - float(points[i - 1][1]),
        )
    return total


def resolve_direction_params(
    specs: Sequence[DirectionLineSpec],
    *,
    search_radius: float,
    mean_well_spacing: float,
    map_extent: float,
) -> List[DirectionLineSpec]:
    """Fill missing radii / defaults for legacy direction attributes.

    Red-oval stretch target: corridor width scales with line length / map so
    high-value bodies form a long belt, not a thin ribbon or well-centered blob.
    """
    base_search = max(float(search_radius), 1.0)
    spacing = max(float(mean_well_spacing), base_search * 0.15, 1.0)
    map_e = max(float(map_extent), base_search, 1.0)
    resolved: List[DirectionLineSpec] = []
    for spec in specs:
        if not spec.active or len(spec.points) < 2:
            continue
        # Strong default stretch (Surfer-style elongated corridor)
        ratio = max(float(spec.ratio), 1.0)
        line_len = max(_polyline_length(spec.points), spacing, 1.0)
        # Compact full-strength core plus a broad, smoothly decaying belt.
        auto_core = max(
            base_search * 0.65,
            line_len * 0.12,
            spacing * 1.05,
        )
        auto_core = min(auto_core, map_e * 0.16, line_len * 0.20)
        auto_influence = max(
            auto_core * 3.2,
            spacing * 3.2,
            base_search * 1.45,
            line_len * 0.30,
        )
        auto_influence = min(auto_influence, map_e * 0.38, line_len * 0.48)

        influence_explicit = float(spec.influence_radius) > 0.0
        core_explicit = float(spec.core_radius) > 0.0
        influence = float(spec.influence_radius) if influence_explicit else auto_influence
        core = float(spec.core_radius) if core_explicit else auto_core
        if influence_explicit and not core_explicit:
            core = min(auto_core, max(influence * 0.55, influence * 0.4))
        # Keep core ≤ influence; prefer shrinking core over inflating influence
        # when the user (or shapefile attrs) set a tight influence radius.
        if core > influence:
            if influence_explicit and not core_explicit:
                core = max(influence * 0.5, min(core, influence * 0.85))
            elif influence_explicit and core_explicit:
                core = min(core, influence * 0.95)
            else:
                influence = max(influence, core * 1.05)
        # Final guard
        core = max(min(core, influence * 0.99), 0.0)
        influence = max(influence, core + 1e-6)
        transition = float(spec.transition)
        if transition <= 0.0:
            transition = max(influence - core, max(core * 0.2, 1e-6))
        extend_mode = str(spec.extend_mode or "auto").strip().lower()
        if extend_mode not in {"auto", "none", "tangent"}:
            extend_mode = "auto"
        resolved.append(
            DirectionLineSpec(
                line_id=str(spec.line_id),
                points=tuple(spec.points),
                active=True,
                ratio=ratio,
                influence_radius=influence,
                priority=int(spec.priority) if int(spec.priority) > 0 else 1,
                core_radius=core,
                zone_id=str(spec.zone_id or ""),
                extend_mode=extend_mode,
                transition=transition,
            )
        )
    return resolved


def estimate_mean_well_spacing(xy: np.ndarray) -> float:
    """Nearest-neighbour mean spacing (O(N²) ok for typical well counts)."""
    if xy is None or len(xy) < 2:
        return 0.0
    pts = np.asarray(xy, dtype=float)
    n = len(pts)
    if n > 400:
        # Subsample for speed on huge sets
        rng = np.random.default_rng(0)
        idx = rng.choice(n, size=400, replace=False)
        pts = pts[idx]
        n = len(pts)
    nearest = np.full(n, np.inf, dtype=float)
    for i in range(n):
        d = np.hypot(pts[:, 0] - pts[i, 0], pts[:, 1] - pts[i, 1])
        d[i] = np.inf
        nearest[i] = float(np.min(d))
    finite = nearest[np.isfinite(nearest)]
    if finite.size == 0:
        return 0.0
    return float(np.mean(finite))


def build_polyline_geometry(
    spec: DirectionLineSpec,
    *,
    index: int = 0,
    extend_distance: float = 0.0,
) -> PolylineGeometry:
    """Build arc-length geometry, optionally extending ends along end tangents."""
    raw = [(float(p[0]), float(p[1])) for p in spec.points]
    # Deduplicate consecutive duplicates
    cleaned: List[PointTuple] = [raw[0]]
    for p in raw[1:]:
        if math.hypot(p[0] - cleaned[-1][0], p[1] - cleaned[-1][1]) > 1e-12:
            cleaned.append(p)
    if len(cleaned) < 2:
        pts = np.asarray(cleaned + cleaned, dtype=float)
        return PolylineGeometry(
            line_id=spec.line_id,
            points=pts,
            cumlen=np.zeros(len(pts), dtype=float),
            total_length=0.0,
            ratio=float(spec.ratio),
            core_radius=float(spec.core_radius),
            influence_radius=float(spec.influence_radius),
            priority=int(spec.priority),
            zone_id=str(spec.zone_id or ""),
            extend_mode=str(spec.extend_mode),
            transition=float(spec.transition),
            s_start=0.0,
            s_end=0.0,
            index=index,
        )

    extend = max(float(extend_distance), 0.0)
    if str(spec.extend_mode).lower() in {"auto", "tangent"} and extend > 0.0:
        # Extend start backward along first tangent
        t0x, t0y = _unit(cleaned[1][0] - cleaned[0][0], cleaned[1][1] - cleaned[0][1])
        start_ext = (cleaned[0][0] - t0x * extend, cleaned[0][1] - t0y * extend)
        # Extend end forward along last tangent
        t1x, t1y = _unit(cleaned[-1][0] - cleaned[-2][0], cleaned[-1][1] - cleaned[-2][1])
        end_ext = (cleaned[-1][0] + t1x * extend, cleaned[-1][1] + t1y * extend)
        chain = [start_ext] + cleaned + [end_ext]
        s_start = extend
    else:
        chain = cleaned
        s_start = 0.0

    pts = np.asarray(chain, dtype=float)
    cum = np.zeros(len(pts), dtype=float)
    for i in range(1, len(pts)):
        cum[i] = cum[i - 1] + math.hypot(pts[i, 0] - pts[i - 1, 0], pts[i, 1] - pts[i - 1, 1])
    total = float(cum[-1])
    s_end = total - (extend if str(spec.extend_mode).lower() in {"auto", "tangent"} and extend > 0.0 else 0.0)
    return PolylineGeometry(
        line_id=spec.line_id,
        points=pts,
        cumlen=cum,
        total_length=total,
        ratio=float(spec.ratio),
        core_radius=float(spec.core_radius),
        influence_radius=float(spec.influence_radius),
        priority=int(spec.priority),
        zone_id=str(spec.zone_id or ""),
        extend_mode=str(spec.extend_mode),
        transition=float(spec.transition),
        s_start=float(s_start),
        s_end=float(s_end),
        index=index,
    )


def project_point_to_polyline(pt: PointTuple, geom: PolylineGeometry) -> Tuple[float, float, float, float, float]:
    """Return (s, n_signed, tx, ty, dist_to_polyline) for the nearest projection."""
    px, py = float(pt[0]), float(pt[1])
    pts = geom.points
    cum = geom.cumlen
    best_dist = float("inf")
    best = (0.0, 0.0, 1.0, 0.0, float("inf"))
    for i in range(len(pts) - 1):
        ax, ay = float(pts[i, 0]), float(pts[i, 1])
        bx, by = float(pts[i + 1, 0]), float(pts[i + 1, 1])
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-24:
            continue
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
        cx = ax + t * dx
        cy = ay + t * dy
        dist = math.hypot(px - cx, py - cy)
        if dist < best_dist:
            best_dist = dist
            length = math.sqrt(length_sq)
            tx, ty = dx / length, dy / length
            # Signed normal: left of direction is positive
            n_signed = (px - cx) * (-ty) + (py - cy) * tx
            s = float(cum[i]) + t * length
            best = (s, n_signed, tx, ty, dist)
    return best


def influence_strength(
    dist_to_line: float,
    core_radius: float,
    influence_radius: float,
    transition: float = 0.0,
    *,
    exp_k: float = 3.0,
) -> float:
    """Perpendicular envelope: g=1 inside core; **exponential** decay core→influence.

    exp_k controls how fast influence drops off the axis (larger = stays high
    longer near core, then falls faster — non-linear belt like user red lines).
    """
    d = abs(float(dist_to_line))
    core = max(float(core_radius), 0.0)
    inf = max(float(influence_radius), core + 1e-9)
    if d <= core:
        return 1.0
    if d >= inf:
        return 0.0
    # Normalized distance in (0,1] across the annulus
    t = (d - core) / max(inf - core, 1e-9)
    t = max(0.0, min(1.0, t))
    k = max(float(exp_k), 0.5)
    # Exponential falloff: e^{-k t} mapped so t=0 → 1, t=1 → 0
    # g = (e^{-k t} - e^{-k}) / (1 - e^{-k})
    e_k = math.exp(-k)
    g = (math.exp(-k * t) - e_k) / max(1.0 - e_k, 1e-12)
    return float(max(0.0, min(1.0, g)))


def along_track_envelope(
    s: float,
    s_start: float,
    s_end: float,
    *,
    tip_length: float = 0.0,
    extend_mode: str = "auto",
) -> float:
    """Along-line envelope: full strength on the whole polyline span [s_start, s_end].

    User requirement: stretch corridor length ≈ direction-line start→end length.
    Outside the original span, only a short tip taper is allowed (extend_mode).
    """
    s0 = float(min(s_start, s_end))
    s1 = float(max(s_start, s_end))
    ss = float(s)
    if s0 - 1e-9 <= ss <= s1 + 1e-9:
        return 1.0
    mode = str(extend_mode or "auto").strip().lower()
    if mode in {"none", "off", "0", "false"}:
        return 0.0
    tip = max(float(tip_length), 0.0)
    if tip <= 1e-12:
        # Default tip ≈ 10% of line length (capped later by caller)
        tip = max(0.1 * (s1 - s0), 1e-6)
    if ss < s0:
        t = (s0 - ss) / tip
    else:
        t = (ss - s1) / tip
    if t >= 1.0:
        return 0.0
    t = max(0.0, min(1.0, t))
    return float(1.0 - t * t * (3.0 - 2.0 * t))


def combined_influence(
    dist_to_line: float,
    s: float,
    geom: "PolylineGeometry",
    *,
    tip_length: float = 0.0,
) -> float:
    """g = g_perp × g_along  — full stretch along entire direction-line length."""
    g_perp = influence_strength(
        dist_to_line, geom.core_radius, geom.influence_radius, geom.transition
    )
    if g_perp <= 1e-12:
        return 0.0
    tip = tip_length
    if tip <= 0.0:
        tip = max(
            0.12 * max(float(geom.s_end) - float(geom.s_start), 1.0),
            float(geom.core_radius) * 0.35,
            1.0,
        )
    g_along = along_track_envelope(
        s,
        geom.s_start,
        geom.s_end,
        tip_length=tip,
        extend_mode=geom.extend_mode,
    )
    return float(g_perp * g_along)


def build_along_track_well_profiles(
    well_xy: np.ndarray,
    well_values: np.ndarray,
    well_coords: Dict[int, Dict[str, np.ndarray]],
    geoms: Sequence[PolylineGeometry],
    *,
    min_g: float = 0.15,
) -> Dict[int, Tuple[np.ndarray, np.ndarray]]:
    """For each direction line, collect wells on the corridor as (s, value) samples.

    Used to extend high values along the full polyline from start→end (including
    empty segments beyond the outermost wells).
    """
    profiles: Dict[int, Tuple[np.ndarray, np.ndarray]] = {}
    n_wells = len(well_xy)
    for geom in geoms:
        wc = well_coords.get(int(geom.index))
        if wc is None:
            continue
        ss: List[float] = []
        zz: List[float] = []
        for i in range(n_wells):
            if not bool(wc["valid"][i]):
                continue
            if float(wc["g"][i]) < float(min_g):
                continue
            # Near-axis wells define the transported local-value profile.
            # Keep unrelated flank wells out of the transported axis profile.
            n_lim = max(
                min(float(geom.core_radius) * 0.46, float(geom.influence_radius) * 0.22),
                float(geom.core_radius) * 0.24,
                1.0,
            )
            if abs(float(wc["n"][i])) > n_lim:
                continue
            val = float(well_values[i])
            if not math.isfinite(val):
                continue
            ss.append(float(wc["s"][i]))
            zz.append(val)
        if not ss:
            continue
        order = np.argsort(np.asarray(ss, dtype=float))
        s_arr = np.asarray(ss, dtype=float)[order]
        z_arr = np.asarray(zz, dtype=float)[order]
        # Merge near-duplicate s — median resists flank outliers
        s_m: List[float] = []
        z_m: List[float] = []
        bucket_s = float(s_arr[0])
        bucket_z = [float(z_arr[0])]
        merge_eps = max(float(geom.core_radius) * 0.05, 1.0)
        for k in range(1, len(s_arr)):
            if abs(float(s_arr[k]) - bucket_s) <= merge_eps:
                bucket_z.append(float(z_arr[k]))
            else:
                s_m.append(bucket_s)
                z_m.append(float(np.median(np.asarray(bucket_z, dtype=float))))
                bucket_s = float(s_arr[k])
                bucket_z = [float(z_arr[k])]
        s_m.append(bucket_s)
        z_m.append(float(np.median(np.asarray(bucket_z, dtype=float))))

        # HARD RULE: ridge always reaches direction-line tips (start & end).
        # Pin anchors at original polyline ends so stretch is not cut mid-line.
        s_tip0 = float(min(geom.s_start, geom.s_end))
        s_tip1 = float(max(geom.s_start, geom.s_end))
        z_lo = float(z_m[0])
        z_hi = float(z_m[-1])
        # Each tip inherits its nearest local value. This preserves low troughs
        # as well as high ridges.
        s_full = [s_tip0] + s_m + [s_tip1]
        z_full = [z_lo] + z_m + [z_hi]
        profiles[int(geom.index)] = (
            np.asarray(s_full, dtype=float),
            np.asarray(z_full, dtype=float),
        )
    return profiles


def sample_along_track_value(
    s: float,
    n: float,
    profile_s: np.ndarray,
    profile_z: np.ndarray,
    geom: PolylineGeometry,
    *,
    extrapolate: str = "constant",
) -> Optional[float]:
    """1D ridge value along polyline station s for the full line span.

    - Between wells: linear interpolation in s
    - Beyond outermost wells toward line start/end: constant (or soft) extrapolation
    - Perpendicular n is handled by the caller via g_perp weighting
    """
    if profile_s is None or len(profile_s) == 0:
        return None

    ss = float(s)
    s_arr = np.asarray(profile_s, dtype=float)
    z_arr = np.asarray(profile_z, dtype=float)
    s_lo = float(s_arr[0])
    s_hi = float(s_arr[-1])

    if len(s_arr) == 1:
        if str(extrapolate).lower() in {"none", "off"}:
            return float(z_arr[0]) if abs(ss - s_lo) < 1e-6 else None
        return float(z_arr[0])

    if ss < s_lo:
        if str(extrapolate).lower() in {"none", "off"}:
            return None
        return float(z_arr[0])  # toward line start (empty west of wells)
    if ss > s_hi:
        if str(extrapolate).lower() in {"none", "off"}:
            return None
        return float(z_arr[-1])  # toward line end

    # Between wells: linear in s (red-oval spine continuity)
    for i in range(len(s_arr) - 1):
        a, b = float(s_arr[i]), float(s_arr[i + 1])
        if a - 1e-12 <= ss <= b + 1e-12 or b - 1e-12 <= ss <= a + 1e-12:
            if abs(b - a) <= 1e-12:
                return float(z_arr[i])
            t = (ss - a) / (b - a)
            t = max(0.0, min(1.0, t))
            return float(z_arr[i]) * (1.0 - t) + float(z_arr[i + 1]) * t
    # Fallback nearest
    j = int(np.argmin(np.abs(s_arr - ss)))
    return float(z_arr[j])


def _interp_profile_vectorized(
    s_cells: np.ndarray,
    profile_s: np.ndarray,
    profile_z: np.ndarray,
) -> np.ndarray:
    """np.interp with constant extrapolation past profile ends."""
    ps = np.asarray(profile_s, dtype=float)
    pz = np.asarray(profile_z, dtype=float)
    if ps.size == 0:
        return np.full(s_cells.shape, np.nan, dtype=float)
    if ps.size == 1:
        return np.full(s_cells.shape, float(pz[0]), dtype=float)
    # Ensure increasing for np.interp
    order = np.argsort(ps)
    ps = ps[order]
    pz = pz[order]
    return np.interp(np.asarray(s_cells, dtype=float), ps, pz, left=float(pz[0]), right=float(pz[-1]))


def blend_corridor_along_track(
    grid_z: np.ndarray,
    direction_cache: Dict[str, np.ndarray],
    geoms: Sequence[PolylineGeometry],
    profiles: Dict[int, Tuple[np.ndarray, np.ndarray]],
    domain_mask: np.ndarray,
    *,
    blend_strength: float = 0.99,
    min_cell_g: float = 0.05,
    exp_k: float = 6.0,
) -> Tuple[np.ndarray, Dict[str, float]]:
    """Blend IDW/Kriging with 1D ridge — vectorized + **exponential** weights.

    User red-corridor: wide belt along direction line; empty west of wells
    pulled strongly toward the ridge with non-linear (exponential) alpha.
    """
    stats = {
        "along_track_cells": 0.0,
        "along_track_profiles": float(len(profiles)),
        "along_track_blend_strength": float(blend_strength),
        "along_track_exp_k": float(exp_k),
    }
    if not profiles or direction_cache is None or grid_z.size == 0:
        return grid_z, stats

    out = np.array(grid_z, dtype=float, copy=True)
    g_arr = np.asarray(direction_cache["g"], dtype=float)
    s_arr = np.asarray(direction_cache["s"], dtype=float)
    n_arr = np.asarray(direction_cache["n"], dtype=float)
    dir_idx = np.asarray(direction_cache["dir_index"], dtype=np.int32)
    domain = np.asarray(domain_mask, dtype=bool)
    strength = max(0.0, min(1.0, float(blend_strength)))
    min_g = float(min_cell_g)
    k_exp = max(float(exp_k), 0.5)

    geom_by_idx = {int(g.index): g for g in geoms}
    total_cells = 0

    for di, (ps, pz) in profiles.items():
        geom = geom_by_idx.get(int(di))
        if geom is None:
            continue
        # Wider selection: use lower g floor so red-corridor flanks participate
        sel = domain & (dir_idx == int(di)) & (g_arr >= min_g)
        if not np.any(sel):
            continue

        s_cells = s_arr[sel]
        n_cells = n_arr[sel]
        g_cells = g_arr[sel]
        base = out[sel]

        # Along-track envelope (full line span start→end)
        s0 = float(min(geom.s_start, geom.s_end))
        s1 = float(max(geom.s_start, geom.s_end))
        tip = max(float(geom.core_radius) * 0.65, float(geom.influence_radius) * 0.20, 1.0)
        inside = (s_cells >= s0 - 1e-9) & (s_cells <= s1 + 1e-9)
        g_along = np.zeros(s_cells.shape, dtype=float)
        g_along[inside] = 1.0
        mode = str(geom.extend_mode or "auto").strip().lower()
        if mode not in {"none", "off", "0", "false"}:
            left = s_cells < s0
            right = s_cells > s1
            if np.any(left):
                t = np.clip((s0 - s_cells[left]) / tip, 0.0, 1.0)
                # exponential tip fade
                e_k = math.exp(-k_exp)
                g_along[left] = (np.exp(-k_exp * t) - e_k) / max(1.0 - e_k, 1e-12)
                g_along[left] = np.where(t >= 1.0, 0.0, np.clip(g_along[left], 0.0, 1.0))
            if np.any(right):
                t = np.clip((s_cells[right] - s1) / tip, 0.0, 1.0)
                e_k = math.exp(-k_exp)
                g_along[right] = (np.exp(-k_exp * t) - e_k) / max(1.0 - e_k, 1e-12)
                g_along[right] = np.where(t >= 1.0, 0.0, np.clip(g_along[right], 0.0, 1.0))

        # Perp envelope — exponential (matches influence_strength); keep core fat
        n_abs = np.abs(n_cells)
        core = max(float(geom.core_radius), 1e-9)
        inf = max(float(geom.influence_radius), core + 1e-9)
        g_perp = np.ones(n_abs.shape, dtype=float)
        mid = (n_abs > core) & (n_abs < inf)
        g_perp[n_abs >= inf] = 0.0
        if np.any(mid):
            t = np.clip((n_abs[mid] - core) / max(inf - core, 1e-9), 0.0, 1.0)
            # Milder mid-annulus decay so belt stays thick (lower effective k)
            k_perp = max(k_exp * 0.65, 2.0)
            e_k = math.exp(-k_perp)
            g_perp[mid] = (np.exp(-k_perp * t) - e_k) / max(1.0 - e_k, 1e-12)
            g_perp[mid] = np.clip(g_perp[mid], 0.0, 1.0)

        # Soft axis weight (wide belt for red-corridor)
        axis_w = np.maximum(0.0, 1.0 - (n_abs / (core * 1.65)) ** 2)
        use = (g_along > 1e-9) & (g_perp > 1e-9)
        if not np.any(use):
            continue

        v_along = _interp_profile_vectorized(s_cells, ps, pz)

        # Aggressive symmetric mix toward the local along-track profile.
        w_lin = np.clip(g_cells * g_along * (0.30 * axis_w + 0.70 * g_perp), 0.0, 1.0)
        changed = (np.abs(v_along - base) > 1e-9) & np.isfinite(base)
        w_lin = np.where(changed, np.clip(w_lin * 1.45 + 0.24, 0.0, 1.0), w_lin)
        raw = 1.0 - np.exp(-k_exp * strength * (1.05 + 2.8 * w_lin))
        raw_max = 1.0 - math.exp(-k_exp * strength * (1.05 + 2.8))
        alpha = np.clip(raw / max(raw_max, 1e-12) * 0.995, 0.0, 0.995)
        on_span = (s_cells >= s0 - 1e-9) & (s_cells <= s1 + 1e-9)
        on_core = on_span & (n_abs <= core)
        on_corridor = on_span & (g_perp >= 0.10)
        # Full-strength axis reaches both direction-line tips.
        alpha = np.where(on_corridor & use, np.maximum(alpha, 0.78 * strength), alpha)
        alpha = np.where(on_core & use, np.maximum(alpha, 0.995 * strength), alpha)
        alpha = np.where(use, np.clip(alpha, 0.0, 0.995), 0.0)

        new_vals = np.array(base, dtype=float, copy=True)
        finite_base = np.isfinite(base)
        fill = use & ~finite_base & (g_perp > 0.08)
        blend = use & finite_base & (alpha > 1e-6)
        new_vals[fill] = v_along[fill]
        new_vals[blend] = (1.0 - alpha[blend]) * base[blend] + alpha[blend] * v_along[blend]
        apply = fill | blend
        if np.any(apply):
            layer = np.array(out, dtype=float, copy=True)
            vals = layer[sel]
            vals[apply] = new_vals[apply]
            layer[sel] = vals
            out = layer
            total_cells += int(np.count_nonzero(apply))

    stats["along_track_cells"] = float(total_cells)
    return out, stats


def curve_distance_sq(
    s0: float,
    n0: float,
    s1: float,
    n1: float,
    ratio: float,
    *,
    exp_aniso: float = 1.0,
) -> float:
    """Curve-coordinate distance with optional exponential anisotropy.

    exp_aniso > 1 makes along-axis even "closer" non-linearly (stronger stretch).
    """
    a = max(float(ratio), 1.0)
    if float(exp_aniso) > 1.0 + 1e-9:
        a = a ** float(exp_aniso)
    ds = (float(s0) - float(s1)) / a
    dn = float(n0) - float(n1)
    return ds * ds + dn * dn


def blend_effective_distance(
    euclidean: float,
    curve_dist: float,
    g_pair: float,
) -> float:
    """d_eff² = (1-g) d_euc² + g d_curve².

    When g is high (on corridor), bias even more toward pure curve distance so
    the stretch is not washed out by residual Euclidean blending.
    """
    g = max(0.0, min(1.0, float(g_pair)))
    # Emphasize curve metric once on the corridor (Surfer-like elongation)
    if g >= 0.25:
        g = min(1.0, 0.70 + 0.30 * g)
    de2 = float(euclidean) * float(euclidean)
    dc2 = float(curve_dist) * float(curve_dist)
    return math.sqrt(max((1.0 - g) * de2 + g * dc2, 0.0))


def elliptical_search_accept(
    s0: float,
    n0: float,
    s1: float,
    n1: float,
    ratio: float,
    base_radius: float,
    g_pair: float,
    euclidean: float,
    *,
    line_length: float = 0.0,
) -> bool:
    """Accept well if inside stretched ellipse (curve axes) or Euclidean when g=0.

    When under strong direction control, R_parallel is expanded so wells along
    the full direction-line length can participate (not only local search radius).
    """
    r = max(float(base_radius), 1e-9)
    g = max(0.0, min(1.0, float(g_pair)))
    if g <= 1e-9:
        return float(euclidean) <= r
    a = max(float(ratio), 1.0)
    # Along-track reach must cover the full direction-line length so wells at
    # either end of the blue axis can influence cells anywhere on the corridor.
    r_par = r * (1.0 + g * (a - 1.0) * 1.15)
    if line_length > 0.0:
        # Full span (+20% margin) when under direction control
        r_par = max(r_par, g * float(line_length) * 1.20, float(line_length) * 1.05 * g)
    r_par = max(r_par, r * a * max(g, 0.85))  # ensure ratio*R along-track when g high
    r_perp = r  # perpendicular stays at base search radius
    ds = abs(float(s0) - float(s1))
    dn = abs(float(n0) - float(n1))
    # Ellipse acceptance in curve coords
    if (ds / max(r_par, 1e-9)) ** 2 + (dn / max(r_perp, 1e-9)) ** 2 <= 1.0:
        return True
    # Fallback: still allow pure Euclidean within base radius for low g
    if g < 0.35 and float(euclidean) <= r:
        return True
    return False


# ---------------------------------------------------------------------------
# Direction field (grid cache)
# ---------------------------------------------------------------------------


def build_direction_geometries(
    specs: Sequence[DirectionLineSpec],
    *,
    search_radius: float,
    mean_well_spacing: float,
    map_extent: float,
) -> List[PolylineGeometry]:
    resolved = resolve_direction_params(
        specs,
        search_radius=search_radius,
        mean_well_spacing=mean_well_spacing,
        map_extent=map_extent,
    )
    geoms: List[PolylineGeometry] = []
    for i, spec in enumerate(resolved):
        # auto extension: min(A * R_base, influence, 0.35 * map_extent)
        a = max(float(spec.ratio), 1.0)
        r_base = max(float(search_radius), 1.0)
        if str(spec.extend_mode).lower() in {"auto", "tangent"}:
            extend = min(a * r_base, float(spec.influence_radius), max(map_extent * 0.35, r_base))
        else:
            extend = 0.0
        geoms.append(build_polyline_geometry(spec, index=i, extend_distance=extend))
    return geoms


def project_points_batch(
    xy: np.ndarray,
    geoms: Sequence[PolylineGeometry],
) -> List[List[Optional[PointCurveCoord]]]:
    """For each point, project onto every direction line.

    Returns list (n_points) of list (n_dirs) of PointCurveCoord or None if far.
    """
    pts = np.asarray(xy, dtype=float)
    out: List[List[Optional[PointCurveCoord]]] = []
    for i in range(len(pts)):
        row: List[Optional[PointCurveCoord]] = []
        p = (float(pts[i, 0]), float(pts[i, 1]))
        for geom in geoms:
            s, n, tx, ty, dist = project_point_to_polyline(p, geom)
            g = combined_influence(dist, s, geom)
            if g <= 1e-9:
                row.append(None)
            else:
                row.append(
                    PointCurveCoord(
                        dir_index=geom.index,
                        s=s,
                        n=n,
                        tx=tx,
                        ty=ty,
                        g=g,
                        ratio=geom.ratio,
                        distance=dist,
                    )
                )
        out.append(row)
    return out


def pick_controlling_direction(
    candidates: Sequence[Optional[PointCurveCoord]],
    geoms: Sequence[PolylineGeometry],
    *,
    allowed_dir_indices: Optional[Sequence[int]] = None,
) -> Optional[PointCurveCoord]:
    """Highest influence score wins: score = g * (1 + 0.05*priority_boost) / (1+dist)."""
    best: Optional[PointCurveCoord] = None
    best_score = -1.0
    allowed = None if allowed_dir_indices is None else set(int(i) for i in allowed_dir_indices)
    for coord in candidates:
        if coord is None:
            continue
        if allowed is not None and int(coord.dir_index) not in allowed:
            continue
        geom = geoms[coord.dir_index]
        # Lower priority number = higher rank (consistent with BarrierLine)
        prio_boost = 1.0 / max(float(geom.priority), 1.0)
        score = float(coord.g) * (1.0 + 0.15 * prio_boost) / (1.0 + float(coord.distance) / max(geom.influence_radius, 1.0))
        if score > best_score:
            best_score = score
            best = coord
    return best


def dual_angle_blend_tangent(
    a: PointCurveCoord,
    b: PointCurveCoord,
) -> Tuple[float, float, float, float]:
    """Blend two tangents using dual-angle (2θ) vectors to avoid 0°/180° cancel.

    Returns (tx, ty, g_blend, ratio_blend).
    """
    # Represent direction as angle * 2
    ang_a = math.atan2(a.ty, a.tx)
    ang_b = math.atan2(b.ty, b.tx)
    wa = max(float(a.g), 1e-9)
    wb = max(float(b.g), 1e-9)
    cx = wa * math.cos(2.0 * ang_a) + wb * math.cos(2.0 * ang_b)
    cy = wa * math.sin(2.0 * ang_a) + wb * math.sin(2.0 * ang_b)
    ang2 = math.atan2(cy, cx)
    ang = 0.5 * ang2
    tx, ty = math.cos(ang), math.sin(ang)
    g = max(a.g, b.g)
    # Prefer higher-g ratio
    if a.g >= b.g:
        ratio = a.ratio
    else:
        ratio = b.ratio
    return tx, ty, g, ratio


def build_grid_direction_cache(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    domain_mask: np.ndarray,
    geoms: Sequence[PolylineGeometry],
    *,
    blend_width: float = 0.0,
) -> Dict[str, np.ndarray]:
    """Precompute per-cell controlling direction attributes.

    Returns dict with arrays:
      dir_index (int32, -1 none), s, n, tx, ty, g, ratio, stretch
    and optionally second-best for blend: dir_index2, g2, tx2, ty2, ratio2, s2, n2
    """
    rows = len(grid_y)
    cols = len(grid_x)
    dir_index = np.full((rows, cols), -1, dtype=np.int32)
    s_arr = np.zeros((rows, cols), dtype=float)
    n_arr = np.zeros((rows, cols), dtype=float)
    tx = np.zeros((rows, cols), dtype=float)
    ty = np.zeros((rows, cols), dtype=float)
    g_arr = np.zeros((rows, cols), dtype=float)
    ratio = np.ones((rows, cols), dtype=float)
    # secondary for dual-angle blend at junctions
    dir_index2 = np.full((rows, cols), -1, dtype=np.int32)
    g2 = np.zeros((rows, cols), dtype=float)
    tx2 = np.zeros((rows, cols), dtype=float)
    ty2 = np.zeros((rows, cols), dtype=float)
    ratio2 = np.ones((rows, cols), dtype=float)
    s2 = np.zeros((rows, cols), dtype=float)
    n2 = np.zeros((rows, cols), dtype=float)

    if not geoms:
        return {
            "dir_index": dir_index,
            "s": s_arr,
            "n": n_arr,
            "tx": tx,
            "ty": ty,
            "g": g_arr,
            "ratio": ratio,
            "stretch": np.ones((rows, cols), dtype=float),
            "dir_index2": dir_index2,
            "g2": g2,
            "tx2": tx2,
            "ty2": ty2,
            "ratio2": ratio2,
            "s2": s2,
            "n2": n2,
        }

    # Only visit domain cells (much faster than full rows×cols scan)
    multi_dir = len(geoms) >= 2
    rr, cc = np.nonzero(domain_mask)
    for r, c in zip(rr.tolist(), cc.tolist()):
        p = (float(grid_x[c]), float(grid_y[r]))
        best_score = -1.0
        best: Optional[PointCurveCoord] = None
        second: Optional[PointCurveCoord] = None
        second_score = -1.0
        for geom in geoms:
            s, n_signed, txx, tyy, dist = project_point_to_polyline(p, geom)
            g = combined_influence(dist, s, geom)
            if g <= 1e-9:
                continue
            prio_boost = 1.0 / max(float(geom.priority), 1.0)
            score = g * (1.0 + 0.15 * prio_boost) / (1.0 + dist / max(geom.influence_radius, 1.0))
            coord = PointCurveCoord(
                dir_index=geom.index,
                s=s,
                n=n_signed,
                tx=txx,
                ty=tyy,
                g=g,
                ratio=geom.ratio,
                distance=dist,
            )
            if score > best_score:
                second, second_score = best, best_score
                best, best_score = coord, score
            elif multi_dir and score > second_score:
                second, second_score = coord, score
        if best is None:
            continue
        dir_index[r, c] = int(best.dir_index)
        s_arr[r, c] = best.s
        n_arr[r, c] = best.n
        tx[r, c] = best.tx
        ty[r, c] = best.ty
        g_arr[r, c] = best.g
        ratio[r, c] = best.ratio

        # Dual-angle blend only when 2+ direction lines compete
        if multi_dir and second is not None and second.g > 0.15 and best.g > 0.15:
            g_a = geoms[best.dir_index]
            g_b = geoms[second.dir_index]
            zone_ok = (not g_a.zone_id) or (not g_b.zone_id) or (g_a.zone_id == g_b.zone_id)
            close = abs(best_score - second_score) <= max(0.15 * best_score, 1e-6)
            if zone_ok and close:
                btx, bty, bg, br = dual_angle_blend_tangent(best, second)
                tx[r, c] = btx
                ty[r, c] = bty
                dir_index2[r, c] = int(second.dir_index)
                g2[r, c] = second.g
                tx2[r, c] = second.tx
                ty2[r, c] = second.ty
                ratio2[r, c] = second.ratio
                s2[r, c] = second.s
                n2[r, c] = second.n
                g_arr[r, c] = max(best.g, second.g * 0.85)
                ratio[r, c] = br

    stretch = 1.0 + (ratio - 1.0) * g_arr
    return {
        "dir_index": dir_index,
        "s": s_arr,
        "n": n_arr,
        "tx": tx,
        "ty": ty,
        "g": g_arr,
        "ratio": ratio,
        "stretch": stretch,
        "dir_index2": dir_index2,
        "g2": g2,
        "tx2": tx2,
        "ty2": ty2,
        "ratio2": ratio2,
        "s2": s2,
        "n2": n2,
    }


def build_legacy_direction_field(cache: Dict[str, np.ndarray]) -> np.ndarray:
    """3-channel field (tx, ty, stretch) compatible with existing smooth/fill code."""
    rows, cols = cache["g"].shape
    field = np.zeros((rows, cols, 3), dtype=float)
    field[:, :, 0] = cache["tx"]
    field[:, :, 1] = cache["ty"]
    field[:, :, 2] = np.maximum(cache["stretch"], 1.0)
    # Zero-out cells without influence
    mask = cache["g"] <= 1e-9
    field[mask, 0] = 0.0
    field[mask, 1] = 0.0
    field[mask, 2] = 1.0
    return field


def precompute_well_curve_coords(
    well_xy: np.ndarray,
    geoms: Sequence[PolylineGeometry],
) -> Dict[int, Dict[str, np.ndarray]]:
    """Per-direction well projections: dict[dir_index] -> {s,n,g,tx,ty,valid}."""
    n_wells = len(well_xy)
    result: Dict[int, Dict[str, np.ndarray]] = {}
    for geom in geoms:
        s = np.zeros(n_wells, dtype=float)
        n = np.zeros(n_wells, dtype=float)
        g = np.zeros(n_wells, dtype=float)
        tx = np.zeros(n_wells, dtype=float)
        ty = np.zeros(n_wells, dtype=float)
        valid = np.zeros(n_wells, dtype=bool)
        for i in range(n_wells):
            p = (float(well_xy[i, 0]), float(well_xy[i, 1]))
            ss, nn, txx, tyy, dist = project_point_to_polyline(p, geom)
            gg = combined_influence(dist, ss, geom)
            s[i] = ss
            n[i] = nn
            g[i] = gg
            tx[i] = txx
            ty[i] = tyy
            valid[i] = gg > 1e-9
        result[geom.index] = {
            "s": s,
            "n": n,
            "g": g,
            "tx": tx,
            "ty": ty,
            "valid": valid,
            "ratio": float(geom.ratio),
            "zone_id": str(geom.zone_id or ""),
            "line_length": float(max(geom.s_end - geom.s_start, geom.total_length, 0.0)),
        }
    return result


def _blend_effective_distance_vec(
    euclidean: np.ndarray,
    curve_dist: np.ndarray,
    g_pair: np.ndarray,
) -> np.ndarray:
    g = np.clip(g_pair, 0.0, 1.0)
    g = np.where(g >= 0.25, np.minimum(1.0, 0.70 + 0.30 * g), g)
    de2 = euclidean * euclidean
    dc2 = curve_dist * curve_dist
    return np.sqrt(np.maximum((1.0 - g) * de2 + g * dc2, 0.0))


def _elliptical_search_accept_vec(
    s0: float,
    n0: float,
    s1: np.ndarray,
    n1: np.ndarray,
    ratio: float,
    base_radius: float,
    g_pair: np.ndarray,
    euclidean: np.ndarray,
    *,
    line_length: float = 0.0,
) -> np.ndarray:
    r = max(float(base_radius), 1e-9)
    g = np.clip(np.asarray(g_pair, dtype=float), 0.0, 1.0)
    a = max(float(ratio), 1.0)
    r_par = r * (1.0 + g * (a - 1.0) * 1.15)
    if line_length > 0.0:
        r_par = np.maximum(
            r_par,
            np.maximum(g * float(line_length) * 1.20, float(line_length) * 1.05 * g),
        )
    r_par = np.maximum(r_par, r * a * np.maximum(g, 0.85))
    ds = np.abs(float(s0) - np.asarray(s1, dtype=float))
    dn = np.abs(float(n0) - np.asarray(n1, dtype=float))
    in_ellipse = (ds / np.maximum(r_par, 1e-9)) ** 2 + (dn / max(r, 1e-9)) ** 2 <= 1.0
    euc_ok = (g < 0.35) & (np.asarray(euclidean, dtype=float) <= r)
    low_g = g <= 1e-9
    return np.where(low_g, np.asarray(euclidean, dtype=float) <= r, in_ellipse | euc_ok)


def pairs_effective_distance(
    *,
    euclidean: np.ndarray,
    cell_dir: int,
    cell_s: float,
    cell_n: float,
    cell_g: float,
    cell_ratio: float,
    well_coords: Dict[int, Dict[str, np.ndarray]],
    geoms: Sequence[PolylineGeometry] | None = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Vectorized (d_eff, g_pair) for one cell against every well."""
    euc = np.asarray(euclidean, dtype=float)
    zeros = np.zeros(euc.shape, dtype=float)
    if int(cell_dir) < 0 or float(cell_g) <= 1e-9:
        return euc.copy(), zeros
    wc = well_coords.get(int(cell_dir))
    if wc is None:
        return euc.copy(), zeros
    valid = np.asarray(wc["valid"], dtype=bool)
    g_well = np.asarray(wc["g"], dtype=float)
    g_pair = np.where(valid, np.minimum(float(cell_g), g_well), 0.0)
    a = max(float(cell_ratio), float(wc["ratio"]), 1.0)
    ds = (float(cell_s) - np.asarray(wc["s"], dtype=float)) / a
    dn = float(cell_n) - np.asarray(wc["n"], dtype=float)
    d_curve = np.sqrt(np.maximum(ds * ds + dn * dn, 0.0))
    d_eff = _blend_effective_distance_vec(euc, d_curve, g_pair)
    inactive = g_pair <= 1e-9
    d_eff = np.where(inactive, euc, d_eff)
    g_pair = np.where(inactive, 0.0, g_pair)
    return d_eff, g_pair


def pairs_in_search_neighborhood(
    *,
    euclidean: np.ndarray,
    d_eff: np.ndarray,
    g_pair: np.ndarray,
    cell_s: float,
    cell_n: float,
    cell_ratio: float,
    cell_dir: int,
    well_coords: Dict[int, Dict[str, np.ndarray]],
    base_radius: float,
    use_extended_search: bool,
) -> np.ndarray:
    """Vectorized elliptical neighborhood test for one cell against every well."""
    r = max(float(base_radius), 1e-9)
    euc = np.asarray(euclidean, dtype=float)
    de = np.asarray(d_eff, dtype=float)
    gp = np.asarray(g_pair, dtype=float)
    fallback = euc <= r if not use_extended_search else de <= r
    if int(cell_dir) < 0:
        return fallback
    wc = well_coords.get(int(cell_dir))
    if wc is None:
        return euc <= r
    a = max(float(cell_ratio), float(wc["ratio"]), 1.0)
    if use_extended_search:
        in_nbhd = _elliptical_search_accept_vec(
            float(cell_s),
            float(cell_n),
            np.asarray(wc["s"], dtype=float),
            np.asarray(wc["n"], dtype=float),
            a,
            r,
            gp,
            euc,
            line_length=float(wc.get("line_length", 0.0) or 0.0),
        )
    else:
        in_nbhd = euc <= r
    return np.where(gp <= 1e-9, fallback, in_nbhd)


def pair_effective_distance(
    *,
    euclidean: float,
    cell_dir: int,
    cell_s: float,
    cell_n: float,
    cell_g: float,
    cell_ratio: float,
    well_index: int,
    well_coords: Dict[int, Dict[str, np.ndarray]],
    geoms: Sequence[PolylineGeometry],
) -> Tuple[float, float]:
    """Return (d_eff, g_pair) for a grid–well pair.

    Uses curve distance only when both points share the same controlling
    direction (or the well is valid under the cell's direction).
    """
    idx = int(well_index)
    d_eff, g_pair = pairs_effective_distance(
        euclidean=np.asarray([float(euclidean)]),
        cell_dir=int(cell_dir),
        cell_s=float(cell_s),
        cell_n=float(cell_n),
        cell_g=float(cell_g),
        cell_ratio=float(cell_ratio),
        well_coords=_well_coords_at(well_coords, idx),
        geoms=geoms,
    )
    return float(d_eff[0]), float(g_pair[0])


def pair_in_search_neighborhood(
    *,
    euclidean: float,
    d_eff: float,
    g_pair: float,
    cell_s: float,
    cell_n: float,
    cell_ratio: float,
    well_index: int,
    cell_dir: int,
    well_coords: Dict[int, Dict[str, np.ndarray]],
    base_radius: float,
    use_extended_search: bool,
) -> bool:
    """Elliptical neighborhood when under direction control."""
    idx = int(well_index)
    accepted = pairs_in_search_neighborhood(
        euclidean=np.asarray([float(euclidean)]),
        d_eff=np.asarray([float(d_eff)]),
        g_pair=np.asarray([float(g_pair)]),
        cell_s=float(cell_s),
        cell_n=float(cell_n),
        cell_ratio=float(cell_ratio),
        cell_dir=int(cell_dir),
        well_coords=_well_coords_at(well_coords, idx),
        base_radius=float(base_radius),
        use_extended_search=bool(use_extended_search),
    )
    return bool(accepted[0])


def _well_coords_at(
    well_coords: Dict[int, Dict[str, np.ndarray]], index: int
) -> Dict[int, Dict[str, np.ndarray]]:
    sliced: Dict[int, Dict[str, np.ndarray]] = {}
    for dir_index, wc in well_coords.items():
        entry: Dict[str, np.ndarray] = {}
        for key, value in wc.items():
            if isinstance(value, np.ndarray) and value.shape[:1] and value.shape[0] > index:
                entry[key] = value[index : index + 1]
            else:
                entry[key] = value
        sliced[dir_index] = entry
    return sliced


__all__ = [
    "DirectionLineSpec",
    "PolylineGeometry",
    "PointCurveCoord",
    "resolve_direction_params",
    "estimate_mean_well_spacing",
    "build_polyline_geometry",
    "project_point_to_polyline",
    "influence_strength",
    "along_track_envelope",
    "combined_influence",
    "build_along_track_well_profiles",
    "sample_along_track_value",
    "blend_corridor_along_track",
    "curve_distance_sq",
    "blend_effective_distance",
    "elliptical_search_accept",
    "build_direction_geometries",
    "project_points_batch",
    "pick_controlling_direction",
    "dual_angle_blend_tangent",
    "build_grid_direction_cache",
    "build_legacy_direction_field",
    "precompute_well_curve_coords",
    "pairs_effective_distance",
    "pairs_in_search_neighborhood",
    "pair_effective_distance",
    "pair_in_search_neighborhood",
]
