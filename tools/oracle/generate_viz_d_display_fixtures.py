#!/usr/bin/env python3
"""Oracle for the VIZ-D advanced seismic display core (CONV-VIZ V5).

Imports the REAL frozen geoviz reference (geo-viz-engine@08851951 — no
hand-written expectations) and freezes fixtures for the C++ port in
libs/seismic_viewer:

  * colormap LUTs (ColormapManager.get_colormap, all registry names);
  * percentile clip ranges (profile_vd._renormalize semantics via
    np.nanpercentile) including NaN/asymmetric/degenerate cases;
  * normalize_to_index index arrays (ColormapManager._normalize_and_clip)
    including the NaN -> lut//2 rule;
  * viewport decimation (profile_wiggle.viewport_decimation);
  * wiggle paint geometry captured from the REAL ProfileWiggle widget by
    intercepting QPainter.drawPolyline/drawPolygon/drawLine during an
    offscreen paint (exact reference-path geometry, not re-derived math);
  * polyline arbitrary-line sampling (gpu_ops.sample_polyline_slice via
    scipy.ndimage.map_coordinates order=1 constant cval=0).

Run with a numpy/scipy/PySide6 interpreter (offscreen):

    QT_QPA_PLATFORM=offscreen /opt/miniconda3/bin/python3 \
        tools/oracle/generate_viz_d_display_fixtures.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE = REPO_ROOT / "geo-viz-engine" / "packages" / "geoviz_seismic"
sys.path.insert(0, str(ENGINE))

from geoviz_seismic.colormap import ColormapManager  # noqa: E402
from geoviz_seismic.gpu_ops import sample_polyline_slice  # noqa: E402
from geoviz_seismic.profile_wiggle import viewport_decimation  # noqa: E402

OUT = REPO_ROOT / "tests" / "cpp" / "viz_d" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)

CMAP_NAMES = [
    "seismic",
    "seismic_r",
    "gray",
    "jet",
    "hsv",
    "viridis",
    "phase_wheel",
]


def _num(value):
    value = float(value)
    if math.isnan(value):
        return "nan"
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def _nums(values) -> list:
    return [_num(v) for v in np.asarray(values, dtype=np.float64).reshape(-1)]


def freeze_colormaps() -> dict:
    return {
        name: np.asarray(ColormapManager.get_colormap(name))[:, :3].astype(int).tolist()
        for name in CMAP_NAMES
    }


def clip_range(data: np.ndarray, pct: float):
    """profile_vd._renormalize clip-range computation on the RAW slice."""
    dmin, dmax = np.nanmin(data), np.nanmax(data)
    if dmax == dmin:
        return None  # degenerate: all-zero index array, no range cached
    lo = float(np.nanpercentile(data, 100.0 - pct))
    hi = float(np.nanpercentile(data, pct))
    if hi <= lo:
        hi, lo = float(dmax), float(dmin)
    return [_num(lo), _num(hi)]


def freeze_percentile_and_normalize() -> dict:
    rng = np.random.default_rng(20260919)
    cases = {}
    planes = {
        "gauss": rng.normal(0.0, 1.0, size=(37, 29)).astype(np.float32),
        "spiky": np.where(
            rng.random((41, 23)) < 0.03, rng.normal(0, 60, size=(41, 23)),
            rng.normal(0, 1, size=(41, 23)),
        ).astype(np.float32),
        "with_nan": np.where(
            rng.random((31, 17)) < 0.1,
            np.float32("nan"),
            rng.normal(0, 1, size=(31, 17)),
        ).astype(np.float32),
        "constant": np.full((8, 8), 3.5, dtype=np.float32),
        "all_nan": np.full((6, 5), np.float32("nan"), dtype=np.float32),
        "tiny": np.array([[0.0, -1.0], [2.0, -3.0]], dtype=np.float32),
    }
    for name, plane in planes.items():
        entry = {"data": _nums(plane), "shape": list(plane.shape), "pcts": {}}
        for pct in (99.0, 95.0, 50.0, 1.0):
            entry["pcts"][str(pct)] = clip_range(plane, pct)
        # normalize_to_index with the default-99 range and polarity flips
        rng99 = clip_range(plane, 99.0)
        if rng99 is not None:
            lo, hi = rng99
            idx = ColormapManager.normalize_to_index(
                plane, lut_size=256, value_range=(float(lo), float(hi))
            )
            idx_neg = ColormapManager.normalize_to_index(
                -plane, lut_size=256, value_range=(float(lo), float(hi))
            )
            entry["index_default"] = [int(v) for v in np.asarray(idx).reshape(-1)]
            entry["index_negated"] = [int(v) for v in np.asarray(idx_neg).reshape(-1)]
            entry["range_used"] = rng99
        else:
            entry["index_default"] = None  # degenerate -> zeros handled by C++ test
        cases[name] = entry
    return cases


def freeze_decimation() -> dict:
    cases = []
    for n_traces, n_samples, w, h, step in [
        (120, 300, 400, 240, 1),
        (900, 1500, 400, 240, 1),
        (50, 60, 400, 240, 4),
        (2, 2, 400, 240, 1),
        (10, 0, 400, 240, 1),
        (7, 3, 1, 240, 1),
        (7, 3, 400, 1, 1),
        (64, 512, 300, 200, 2),
    ]:
        ts, idx = viewport_decimation(n_traces, n_samples, w, h, step)
        cases.append(
            {
                "n_traces": n_traces,
                "n_samples": n_samples,
                "width": w,
                "height": h,
                "trace_step_in": int(step),
                "trace_step": int(ts),
                "sample_indices": [int(v) for v in np.asarray(idx).reshape(-1)],
            }
        )
    return {"cases": cases}


def capture_wiggle_geometry() -> dict:
    """Run the REAL ProfileWiggle.paintEvent offscreen and record the exact
    draw calls (baselines / fill polygons / polylines) by monkey-patching
    QPainter — geometry straight from the frozen reference path."""
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF, QPixmap
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])

    rng = np.random.default_rng(42)
    cases = []
    scenarios = {
        "sine_ricker": (
            (
                np.exp(-((np.arange(120)[None, :] - 40) ** 2) / 400.0)
                * np.sin(2 * np.pi * np.arange(200)[:, None] / 25.0)
            ).astype(np.float32)
            * 1.0
        ),
        "with_nan": np.where(
            rng.random((150, 12)) < 0.05,
            np.float32("nan"),
            rng.normal(0, 1, size=(150, 12)).astype(np.float32),
        ),
        "constant_zero": np.zeros((30, 4), dtype=np.float32),
    }
    for name, data in scenarios.items():
        data = np.ascontiguousarray(data, dtype=np.float32)
        n_samples, n_traces = data.shape
        for polarity_normal in (True, False):
            for gain in (2.0, 1.0):
                width, height = 360, 260
                records = {"lines": [], "polygons": [], "polylines": []}

                real_draw_line = QPainter.drawLine
                real_draw_polygon = QPainter.drawPolygon
                real_draw_polyline = QPainter.drawPolyline

                def draw_line_recorder(self, *args, **kwargs):
                    pts = []
                    for a in args:
                        if isinstance(a, QPointF):
                            pts.append([float(a.x()), float(a.y())])
                    if pts:
                        records["lines"].append(pts)
                    return real_draw_line(self, *args, **kwargs)

                def poly_points(args):
                    for a in args:
                        if isinstance(a, QPolygonF):
                            return [
                                [float(p.x()), float(p.y())] for p in a
                            ]
                    return []

                def draw_polygon_recorder(self, *args, **kwargs):
                    pts = poly_points(args)
                    if pts:
                        records["polygons"].append(pts)
                    return real_draw_polygon(self, *args, **kwargs)

                def draw_polyline_recorder(self, *args, **kwargs):
                    pts = poly_points(args)
                    if pts:
                        records["polylines"].append(pts)
                    return real_draw_polyline(self, *args, **kwargs)

                QPainter.drawLine = draw_line_recorder
                QPainter.drawPolygon = draw_polygon_recorder
                QPainter.drawPolyline = draw_polyline_recorder
                try:
                    from geoviz_seismic.profile_wiggle import ProfileWiggle

                    widget = ProfileWiggle()
                    widget.resize(width, height)
                    widget.render(data.copy())
                    widget.set_gain(gain)
                    widget.set_polarity(polarity_normal)
                    # grab() repaints through the widget's REAL paintEvent
                    # (QWidget::render is shadowed by ProfileWiggle.render,
                    # so a direct call would feed a QPainter into render()).
                    widget.grab()
                finally:
                    QPainter.drawLine = real_draw_line
                    QPainter.drawPolygon = real_draw_polygon
                    QPainter.drawPolyline = real_draw_polyline
                def tag(points):
                    return [[_num(x), _num(y)] for x, y in points]

                cases.append(
                    {
                        "id": f"{name}_{'normal' if polarity_normal else 'flipped'}_g{gain}",
                        "data": _nums(data),
                        "n_samples": n_samples,
                        "n_traces": n_traces,
                        "width": width,
                        "height": height,
                        "gain": gain,
                        "polarity": 1 if polarity_normal else -1,
                        "lines": [tag(pts) for pts in records["lines"]],
                        "polygons": [tag(pts) for pts in records["polygons"]],
                        "polylines": [tag(pts) for pts in records["polylines"]],
                    }
                )
    return {"cases": cases}


def freeze_polyline_sampling() -> dict:
    rng = np.random.default_rng(7)
    ni, nx, nt = 12, 9, 24
    volume = rng.normal(0, 1, size=(ni, nx, nt)).astype(np.float32)
    volume_nan = volume.copy()
    volume_nan[3, 4, :] = np.float32("nan")
    volume_nan[7, 2, 10] = np.float32("nan")
    cases = []
    polylines = {
        "interior": [(1.25, 2.5), (6.75, 6.25)],
        "integer_nodes": [(2.0, 3.0), (8.0, 5.0)],
        "out_of_domain": [(-1.5, 1.0), (5.0, 12.5)],
        "three_legs": [(0.5, 0.5), (6.0, 6.0), (11.5, 3.5)],
        "short_seg": [(1.0, 1.0), (1.005, 1.0), (9.0, 7.0)],
        "single_point": [(2.0, 2.0)],
    }
    for vol_name, vol in {"base": volume, "nan": volume_nan}.items():
        for name, pts in polylines.items():
            section, dists = sample_polyline_slice(vol, pts, samples_per_unit=1.0)
            cases.append(
                {
                    "id": f"{vol_name}_{name}",
                    "volume": _nums(vol),
                    "shape": [ni, nx, nt],
                    "points": [list(map(float, p)) for p in pts],
                    "section": _nums(section),
                    "section_shape": list(section.shape),
                    "distances": _nums(dists),
                }
            )
    return {"cases": cases}


def main() -> None:
    fixture = {
        "generator": "tools/oracle/generate_viz_d_display_fixtures.py",
        "engine": "geo-viz-engine@08851951",
        "colormaps": freeze_colormaps(),
        "percentile_and_normalize": freeze_percentile_and_normalize(),
        "decimation": freeze_decimation(),
        "polyline": freeze_polyline_sampling(),
    }
    path = OUT / "viz_d_display_oracle.json"
    path.write_text(json.dumps(fixture, indent=1), encoding="utf-8")
    print(f"wrote {path}")

    wiggle = capture_wiggle_geometry()
    path = OUT / "viz_d_wiggle_oracle.json"
    path.write_text(json.dumps(wiggle, indent=1), encoding="utf-8")
    print(f"wrote {path} ({len(wiggle['cases'])} captured cases)")


if __name__ == "__main__":
    main()
