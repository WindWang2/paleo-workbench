#!/usr/bin/env python3
"""Oracle for the VIZ-E charts kernel (libs/viz_charts) — plan V6.

Imports the REAL geoviz_plots sources (chart/axes, chart/series,
chart/convex_hull, surface/colormaps, surface/marching_squares,
fence/fence_generator, analytics/well_qc) from the geo-viz-engine
submodule and freezes deterministic observable outputs for the C++ replay
test in libs/viz_charts/viz_charts_tests.

Freeze families and their parity contracts (see
docs/development/cpp-viz-e/scope-ledger.md):
  * axes / lttb / colormaps / fence / well_qc — exact-value freeze (the C++
    port reproduces the same doubles / ints / strings).
  * convex hull — cyclic-order freeze: SciPy's starting vertex follows
    qhull's internal facet order (no stable documented convention), so the
    C++ test compares the CCW vertex cycle modulo rotation.
  * marching squares — geometric-invariant freeze: the C++ port replaces
    contourpy's quad-based serial algorithm with triangle subdivision
    (bilinear center), so vertex sequences differ; per level the oracle
    freezes line counts, total polyline length, bounding box and midpoint
    on-line values; per band it freezes total area and sample-point
    membership. Tolerances live in the C++ comparator.

The generator also runs a negative self-check: after freezing, every
numeric field is perturbed and the checksum must change (guards against an
all-zero / tampered fixture passing trivially).

Run with the geo-viz-engine venv (PySide6 + numpy + scipy + contourpy):

    <repo>/../main/geo-viz-engine/.venv/bin/python \
        tools/oracle/generate_viz_e_charts_fixtures.py

Re-freeze requires re-running this script; expected values are never
hand-edited.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# The frozen behavior source is the geo-viz-engine submodule. Prefer the
# sibling main checkout (read-only) so migration worktrees need not clone
# the submodule; fall back to the in-repo submodule path. Worktrees carry
# EMPTY submodule mount points, so existence alone must not win — require
# the actual package tree.
CANDIDATES = [
    REPO_ROOT.parent.parent / "main" / "geo-viz-engine",  # worktrees/x layout
    REPO_ROOT.parent / "geo-viz-engine",                  # sibling checkout
    REPO_ROOT / "geo-viz-engine",                         # in-repo submodule
]
GEO_ENGINE = next(
    (c for c in CANDIDATES if (c / "packages" / "geoviz_plots").is_dir()), None
)
if GEO_ENGINE is None:
    raise SystemExit(
        "geo-viz-engine package tree not found (checked: "
        + ", ".join(str(c) for c in CANDIDATES)
        + ") — check out the submodule or point this script at a sibling checkout"
    )
PKG = GEO_ENGINE / "packages"
sys.path.insert(0, str(PKG))

OUT = (
    REPO_ROOT
    / "libs"
    / "viz_charts"
    / "viz_charts_tests"
    / "fixtures"
    / "viz_e_charts_oracle.json"
)

GEOVIZ_GITLINK = "08851951f3bbc0beb90886adf52e1928f4383c16"


def _rng(seed: int):
    """Deterministic LCG so the fixture never depends on the host RNG."""
    state = seed

    def next01() -> float:
        nonlocal state
        state = (6364136223846793005 * state + 1442695040888963407) % (1 << 64)
        return (state >> 11) / float(1 << 53)

    return next01


def collect_inputs() -> dict:
    """Deterministic inputs shared verbatim by Python freeze and C++ replay."""
    rnd = _rng(20260919)
    cases: dict = {}

    # --- axes ------------------------------------------------------------
    cases["ticks"] = [
        [vmin, vmax, max_ticks]
        for vmin, vmax, max_ticks in [
            (0.0, 1.0, 6), (0.0, 10.0, 6), (-3.5, 7.2, 6),
            (0.001, 0.004, 6), (1e6, 9e6, 5), (-1.0, -0.1, 6),
            (0.0, 0.0, 6), (5.0, 5.0, 6), (2.0, 1.0, 6), (0.0, 1.0, 1),
            (float("nan"), 1.0, 6), (0.0, float("inf"), 6),
            (0.0, 100.0, 8), (-250.0, 250.0, 7), (0.123, 0.456, 6),
        ]
    ]
    cases["nice_number"] = [
        [value, round_flag]
        for value in [1.3, 2.7, 6.4, 9.9, 0.0, -1.3, -6.4, 12345.6, 0.00042]
        for round_flag in [True, False]
    ]
    cases["format_tick"] = [
        [value, step]
        for value, step in [
            (0.5, 0.1), (0.0012, 0.001), (1234.0, 100.0), (0.0, 1.0),
            (-7.25, 0.05), (3.14159, 1e-12), (2.0, 10.0),
            (float("nan"), 1.0), (float("inf"), 1.0),
        ]
    ]

    # --- lttb ------------------------------------------------------------
    def series_sine(n: int, noise: float) -> tuple[list[float], list[float]]:
        xs, ys = [], []
        for i in range(n):
            x = i / max(1, n - 1) * 6.283185307179586
            y = math.sin(x) + noise * (rnd() - 0.5)
            xs.append(x)
            ys.append(y)
        return xs, ys

    lttb_cases = []
    xs, ys = series_sine(97, 0.35)
    lttm_case = {"x": xs, "y": ys, "threshold": 12}
    lttb_cases.append(lttm_case)
    x2 = [float(i) for i in range(40)]
    y2 = [float(i * i % 13) for i in range(40)]
    y2[7] = float("nan")
    y2[19] = float("nan")
    x2[11] = float("nan")  # pair dropped even though y is fine
    lttb_cases.append({"x": x2, "y": y2, "threshold": 9})
    xs3, ys3 = series_sine(23, 0.0)
    lttb_cases.append({"x": xs3, "y": ys3, "threshold": 5})
    cases["lttb"] = lttb_cases
    cases["bounds"] = [
        {"x": l["x"], "y": l["y"]} for l in lttb_cases
    ]

    # --- colormaps --------------------------------------------------------
    cases["colormap_samples"] = [
        [name, val, vmin, vmax]
        for name in ["viridis", "cnpc_strat", "cnpc_fluid", "thermal", "nope"]
        for val, vmin, vmax in [
            (0.0, 0.0, 1.0), (0.5, 0.0, 1.0), (1.0, 0.0, 1.0),
            (-1.0, 0.0, 1.0), (2.0, 0.0, 1.0), (0.37, 0.1, 0.9),
            (0.5, 0.5, 0.5), (7.5, 5.0, 10.0),
        ]
    ]

    # --- convex hull + point-in-polygon ------------------------------------
    hull_pts_x, hull_pts_y = [], []
    for _ in range(37):
        hull_pts_x.append(round(rnd() * 10 - 5, 6))
        hull_pts_y.append(round(rnd() * 10 - 5, 6))
    # a few collinear-on-edge + NaN cases
    hull_pts_x += [0.0, 1.0, 2.0]
    hull_pts_y += [3.0, 3.0, 3.0]
    hull_pts_x.append(float("nan"))
    hull_pts_y.append(0.0)
    cases["hull"] = {"x": hull_pts_x, "y": hull_pts_y}
    cases["hull_collinear"] = {
        "x": [0.0, 1.0, 2.0, 3.0, float("nan"), 1.5],
        "y": [0.0, 0.0, 0.0, 0.0, 4.0, 0.0],
    }
    lasso = [(1.0, 1.0), (4.0, 1.5), (5.0, 4.0), (2.5, 5.0), (1.0, 3.5)]
    pip_x = [round(rnd() * 6, 4) for _ in range(29)]
    pip_y = [round(rnd() * 6, 4) for _ in range(29)]
    cases["pip"] = {"x": pip_x, "y": pip_y, "poly": lasso}

    # --- marching squares grid (deterministic analytic surface) -----------
    gx = [round(0.0 + 0.5 * j, 6) for j in range(13)]
    gy = [round(0.0 + 0.4 * i, 6) for i in range(11)]
    gzx, gzy = [], []
    for i in range(len(gy)):
        for j in range(len(gx)):
            gzx.append(gx[j])
            gzy.append(gy[i])
    gz = [
        round(3.1 * math.sin(0.7 * gzx[k]) * math.cos(0.9 * gzy[k])
              + 0.2 * math.sin(gzx[k] * gzy[k]), 6)
        for k in range(len(gzx))
    ]
    # NaN pocket (masked region)
    for i in range(3, 5):
        for j in range(4, 7):
            gz[i * len(gx) + j] = float("nan")
    cases["ms_grid"] = {"gx": gx, "gy": gy, "gz": gz}
    cases["ms_levels"] = [-2.0, -1.0, 0.0, 0.75, 1.5, 2.25]

    # saddle-dominant mini grid (center-value disambiguation)
    cases["ms_saddle_grid"] = {
        "gx": [0.0, 1.0, 2.0],
        "gy": [0.0, 1.0, 2.0],
        "gz": [
            0.0, 2.0, 0.0,
            2.0, 1.0, 2.0,
            0.0, 2.0, 0.0,
        ],
    }

    # --- fence -------------------------------------------------------------
    cases["fence"] = {
        "wells": [
            {"name": "W1", "x": 100.5, "y": 200.25, "depth": 150.0},
            {"name": "W2", "x": 400.0, "y": 210.5, "depth": 220.75},
            {"name": "W3", "x": 700.25, "y": 180.0, "depth": 90.5},
        ],
        "nz_samples": 5,
    }
    ni, nx, nz = 12, 14, 6
    seis = []
    for i in range(ni):
        for j in range(nx):
            for k in range(nz):
                seis.append(round(math.sin(0.3 * i + 0.2 * j) * math.cos(0.4 * k), 4))
    cases["fence_slice"] = {
        "seismic": seis, "ni": ni, "nx": nx, "nz": nz,
        "wells": [
            {"name": "A", "x": 2.7, "y": 3.2, "depth": 10},
            {"name": "B", "x": 9.1, "y": 4.4, "depth": 20},
            {"name": "C", "x": 4.5, "y": 11.8, "depth": 30},
        ],
        "n_samples_per_segment": 7,
    }

    # --- well qc ------------------------------------------------------------
    qc_vals = [round(rnd() * 20 - 10, 4) for _ in range(31)]
    qc_vals[3] = float("nan")
    qc_vals[17] = float("inf")
    cases["qc_mad"] = [qc_vals, [1.0, 2.0, 3.0, 4.0, 5.0], [7.0], []]
    cases["qc_z"] = [qc_vals, [5.0, 5.0, 5.0, 9.0], [1.0, 2.0, 3.0]]
    cases["qc_sand"] = [
        [10.0, 40.0], [0.0, 40.0], [40.0, 40.0], [41.0, 40.0],
        [-1.0, 40.0], [10.0, 0.0], [None, 40.0], [10.0, None],
        [float("nan"), 40.0], [7.5, 30.0],
    ]
    return cases


def freeze(inputs: dict) -> dict:
    """Run the REAL Python implementations over the shared inputs."""
    import subprocess

    import numpy as np
    import geoviz_plots
    from geoviz_plots.chart.axes import calculate_ticks, format_tick, nice_number
    from geoviz_plots.chart.series import lttb_downsample
    from geoviz_plots.chart.convex_hull import (
        compute_convex_hull,
        point_in_polygon_mask,
    )
    from geoviz_plots.surface.colormaps import sample_colormap
    from geoviz_plots.surface.marching_squares import (
        extract_contour_lines,
        extract_filled_contours,
    )
    from geoviz_plots.fence.fence_generator import CrossWellFenceGenerator
    from geoviz_plots.analytics.well_qc import (
        compute_sand_ratio,
        median_absolute_deviation,
        modified_z_scores,
    )

    out: dict = {"geoviz_gitlink": GEOVIZ_GITLINK, "inputs": inputs}

    # Provenance: the fixture must record the tree the numbers actually came
    # from, and that tree must be the frozen gitlink (fail loudly otherwise —
    # freezing off an unverified checkout silently invalidates every value).
    src_root = Path(geoviz_plots.__file__).resolve().parents[2]
    try:
        sha = subprocess.check_output(
            ["git", "-C", str(src_root), "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:
        sha = "unknown"
    out["geoviz_source"] = str(src_root)
    out["geoviz_sha"] = sha
    if sha != GEOVIZ_GITLINK:
        raise SystemExit(
            f"provenance mismatch: imported geoviz_plots from {src_root} "
            f"@ {sha}, expected gitlink {GEOVIZ_GITLINK} — refusing to freeze"
        )

    out["ticks"] = [
        {"ticks": t, "step": s}
        for t, s in (calculate_ticks(v0, v1, int(m)) for v0, v1, m in inputs["ticks"])
    ]
    out["nice_number"] = [
        nice_number(v, bool(r)) for v, r in inputs["nice_number"]
    ]
    out["format_tick"] = [
        format_tick(v, s) for v, s in inputs["format_tick"]
    ]

    lttb_out = []
    for case in inputs["lttb"]:
        x, y = lttb_downsample(np.asarray(case["x"]), np.asarray(case["y"]), case["threshold"])
        lttb_out.append({"x": [float(v) for v in x], "y": [float(v) for v in y]})
    out["lttb"] = lttb_out
    from geoviz_plots.chart.series import Series

    bounds_out = []
    for case in inputs["bounds"]:
        s = Series(x=case["x"], y=case["y"])
        b = s.get_bounds()
        bounds_out.append(list(b))
    out["bounds"] = bounds_out

    cm_out = []
    for name, val, vmin, vmax in inputs["colormap_samples"]:
        c = sample_colormap(name, val, vmin, vmax)
        cm_out.append([c.red(), c.green(), c.blue()])
    out["colormap_samples"] = cm_out

    hx = np.asarray(inputs["hull"]["x"])
    hy = np.asarray(inputs["hull"]["y"])
    hull = compute_convex_hull(hx, hy)
    out["hull"] = [[float(p[0]), float(p[1])] for p in hull]
    coll = compute_convex_hull(
        np.asarray(inputs["hull_collinear"]["x"]),
        np.asarray(inputs["hull_collinear"]["y"]),
    )
    out["hull_collinear"] = [[float(p[0]), float(p[1])] for p in coll]
    mask = point_in_polygon_mask(
        np.asarray(inputs["pip"]["x"]), np.asarray(inputs["pip"]["y"]),
        [tuple(p) for p in inputs["pip"]["poly"]],
    )
    out["pip"] = [bool(v) for v in mask]

    # marching squares — geometric invariants (see module docstring)
    g = inputs["ms_grid"]
    gx, gy, gz = (np.asarray(g[k], dtype=np.float64) for k in ("gx", "gy", "gz"))
    gz2 = gz.reshape(len(g["gy"]), len(g["gx"]))
    levels = inputs["ms_levels"]
    lines = extract_contour_lines(gx, gy, gz2, levels)

    def line_invariants(plines):
        total = 0.0
        bbox = None
        for pl in plines:
            pts = np.asarray(pl)
            if pts.size == 0:
                continue
            seglen = np.hypot(*(pts[1:] - pts[:-1]).T).sum()
            total += float(seglen)
            lo, hi = pts.min(axis=0), pts.max(axis=0)
            bbox = [float(lo[0]), float(hi[0]), float(lo[1]), float(hi[1])] if bbox is None else [
                min(bbox[0], float(lo[0])), max(bbox[1], float(hi[0])),
                min(bbox[2], float(lo[1])), max(bbox[3], float(hi[1])),
            ]
        mid_samples = []
        for pl in plines:
            pts = np.asarray(pl)
            if len(pts) >= 3:
                mid = pts[len(pts) // 2]
                mid_samples.append([float(mid[0]), float(mid[1])])
        return {
            "count": len(plines),
            "total_length": total,
            "bbox": bbox,
            "midpoints": mid_samples[:4],
        }

    out["ms_lines"] = {f"{lv:g}": line_invariants(lines[float(lv)]) for lv in levels}
    bands = extract_filled_contours(gx, gy, gz2, levels)
    band_out = []
    for b in bands:
        area = 0.0
        for poly, off in zip(b.polygons, b.offsets):
            rings = [
                np.asarray(poly[off[k]:off[k + 1]])
                for k in range(len(off) - 1)
            ]
            for ring in rings:
                if len(ring) < 3:
                    continue
                x = ring[:, 0]
                y = ring[:, 1]
                area += 0.5 * abs(float(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))
        band_out.append({
            "level_min": b.level_min,
            "level_max": b.level_max,
            "color": [b.color.red(), b.color.green(), b.color.blue()],
            "label": b.label,
            "area": area,
        })
    out["ms_bands"] = band_out

    sad = inputs["ms_saddle_grid"]
    slines = extract_contour_lines(
        np.asarray(sad["gx"]), np.asarray(sad["gy"]),
        np.asarray(sad["gz"]).reshape(3, 3), [1.5],
    )
    out["ms_saddle"] = {f"{lv:g}": line_invariants(pl) for lv, pl in slines.items()}

    wells = [dict(w) for w in inputs["fence"]["wells"]]
    verts, faces, colors = CrossWellFenceGenerator.generate_fence_mesh(
        wells, nz_samples=inputs["fence"]["nz_samples"]
    )
    out["fence"] = {
        "vertices": [float(v) for v in verts.ravel()],
        "faces": [int(v) for v in faces.ravel()],
        "face_colors": [float(v) for v in colors.ravel()],
    }
    fs = inputs["fence_slice"]
    sl = CrossWellFenceGenerator.extract_seismic_slice(
        np.asarray(fs["seismic"], dtype=np.float32).reshape(fs["ni"], fs["nx"], fs["nz"]),
        [dict(w) for w in fs["wells"]],
        n_samples_per_segment=fs["n_samples_per_segment"],
    )
    out["fence_slice"] = {
        "shape": [int(sl.shape[0]), int(sl.shape[1])],
        "values": [float(v) for v in sl.ravel()],
    }

    out["qc_mad"] = [
        float(median_absolute_deviation(v)) for v in inputs["qc_mad"]
    ]
    out["qc_z"] = [
        [float(v) for v in modified_z_scores(v)] for v in inputs["qc_z"]
    ]
    out["qc_sand"] = [
        [None if r is None else float(r), flag]
        for r, flag in (compute_sand_ratio(s, t) for s, t in inputs["qc_sand"])
    ]
    return out


def negative_self_check(fixture: dict) -> None:
    """Tamper every numeric family and require the digest to change."""
    digest = lambda d: hashlib.sha256(
        json.dumps(d, sort_keys=True).encode()
    ).hexdigest()  # noqa: E731

    base = digest(fixture)
    for key in ("ticks", "lttb", "colormap_samples", "hull", "ms_bands",
                "fence", "qc_mad", "nice_number"):
        tampered = json.loads(json.dumps(fixture))
        # flip one deep numeric leaf
        def flip(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        obj[k] = v + 1.5
                        return True
                    if flip(v):
                        return True
                return False
            if isinstance(obj, list):
                for v in obj:
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        i = obj.index(v)
                        obj[i] = v + 1.5
                        return True
                    if flip(v):
                        return True
                return False
            return False

        if not flip(tampered[key]):
            raise SystemExit(f"negative self-check: no numeric leaf in {key}")
        if digest(tampered) == base:
            raise SystemExit(f"negative self-check: tampering {key} went undetected")
    print("negative self-check: OK (8 families tamper-detected)")


def _sanitize(obj):
    """Replace non-finite floats with string markers (nlohmann and strict
    JSON reject NaN/Infinity literals); the C++ replay maps them back."""
    if isinstance(obj, float):
        if math.isnan(obj):
            return "__nan__"
        if math.isinf(obj):
            return "__inf__" if obj > 0 else "__-inf__"
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def main() -> None:
    inputs = collect_inputs()
    fixture = _sanitize(freeze(inputs))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(fixture, indent=1, sort_keys=True)
    OUT.write_text(payload + "\n")
    print(f"wrote {OUT} ({len(payload)} bytes)")
    negative_self_check(json.loads(payload))
    print(f"geoviz source: {GEO_ENGINE} @ {GEOVIZ_GITLINK}")


if __name__ == "__main__":
    main()
