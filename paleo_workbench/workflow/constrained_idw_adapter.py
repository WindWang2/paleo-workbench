"""Haiyou constrained-IDW bridge — host owns the integration boundary.

This is the ONLY place in the workbench that imports the haiyou constrained-IDW
algorithm. It keeps the two engines independent: ``geo-viz-engine`` (kriging /
IDW / directional / spline) and the haiyou constrained-IDW algorithm never
import each other; the host adapts between the host data model and each
engine's input model.

The algorithm is *selectively vendored* under
``paleo_workbench/_vendored/haiyou_constrained_idw/`` (the pure-NumPy + optional
SciPy modules only; no Qt app shell). Vendoring — rather than a submodule — is
used because the upstream ``WWX9/haiyou-visualization`` is a private repo the
workbench build/release must not depend on (goal §14: the published artifact
runs without private-repo access). See ``ATTRIBUTION.md`` there for provenance.
The vendored package ``__init__`` files are Qt-free, so the bridge simply puts
the vendored root on :data:`sys.path` and imports the algorithm normally.

Public surface (host contract):

- :data:`CONSTRAINED_IDW_ENGINE_LABEL` — UI/engine method id.
- :func:`run_constrained_idw` — mirrors the ``interpolate_factor_grid`` output
  dict contract so downstream task / preview / contour / catalog plumbing is
  method-agnostic.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from paleo_workbench.workflow.constraints import (
    break_polylines_for_idw,
    direction_line_params,
)

#: Engine/backend identifier used in the result dict (``backend`` field) and as
#: the routed method name in :data:`METHOD_LABEL_TO_ENGINE`.
CONSTRAINED_IDW_ENGINE_LABEL = "constrained_idw"

# Constrained-IDW is noticeably heavier than plain IDW (multi-pass anisotropic
# search + declustering + smoothing). Cap the requested resolution so a large
# ``grid_n`` cannot make a UI-triggered run explode; the host default (50) is
# well within budget.
_MAX_GRID_RESOLUTION = 200
_MIN_GRID_RESOLUTION = 20

# Repository layout: the pure algorithm is vendored under
# paleo_workbench/_vendored/haiyou_constrained_idw/ (Qt-free package roots).
# Adding this dir to sys.path makes the vendored top-level ``drawing`` package
# importable; the algorithm modules use absolute ``drawing.*`` imports.
_VENDOR_ROOT = (
    Path(__file__).resolve().parents[1]
    / "_vendored"
    / "haiyou_constrained_idw"
)

_haiyou_cache: dict[str, Any] | None = None


def _ensure_haiyou_engine() -> dict[str, Any]:
    """Import the vendored constrained-IDW algorithm (Qt-free), cached.

    Puts the vendored package root on :data:`sys.path` (idempotent) so the
    algorithm's absolute ``drawing.*`` imports resolve. The vendored package
    ``__init__`` files are Qt-free, so no PyQt6 is pulled into the host.
    """
    global _haiyou_cache
    if _haiyou_cache is not None:
        return _haiyou_cache

    root = str(_VENDOR_ROOT)
    if not _VENDOR_ROOT.is_dir():
        raise RuntimeError(
            f"vendored haiyou algorithm not found at {_VENDOR_ROOT}"
        )
    if root not in sys.path:
        sys.path.insert(0, root)

    from drawing.single_factor.constrained_engine import (  # type: ignore[import-not-found]
        BarrierLine,
        BoundaryPolygon,
        ConstrainedIDWConfig,
        ConstraintWell,
        DirectionLine,
        generate_constrained_idw,
    )

    _haiyou_cache = {
        "generate_constrained_idw": generate_constrained_idw,
        "Config": ConstrainedIDWConfig,
        "Well": ConstraintWell,
        "Boundary": BoundaryPolygon,
        "Barrier": BarrierLine,
        "Direction": DirectionLine,
    }
    return _haiyou_cache


# --------------------------------------------------------------------------- #
# Host → haiyou input mapping
# --------------------------------------------------------------------------- #


def _coord(point: dict[str, Any]) -> tuple[float, float] | None:
    """Extract (x, y) from a host sample point (x/y or lng/lat keys)."""
    try:
        if "x" in point and "y" in point:
            return float(point["x"]), float(point["y"])
        if "lng" in point and "lat" in point:
            return float(point["lng"]), float(point["lat"])
    except (TypeError, ValueError):
        return None
    return None


def _value(point: dict[str, Any]) -> float | None:
    for key in ("value", "z", "v"):
        raw = point.get(key)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(val):
            return val
    return None


def _build_wells(points: Sequence[dict[str, Any]]):
    """Map host sample points → haiyou ``ConstraintWell`` list (drops invalid)."""
    Well = _ensure_haiyou_engine()["Well"]
    wells = []
    for i, p in enumerate(points):
        xy = _coord(p)
        val = _value(p)
        if xy is None or val is None:
            continue
        wells.append(Well(well_id=str(p.get("well") or i), x=xy[0], y=xy[1], value=val))
    return wells


def _dedupe_wells(wells: Sequence[Any]) -> tuple[list[Any], int]:
    """Drop wells sharing an identical (x, y); keep the first (first-wins).

    The constrained-IDW pipeline reads the well list twice with conflicting
    duplicate semantics: the exact-hit IDW stage keeps the first well at a
    coordinate while the residual-anchor stage overwrites in list order
    (last-wins). Deduplicating at the host boundary unifies both stages on
    first-wins, so the surface is reproducible and the earlier measurement is
    never silently discarded. Returns ``(kept_wells, dropped_count)``.
    """
    kept: list[Any] = []
    seen: set[tuple[float, float]] = set()
    dropped = 0
    for well in wells:
        key = (float(well.x), float(well.y))
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        kept.append(well)
    return kept, dropped


def _build_barriers(
    break_polylines: Sequence[Sequence[tuple[float, float]]] | None,
):
    """Map host IDW break lines → haiyou ``BarrierLine`` (hard region barriers)."""
    if not break_polylines:
        return []
    Barrier = _ensure_haiyou_engine()["Barrier"]
    barriers = []
    for i, poly in enumerate(break_polylines):
        pts = [(float(x), float(y)) for x, y in poly]
        if len(pts) >= 2:
            barriers.append(Barrier(line_id=f"break-{i}", points=tuple(pts), active=True))
    return barriers


def _build_directions(
    layers: Iterable[Any] | None, *, target_horizon: str | None
):
    """Map host direction constraint lines → haiyou ``DirectionLine`` corridors.

    The host models direction as anisotropy (azimuth + semi-axes); haiyou models
    it as a geometric corridor polyline. We use the host line's geometric
    ``coordinates`` as the corridor geometry and carry its anisotropy as the
    corridor ``ratio`` (major/minor) when available. Curated defaults otherwise.
    """
    if layers is None:
        return []
    Direction = _ensure_haiyou_engine()["Direction"]
    directions = []
    for i, param in enumerate(
        direction_line_params(layers, target_horizon=target_horizon)
    ):
        pts_raw = param.get("coordinates") or []
        pts = [(float(p[0]), float(p[1])) for p in pts_raw]
        if len(pts) < 2:
            continue
        ratio = 18.0  # haiyou default anisotropy ratio
        semi_major = param.get("semi_major")
        semi_minor = param.get("semi_minor")
        try:
            if semi_major and semi_minor and float(semi_minor) > 1e-9:
                ratio = max(1.0, float(semi_major) / float(semi_minor))
        except (TypeError, ValueError):
            pass
        directions.append(
            Direction(
                line_id=str(param.get("id") or f"dir-{i}"),
                points=tuple(pts),
                active=True,
                ratio=ratio,
            )
        )
    return directions


def _boundary_from_samples(
    points: Sequence[dict[str, Any]], wells: Sequence[Any]
):
    """Synthesize a haiyou ``BoundaryPolygon`` domain from the sample hull.

    The host's interpolation derives the grid from the sample bbox (+padding)
    and has no explicit boundary. Haiyou's constrained-IDW *requires* ≥1
    boundary polygon (it masks the interpolation domain). We build a convex
    hull around the samples, buffered slightly, so the constrained grid covers
    the data extent — and fall back to the bbox rectangle for degenerate
    (collinear / <3 unique) point sets.
    """
    Boundary = _ensure_haiyou_engine()["Boundary"]
    xs = np.array([w.x for w in wells], dtype=float)
    ys = np.array([w.y for w in wells], dtype=float)
    span = max(float(xs.max() - xs.min()), float(ys.max() - ys.min()))
    if not math.isfinite(span) or span < 1e-9:
        span = 1.0
    buf = 0.03 * span  # small outward buffer so edge wells sit inside the domain
    try:
        from shapely.geometry import MultiPoint

        hull = MultiPoint(list(zip(xs.tolist(), ys.tolist()))).convex_hull
        coords_xy = getattr(getattr(hull, "exterior", None), "coords", None)
        if coords_xy is not None and len(list(coords_xy)) >= 4:
            # Apply the promised buffer to the hull ring. The rasterizer's strict
            # cell-center ray casting excludes cell centers exactly on the ring,
            # so without this the outermost wells (the very points that define
            # the map edge) fall outside the interpolation domain: they are never
            # residual-anchored and cannot be LOO-sampled.
            buffered = hull.buffer(buf)
            buffered_coords = getattr(
                getattr(buffered, "exterior", None), "coords", None
            )
            if buffered_coords is not None and len(list(buffered_coords)) >= 4:
                exterior = tuple((float(x), float(y)) for x, y in buffered_coords)
                return Boundary(exterior=exterior), list(exterior)
    except Exception:
        pass
    # Degenerate fallback: bbox rectangle with margin.
    x0, x1 = float(xs.min()) - buf, float(xs.max()) + buf
    y0, y1 = float(ys.min()) - buf, float(ys.max()) + buf
    exterior = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    return Boundary(exterior=exterior), list(exterior)


# --------------------------------------------------------------------------- #
# Core entry point
# --------------------------------------------------------------------------- #


def _leave_one_out_grid_fidelity(
    grid_z: np.ndarray, grid_x: np.ndarray, grid_y: np.ndarray, wells
) -> tuple[float, int]:
    """In-sample R² of the interpolated surface at the well locations.

    Constrained-IDW re-anchors wells (``well_anchor_enabled``), so the grid
    should reproduce well values closely. We bilinearly sample the grid at each
    well and report 1 - SS_res/SS_tot. Cheap (O(n_wells)) and an honest quality
    indicator consistent with the other methods' reported R².

    Wells whose bilinear window touches nodata cells are *counted as missing*
    and excluded from the R² — never replaced by a fabricated prediction.
    Returns ``(r_squared, n_skipped)``.
    """
    values = np.array([w.value for w in wells], dtype=float)
    if values.size < 2 or float(values.std()) < 1e-12:
        return 1.0, 0
    gx = np.asarray(grid_x, dtype=float)
    gy = np.asarray(grid_y, dtype=float)
    z = np.asarray(grid_z, dtype=float)
    pred = np.full(values.shape, np.nan, dtype=float)
    x0, x1 = gx[0], gx[-1]
    y0, y1 = gy[0], gy[-1]
    nx = gx.size
    ny = gy.size

    def _sample(px: float, py: float) -> float | None:
        fi = (px - x0) / (x1 - x0) * (nx - 1) if nx > 1 else 0.0
        fj = (py - y0) / (y1 - y0) * (ny - 1) if ny > 1 else 0.0
        i = min(max(int(math.floor(fi)), 0), nx - 2)
        j = min(max(int(math.floor(fj)), 0), ny - 2)
        a = fi - i
        b = fj - j
        # rows index y (grid_z shape = (len(grid_y), len(grid_x)))
        v = (
            z[j, i] * (1 - a) * (1 - b)
            + z[j, i + 1] * a * (1 - b)
            + z[j + 1, i] * (1 - a) * b
            + z[j + 1, i + 1] * a * b
        )
        if not math.isfinite(float(v)):
            return None
        return float(v)

    n_skipped = 0
    for k, w in enumerate(wells):
        sampled = _sample(w.x, w.y)
        if sampled is None:
            n_skipped += 1
            continue
        pred[k] = sampled
    valid = np.isfinite(pred)
    if int(valid.sum()) < 2:
        # R² is undefined with fewer than two samplable wells; keep the
        # degenerate-input convention (1.0) but report how many were skipped.
        return 1.0, n_skipped
    v_obs = values[valid]
    v_pred = pred[valid]
    ss_res = float(np.sum((v_obs - v_pred) ** 2))
    ss_tot = float(np.sum((v_obs - v_obs.mean()) ** 2))
    if ss_tot < 1e-12:
        return 1.0, n_skipped
    return float(max(0.0, min(1.0, 1.0 - ss_res / ss_tot))), n_skipped


def _value_range_from_wells(wells: Sequence[Any]) -> tuple[float | None, float | None]:
    """Derive clamp bounds from sample values (disable when empty/degenerate).

    Haiyou defaults ``value_min=0`` / ``value_max=1``, which silently clamps
    real factor fields (thickness, sand %, etc.). Host-owned integration must
    set the range from data so numerical results match the observed samples.
    """
    values = np.asarray([w.value for w in wells], dtype=np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None, None
    lo = float(finite.min())
    hi = float(finite.max())
    if not math.isfinite(lo) or not math.isfinite(hi):
        return None, None
    if hi < lo:
        lo, hi = hi, lo
    # Tiny pad so exact sample extremes survive floating-point anchor/smooth.
    if hi == lo:
        pad = max(abs(lo) * 1e-6, 1e-9)
        return lo - pad, hi + pad
    pad = max((hi - lo) * 1e-9, 1e-12)
    return lo - pad, hi + pad


def _search_radii_from_wells(
    wells: Sequence[Any],
) -> tuple[float, float]:
    """Scale search/decluster radii to sample extent (not fixed metre defaults).

    Synthetic degree-scale and unit-box fixtures as well as projected metres
    all need radii proportional to the map.  Returns ``(search_radius,
    decluster_radius)``.
    """
    xs = np.asarray([w.x for w in wells], dtype=np.float64)
    ys = np.asarray([w.y for w in wells], dtype=np.float64)
    span_x = float(xs.max() - xs.min()) if xs.size else 0.0
    span_y = float(ys.max() - ys.min()) if ys.size else 0.0
    span = max(span_x, span_y, 0.0)
    if not math.isfinite(span) or span <= 0.0:
        span = 1.0
    # Cover the domain generously so sparse wells still fill the hull; cap is
    # the diagonal of the sample bbox (with a small pad).
    diagonal = math.hypot(span_x, span_y) if (span_x > 0 or span_y > 0) else span
    search_radius = max(diagonal * 1.05, span * 0.75, 1e-6)
    # Decluster over a fraction of the domain so dense clusters down-weight.
    decluster_radius = max(search_radius * 0.15, span * 0.05, 1e-6)
    return float(search_radius), float(decluster_radius)


#: Barrier blank-buffer target for geographic (degree) CRS projects, metres.
_DEGREE_CRS_BARRIER_BUFFER_METERS = 300.0
#: Equatorial metres per degree (meridian constant). Conservative for the
#: buffer: at any latitude the corridor is at most ~300 m wide.
_METERS_PER_DEGREE = 111_320.0


def barrier_buffer_distance_for_crs(crs: str | None) -> float | None:
    """Explicit barrier blank buffer (map units) when *crs* is geographic.

    The vendored engine's auto barrier buffer is calibrated for metre-scale
    projected coordinates (≈300 m): its adaptive constants (2·grid_step,
    3%·search_radius, 1.2%·extent) applied to degree coordinates resolve to
    kilometres. For a geographic CRS we pass the ~300 m target converted to
    degrees instead, keeping metre-CRS behavior untouched (returns ``None``).
    """
    if not crs:
        return None
    text = str(crs).strip().lower()
    is_geographic = False
    try:
        import pyproj  # optional; heuristic fallback below when unavailable

        is_geographic = bool(pyproj.CRS.from_user_input(text).is_geographic)
    except Exception:
        # Host default project_crs is "EPSG:4326 / WGS84" (not parseable by
        # pyproj due to the free-text suffix) — recognize it heuristically.
        is_geographic = "4326" in text or "wgs84" in text
    if not is_geographic:
        return None
    return _DEGREE_CRS_BARRIER_BUFFER_METERS / _METERS_PER_DEGREE


def run_constrained_idw(
    points: Sequence[dict[str, Any]],
    *,
    grid_n: int = 50,
    power: float = 2.0,
    layers: Iterable[Any] | None = None,
    target_horizon: str | None = None,
    break_polylines: Sequence[Sequence[tuple[float, float]]] | None = None,
    cancellation_token=None,
    crs: str | None = None,
) -> dict[str, Any]:
    """Run haiyou constrained-IDW and return a host ``interpolate_factor_grid``-shaped dict.

    Parameters mirror the host's interpolation contract: ``points`` are the
    host sample points; ``layers`` provide break/direction constraints; the
    result dict matches what :func:`geoviz.interpolate_factor_grid` returns so
    the rest of the single-factor pipeline (task params, preview cards, contour
    draft, catalog run, serialization) consumes it unchanged.

    Hot-path arrays (``grid_x`` / ``grid_y`` / ``grid_z``) are contiguous
    ``ndarray`` values.  Legacy nested-list encoding is deferred to
    :class:`FactorGridResult` / task-parameter serialisation boundaries.
    """
    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()

    try:
        import scipy.ndimage  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "约束IDW 需要 SciPy（scipy.ndimage）才能保持可达域/孔洞填充语义；"
            "当前环境未安装 SciPy，拒绝降级为不同网格。"
        ) from exc

    engine = _ensure_haiyou_engine()
    generate = engine["generate_constrained_idw"]
    Config = engine["Config"]

    wells = _build_wells(points)
    wells, n_duplicate_wells = _dedupe_wells(wells)
    if len(wells) < 3:
        raise ValueError(
            "约束IDW 需要至少 3 个有效样本点（含坐标与数值），当前仅 "
            f"{len(wells)} 个。"
        )

    # Resolve barriers / directions from the project constraints when no
    # explicit break lines were supplied.
    barriers_in = break_polylines
    if barriers_in is None and layers is not None:
        barriers_in = break_polylines_for_idw(layers, target_horizon=target_horizon)
    barriers = _build_barriers(barriers_in)
    directions = _build_directions(layers, target_horizon=target_horizon)

    boundary, boundary_xy = _boundary_from_samples(points, wells)

    resolution = int(round(grid_n))
    resolution = max(_MIN_GRID_RESOLUTION, min(_MAX_GRID_RESOLUTION, resolution))

    value_min, value_max = _value_range_from_wells(wells)
    search_radius, decluster_radius = _search_radii_from_wells(wells)

    config = Config(
        grid_resolution=resolution,
        power=float(power),
        search_radius=search_radius,
        decluster_radius=decluster_radius,
        value_min=value_min,
        value_max=value_max,
        # We only need the interpolated surface (host re-derives contours via
        # its own marching-squares contour-draft pipeline, consistent with the
        # other methods). Skip haiyou's contour extraction to keep the import
        # graph narrow (no contour_extractor) and avoid duplicate contour logic.
        extract_contours=False,
        # Geographic (degree) CRS: the engine's auto barrier buffer is
        # metre-calibrated; pass an explicit ~300 m buffer in degrees instead
        # of letting the metre constants expand to kilometres.
        barrier_buffer_distance=barrier_buffer_distance_for_crs(crs) or 0.0,
    )

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()

    result = generate(
        wells,
        [boundary],
        barriers,
        directions,
        levels=[],  # unused with extract_contours=False
        config=config,
    )

    if cancellation_token is not None:
        cancellation_token.raise_if_cancelled()

    # Contiguous float64 axes / float64 grid (canonical nodata = NaN).  Keep as
    # ndarray through FactorGridResult; do not .tolist() on the hot path.
    grid_z = np.ascontiguousarray(result.grid_z, dtype=np.float64)
    grid_x = np.ascontiguousarray(result.grid_x, dtype=np.float64)
    grid_y = np.ascontiguousarray(result.grid_y, dtype=np.float64)
    finite = grid_z[np.isfinite(grid_z)]
    if finite.size == 0:
        raise ValueError("约束IDW 未产生任何有效格网单元。")
    z_min = float(finite.min())
    z_max = float(finite.max())
    z_mean = float(finite.mean())
    r_squared, r_squared_n_skipped = _leave_one_out_grid_fidelity(
        grid_z, grid_x, grid_y, wells
    )

    return {
        "grid_x": grid_x,
        "grid_y": grid_y,
        "grid_z": grid_z,
        "backend": CONSTRAINED_IDW_ENGINE_LABEL,
        "method": CONSTRAINED_IDW_ENGINE_LABEL,
        "grid_n": resolution,
        "n_points": len(wells),
        "n_break_lines": len(barriers),
        # Duplicate-coordinate wells are dropped first-wins at the host
        # boundary; report the count so callers can warn the user.
        "duplicate_wells_dropped": n_duplicate_wells,
        "min": z_min,
        "max": z_max,
        "mean": z_mean,
        "r_squared": r_squared,
        # Transparency for the quality metric: how many wells were excluded
        # from the R² because their sampling window hit nodata (never faked).
        "r_squared_n_sampled": int(len(wells) - r_squared_n_skipped),
        "r_squared_n_skipped": r_squared_n_skipped,
        # Keep the resolved domain boundary so downstream consumers can show
        # the constrained interpolation extent (e.g. as a reference outline).
        "boundary": [[float(x), float(y)] for x, y in boundary_xy],
        "n_direction_lines": len(directions),
        "search_radius": search_radius,
        "decluster_radius": decluster_radius,
    }
