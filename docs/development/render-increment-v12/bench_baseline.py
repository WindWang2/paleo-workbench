"""V12-C baseline quantification script (goal §4.1).

Measures, on the BASE commit (926f3335), before any change:

1. Scalar-grid per-frame draw cost: wall time, ``rasterize()`` call count,
   and bytes copied per frame for a pan sequence (frame cache defeated by
   extent changes, exactly what wheel-zoom/pan does).
   Two payload flavours:
   - pure-Python ``GridMapLayer.rasterize_rgba`` via ``_ScalarPayload``
   - native ``grid_render_core.ScalarGridLayer`` (only when importable)
2. ``FallbackMapRenderBackend._prepared_layer`` repeat-call cost with an
   UNCHANGED snapshot (is the "no data change ⇒ zero rebuild" already true?)
   versus a first-touch (miss) rebuild.
3. ``TopologyService.validate_records`` wall time vs feature count, plus the
   number of cross-language (bridge) validate calls per invocation, in three
   engine modes: none (Shapely), fake bridge (counting), real bridge.

Run from the repo root of the worktree:

    QT_QPA_PLATFORM=offscreen python docs/development/render-increment-v12/bench_baseline.py \
        [--native-path PATH_TO_grid_render_core_DIR] [--bridge-path PATH_TO_qgis_render_bridge_DIR]

The script prints a markdown table; numbers land in 01-baseline.md.
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from PySide6.QtWidgets import QApplication

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
)
from paleo_workbench.mapping.topology import TopologyService

GRID_W, GRID_H = 600, 450
OUT_W, OUT_H = 900, 675
PAN_FRAMES = 30


class _CountingPayload:
    """Wrap a scalar payload and count rasterize() calls + bytes shipped."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls = 0
        self.bytes_returned = 0

    def rasterize(self):
        rgba = self._inner.rasterize()
        self.calls += 1
        self.bytes_returned += int(rgba.nbytes)
        return rgba


def _smooth_grid(w: int, h: int) -> np.ndarray:
    ys, xs = np.mgrid[0:h, 0:w]
    z = (
        0.5 * np.sin(xs / 37.0)
        + 0.3 * np.cos(ys / 23.0)
        + 0.2 * np.sin((xs + ys) / 61.0)
        + np.sin(xs / 130.0) * np.cos(ys / 97.0)
    ).astype(np.float64)
    z[np.sqrt((xs - w / 2) ** 2 + (ys - h / 2) ** 2) < w / 8] = np.nan
    return z


def scalar_draw_rows() -> list[dict]:
    rows: list[dict] = []
    extent = (0.0, 0.0, 1000.0, 750.0)

    # -- pure-Python payload (GridMapLayer → _ScalarPayload) -----------------
    from paleo_workbench.mapping.layers import GridMapLayer

    xs = np.linspace(extent[0], extent[2], GRID_W)
    ys = np.linspace(extent[1], extent[3], GRID_H)
    layer = GridMapLayer(
        id="bench:scalar",
        name="scalar",
        grid_z=_smooth_grid(GRID_W, GRID_H),
        grid_x=xs,
        grid_y=ys,
    )
    snapshot = layer.to_snapshot()
    payload = _CountingPayload(snapshot.renderer_payload)
    rows.append(_measure_scalar_draw("pure-python payload", snapshot, payload, extent))

    # -- native payload (grid_render_core.ScalarGridLayer) -------------------
    native = None
    try:
        native_path = globals().get("_ARGS").native_path
        if native_path:
            sys.path.insert(0, native_path)
        import grid_render_core  # noqa: F401

        native = grid_render_core
    except Exception as exc:  # noqa: BLE001 — absence is a reportable outcome
        rows.append({"payload": "native payload", "note": f"unavailable: {exc}"})
    if native is not None:
        from paleo_workbench.mapping.color_ramps import get_color_ramp

        scalar = native.ScalarGridLayer(_smooth_grid(GRID_W, GRID_H).astype(np.float32))
        ramp = np.array(get_color_ramp("viridis").sample_table(256), dtype=np.uint8)
        scalar.set_color_ramp(ramp)
        scalar.set_color_range(-1.5, 1.5)
        snap = MapLayerSnapshot(
            id="bench:native-scalar",
            name="native",
            layer_type="scalar_grid",
            extent=extent,
            crs="",
            data_revision=int(scalar.data_revision),
            style_revision=int(scalar.style_revision),
            renderer_payload=scalar,
        )
        rows.append(_measure_scalar_draw("native payload", snap, _CountingPayload(scalar), extent))
    return rows


def _measure_scalar_draw(label: str, snapshot: MapLayerSnapshot, payload, extent) -> dict:
    backend = FallbackMapRenderBackend()
    backend.initialize()
    # Swap in the counting payload (snapshot is frozen; rebuild with it).
    from dataclasses import replace

    wrapped = MapRenderSnapshot(
        project_crs="", layers=(replace(snapshot, renderer_payload=payload),)
    )
    backend.set_layer_snapshot(wrapped)
    backend.set_output_size(OUT_W, OUT_H)
    backend.set_dpi(96.0)
    timings: list[float] = []
    for frame_index in range(PAN_FRAMES):
        dx = frame_index * 8.0
        backend.set_extent((extent[0] + dx, extent[1], extent[2] + dx, extent[3]))
        started = time.perf_counter()
        backend.render_sync()
        timings.append((time.perf_counter() - started) * 1000.0)
    copy_bytes = payload.bytes_returned + payload.calls * GRID_W * GRID_H * 4  # rasterize + QImage.copy
    return {
        "payload": label,
        "frames": len(timings),
        "median_ms": round(statistics.median(timings), 2),
        "p90_ms": round(sorted(timings)[int(len(timings) * 0.9) - 1], 2),
        "rasterize_calls_per_frame": payload.calls / max(1, len(timings)),
        "copy_mb_per_frame": round(copy_bytes / max(1, len(timings)) / (1024 * 1024), 2),
    }


def prepared_layer_rows() -> list[dict]:
    feature_count, ring_vertices = 1500, 32
    features = []
    for index in range(feature_count):
        ox, oy = (index % 40) * 30.0, (index // 40) * 30.0
        ring = [[ox + 12.0 * np.cos(2 * np.pi * i / ring_vertices),
                 oy + 12.0 * np.sin(2 * np.pi * i / ring_vertices)]
                for i in range(ring_vertices)]
        ring.append(list(ring[0]))
        features.append({"id": f"f{index}", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {}})
    layer = MapLayerSnapshot(
        id="bench:vector",
        name="vector",
        layer_type="vector",
        extent=(0.0, 0.0, 1200.0, 1150.0),
        crs="",
        data_revision=7,
        style_revision=1,
        features=tuple(features),
    )
    backend = FallbackMapRenderBackend()
    backend.initialize()

    started = time.perf_counter()
    backend._prepared_layer(layer)
    first_ms = (time.perf_counter() - started) * 1000.0
    hits = backend.render_diagnostics()["prepared_cache_hits"]

    repeats = 200
    started = time.perf_counter()
    for _ in range(repeats):
        backend._prepared_layer(layer)
    repeat_ms = (time.perf_counter() - started) * 1000.0 / repeats
    diagnostics = backend.render_diagnostics()
    return [
        {
            "case": f"{feature_count} polygons x {ring_vertices} vertices",
            "first_call_ms": round(first_ms, 3),
            "repeat_call_us": round(repeat_ms * 1000.0, 2),
            "hits": diagnostics["prepared_cache_hits"] - hits,
            "misses": diagnostics["prepared_cache_misses"],
        }
    ]


def _records(count: int) -> list[dict]:
    records = []
    for index in range(count):
        ox, oy = (index % 25) * 40.0, (index // 25) * 40.0
        if index % 10 == 0:
            # Bow-tie: self-intersecting square → GEOS/Shapely report invalid.
            coords = [[ox, oy], [ox + 30, oy + 30], [ox + 30, oy], [ox, oy + 30], [ox, oy]]
        else:
            coords = [[ox, oy], [ox + 30, oy], [ox + 30, oy + 30], [ox, oy + 30], [ox, oy]]
        records.append({"feature_id": f"f{index}", "geometry": {"type": "Polygon", "coordinates": [coords]}})
    return records


def topology_rows(mode: str, bridge_path: str | None) -> tuple[list[dict], str]:
    if mode == "fake":
        import types

        fake = types.ModuleType("qgis_render_bridge")
        geometry = types.ModuleType("qgis_render_bridge.geometry")

        class _CountingValidate:
            def __init__(self) -> None:
                self.calls = 0

            def __call__(self, geometry_dict):
                self.calls += 1
                return []

        counter = _CountingValidate()
        geometry.validate = counter
        fake.geometry = geometry
        sys.modules["qgis_render_bridge"] = fake
        sys.modules["qgis_render_bridge.geometry"] = geometry
    elif mode == "real" and bridge_path:
        sys.path.insert(0, bridge_path)

    service = TopologyService()
    rows: list[dict] = []
    counter = None
    if mode == "fake":
        counter = sys.modules["qgis_render_bridge"].geometry.validate
    for count in (50, 200, 1000):
        records = _records(count)
        started = time.perf_counter()
        calls_before = counter.calls if counter is not None else 0
        issues = service.validate_records("bench:layer", records)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        calls = (counter.calls - calls_before) if counter is not None else None
        rows.append(
            {
                "records": count,
                "issues": len(issues),
                "ms": round(elapsed_ms, 2),
                "bridge_calls": calls,
            }
        )
    return rows, mode


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--native-path", default=None, help="dir containing grid_render_core .so")
    parser.add_argument("--bridge-path", default=None, help="dir containing qgis_render_bridge .so")
    parser.add_argument("--bridge", choices=["none", "fake", "real"], default="fake")
    args = parser.parse_args()
    globals()["_ARGS"] = args

    app = QApplication.instance() or QApplication([])

    print("## 1. scalar-grid per-frame draw (pan sequence, frame cache defeated)\n")
    print("| payload | frames | median ms | p90 ms | rasterize calls/frame | copy MB/frame |")
    print("|---|---|---|---|---|---|")
    for row in scalar_draw_rows():
        if "note" in row:
            print(f"| {row['payload']} | - | - | - | - | - ({row['note']}) |")
        else:
            print(
                f"| {row['payload']} | {row['frames']} | {row['median_ms']} | {row['p90_ms']} "
                f"| {row['rasterize_calls_per_frame']} | {row['copy_mb_per_frame']} |"
            )

    print("\n## 2. _prepared_layer repeat calls (unchanged snapshot)\n")
    print("| case | first call ms | repeat call µs | hits | misses |")
    print("|---|---|---|---|---|")
    for row in prepared_layer_rows():
        print(
            f"| {row['case']} | {row['first_call_ms']} | {row['repeat_call_us']} "
            f"| {row['hits']} | {row['misses']} |"
        )

    print(f"\n## 3. topology.validate_records (engine mode: {args.bridge})\n")
    rows, _ = topology_rows(args.bridge, args.bridge_path)
    print("| records | issues | ms | bridge validate calls |")
    print("|---|---|---|---|")
    for row in rows:
        print(f"| {row['records']} | {row['issues']} | {row['ms']} | {row['bridge_calls']} |")


if __name__ == "__main__":
    main()
