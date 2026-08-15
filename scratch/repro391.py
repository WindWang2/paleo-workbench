"""Verification for #391: culling + pan-strip reuse + frame cache."""
from __future__ import annotations

import time

from PySide6.QtWidgets import QApplication

from paleo_workbench.mapping.map_render_backend import (
    FallbackMapRenderBackend,
    MapLayerSnapshot,
    MapRenderSnapshot,
)

app = QApplication.instance() or QApplication([])

N = 10_000
SIDE = 100


def features() -> tuple[dict, ...]:
    rows = []
    for i in range(N):
        x = (i % SIDE) * 10.0
        y = (i // SIDE) * 10.0
        rows.append(
            {
                "id": f"f{i}",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[x, y], [x + 8, y], [x + 8, y + 8], [x, y + 8], [x, y]]],
                },
                "properties": {"name": f"F{i}"},
            }
        )
    return tuple(rows)


def make_snapshot(data_revision: int = 1) -> MapRenderSnapshot:
    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            MapLayerSnapshot(
                id="10k:facies",
                name="Facies",
                layer_type="vector",
                extent=(0.0, 0.0, SIDE * 10.0, SIDE * 10.0),
                crs="EPSG:3857",
                data_revision=data_revision,
                style_revision=1,
                features=features(),
                style={"fill": "#6c8ebf", "stroke": "#26364d", "stroke_width": 1.0},
            ),
        ),
    )


def new_backend() -> FallbackMapRenderBackend:
    backend = FallbackMapRenderBackend()
    backend.set_layer_snapshot(make_snapshot())
    backend.set_output_size(800, 600)
    backend.set_dpi(96.0)
    return backend


full_extent = (0.0, 0.0, SIDE * 10.0, SIDE * 10.0)
pan_a = (300.0, 300.0, 1100.0, 1100.0)
pan_b = (320.0, 300.0, 1120.0, 1100.0)  # 20px right pan at 800px wide viewport


def timed(label: str, fn) -> float:
    start = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - start
    print(f"{label}: {elapsed * 1000:.1f} ms")
    return elapsed


# --- 1. Pixel identity: strip reuse must equal a full render ---
ref = new_backend()
ref.set_extent(pan_b)
ref_frame = ref.render_sync()

inc = new_backend()
inc.set_extent(pan_a)
inc.render_sync()
inc.set_extent(pan_b)
inc_frame = inc.render_sync()  # pan A -> B via strip reuse
print("strip reuse frame identical to full render:", inc_frame.rgba == ref_frame.rgba)
print("diagnostics:", inc.fallback_diagnostics())

# --- 2. Identical input short-circuit ---
inc2 = new_backend()
inc2.set_extent(pan_a)
inc2.render_sync()
g1 = inc2.render_sync()
g2 = inc2.render_sync()
print("identical-input: gen up, no rasterization:", g2.generation > g1.generation, inc2.fallback_diagnostics())

# --- 3. Edit invalidates reuse ---
inc3 = new_backend()
inc3.set_extent(pan_a)
inc3.render_sync()
inc3.set_layer_snapshot(make_snapshot(data_revision=2))
inc3.render_sync()
print("edit -> full rasterization:", inc3.fallback_diagnostics())

# --- 4. Zoom falls back to full rasterization ---
inc4 = new_backend()
inc4.set_extent(pan_a)
inc4.render_sync()
inc4.set_extent((300.0, 300.0, 600.0, 600.0))
inc4.render_sync()
print("zoom -> full rasterization:", inc4.fallback_diagnostics())

# --- 5. Timings: 60-step pan at a realistic viewport ---
backend = new_backend()
backend.set_extent(full_extent)
timed("cold full-view render (all 10k visible, culled=0)", backend.render_sync)
backend.set_extent(pan_a)
timed("cold pan-viewport render (culled)", backend.render_sync)
start = time.perf_counter()
for step in range(60):
    backend.set_extent((300.0 + step * 20.0, 300.0, 1100.0 + step * 20.0, 1100.0))
    backend.render_sync()
total = time.perf_counter() - start
print(f"60 incremental pan steps: {total * 1000:.1f} ms total, diagnostics: {backend.fallback_diagnostics()}")

# zoom-in series
backend2 = new_backend()
backend2.set_extent(pan_a)
start = time.perf_counter()
for step in range(10):
    xmin, ymin, xmax, ymax = backend2._extent
    cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
    backend2.set_extent(
        (cx + (xmin - cx) * 0.8, cy + (ymin - cy) * 0.8, cx + (xmax - cx) * 0.8, cy + (ymax - cy) * 0.8)
    )
    backend2.render_sync()
print(f"10 zoom-in steps: {(time.perf_counter() - start) * 1000:.1f} ms total, diagnostics: {backend2.fallback_diagnostics()}")
