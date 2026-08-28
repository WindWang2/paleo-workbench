#!/usr/bin/env python
"""L2 VRAM texture-cache benchmark — issue #1078 acceptance evidence.

Measures the repeated-slice-browsing path at three realistic slice sizes:

- cold render  — full ProfileVD.render: percentile scan + normalize + image
- L2 hit       — ProfileVD.render_indexed from the VramTextureCache content
- speedup      — cold / L2-hit ratio

Acceptance: repeated browsing of an already-seen slice stays under 16 ms
(L2-hit path) at production slice sizes.

Run:
    QT_QPA_PLATFORM=offscreen python benchmarks/vram_l2_hit_benchmark.py \
        [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()

from PySide6.QtWidgets import QApplication

from geoviz_seismic.profile_vd import ProfileVD

# (n_samples, n_traces) — inline-slice-shaped, matching survey aspect ratios.
SLICE_SHAPES = [
    (750, 750),      # ~0.56 M samples: typical older survey slice
    (1050, 1500),    # ~1.6 M samples: modern full-res inline
    (2000, 2000),    # 4 M samples: 100G-class slice (spec #1075)
]
REPEATS = 21
BUDGET_MS = 16.0


def _bench_shape(app: QApplication, n_samples: int, n_traces: int) -> dict:
    import numpy as np

    vd = ProfileVD()
    vd.resize(1100, 800)
    vd.show()
    data = np.random.default_rng(42).normal(
        size=(n_samples, n_traces)
    ).astype(np.float32)

    t0 = time.perf_counter()
    vd.render(data)  # cold: percentile scan + normalize + QImage build
    app.processEvents()
    cold_ms = (time.perf_counter() - t0) * 1000.0

    snap = vd.indexed_snapshot()
    assert snap is not None, "cold render must produce an L2-publishable snapshot"
    indexed, clip_range = snap

    hit_ms = []
    for _ in range(REPEATS):
        t0 = time.perf_counter()
        vd.render_indexed(data, indexed, clip_range)
        app.processEvents()
        hit_ms.append((time.perf_counter() - t0) * 1000.0)
    hit_median = statistics.median(hit_ms)

    # End-to-end L2-hit path through the real SeismicView pipeline: key
    # build + VRAM.get + panel refresh — what a repeated browse actually pays.
    pipeline_median = _bench_pipeline(app, data)

    return {
        "shape": [n_samples, n_traces],
        "slice_px": n_samples * n_traces,
        "texture_bytes": int(indexed.nbytes),
        "cold_ms": round(cold_ms, 2),
        "l2_hit_median_ms": round(hit_median, 2),
        "l2_hit_min_ms": round(min(hit_ms), 2),
        "pipeline_hit_median_ms": round(pipeline_median, 2),
        "speedup": round(cold_ms / max(hit_median, 1e-9), 1),
        "under_16ms": hit_median < BUDGET_MS and pipeline_median < BUDGET_MS,
    }


def _bench_pipeline(app: QApplication, data) -> float:
    from geoviz_seismic.seismic_view import SeismicView

    view = SeismicView(auto_load=False)
    view.resize(1200, 900)
    view.show()
    try:
        view._update_profile_panel("inline", 10, data)  # cold (fills L2)
        app.processEvents()
        hit_ms = []
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            view._update_profile_panel("inline", 10, data)  # L2 hit
            app.processEvents()
            hit_ms.append((time.perf_counter() - t0) * 1000.0)
        return statistics.median(hit_ms)
    finally:
        view.deleteLater()
        app.processEvents()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None, help="write results as JSON")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([])

    results = [_bench_shape(app, s, t) for s, t in SLICE_SHAPES]

    header = (
        f"{'slice (samples x traces)':>26} {'texture':>10} {'cold ms':>9} "
        f"{'L2 hit ms':>10} {'pipeline ms':>12} {'speedup':>8} {'<16 ms':>7}"
    )
    print(header)
    print("-" * len(header))
    all_pass = True
    for r in results:
        all_pass &= r["under_16ms"]
        shape = f"{r['shape'][0]} x {r['shape'][1]}"
        print(
            f"{shape:>26} {r['texture_bytes'] / 1024:>8.0f}K "
            f"{r['cold_ms']:>9.2f} {r['l2_hit_median_ms']:>10.2f} "
            f"{r['pipeline_hit_median_ms']:>12.2f} "
            f"{r['speedup']:>7.1f}x {'PASS' if r['under_16ms'] else 'FAIL':>7}"
        )

    print()
    print(
        "verdict: " + ("all slice sizes under 16 ms on the L2-hit path"
                       if all_pass else "AT LEAST ONE SIZE ABOVE 16 ms — FAIL")
    )

    if args.json:
        args.json.write_text(
            json.dumps({"budget_ms": BUDGET_MS, "results": results}, indent=2),
            encoding="utf-8",
        )
        print(f"results written to {args.json}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
