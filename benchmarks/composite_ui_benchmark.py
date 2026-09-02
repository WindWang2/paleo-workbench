#!/usr/bin/env python
"""Composite authoring interactive-path benchmark (fallback renderer).

Verifies the workstation-composite performance contract at 10k / 50k / 100k
features in one editable layer:

- initial snapshot publish (cold spatial index build happens on first hit)
- visibility toggle / opacity change / reorder through LayerManagerPanel →
  must NOT rebuild geometry (snapshot signature dedup: expect sub-ms)
- identify (revision-cached cell grid) and snapping
- digitize: add feature into the edit session + undo
- commit + sync_to_project (project save path)

Run:
    QT_QPA_PLATFORM=offscreen python benchmarks/composite_ui_benchmark.py \
        [--sizes 10000 50000 100000] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _bench(fn, *, repeat: int = 3) -> float:
    best = float("inf")
    for _ in range(repeat):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best * 1000.0  # ms


def _make_features(total: int):
    from paleo_workbench.mapping.vector_layer import VectorFeature

    wells = total * 50 // 100
    lines = total * 30 // 100
    polygons = max(0, total - wells - lines)
    features = []
    for i in range(wells):
        features.append(
            VectorFeature(
                f"w{i}",
                {"type": "Point", "coordinates": [i % 1000 * 0.001, (i // 1000) * 0.001]},
                {"name": f"W{i}", "kind": "well"},
            )
        )
    for i in range(lines):
        x0 = (i % 500) * 0.002
        y0 = (i // 500) * 0.002
        features.append(
            VectorFeature(
                f"l{i}",
                {"type": "LineString", "coordinates": [[x0, y0], [x0 + 0.01, y0 + 0.008], [x0 + 0.02, y0]]},
                {"kind": "contour"},
            )
        )
    for i in range(polygons):
        x0 = (i % 200) * 0.005
        y0 = (i // 200) * 0.005
        features.append(
            VectorFeature(
                f"p{i}",
                {
                    "type": "Polygon",
                    "coordinates": [[[x0, y0], [x0 + 0.02, y0], [x0 + 0.02, y0 + 0.015], [x0, y0 + 0.015], [x0, y0]]],
                },
                {"facies": "三角洲", "confidence": "中"},
            )
        )
    return features


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", nargs="+", type=int, default=[10000, 50000, 100000])
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args()

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from paleo_workbench.mapping.vector_layer import VectorFeature
    from paleo_workbench.ui.unified_map_canvas import UnifiedMapCanvas
    from paleo_workbench.ui.workstation.composite_document import LayerManagerPanel
    from paleo_workbench.ui.workstation.composite_editing import CompositeEditController

    rows: list[dict] = []
    header = (
        f"{'features':>9} | {'publish':>9} | {'toggle':>8} | {'opacity':>8} | "
        f"{'reorder':>8} | {'identify':>8} | {'snap':>8} | {'add+undo':>9} | {'commit':>8} | {'RSS MB':>7}"
    )
    print(header)
    print("-" * len(header))

    for size in args.sizes:
        canvas = UnifiedMapCanvas()
        canvas.resize(1200, 800)
        controller = CompositeEditController(project_crs="EPSG:4326")
        controller.attach_canvas(canvas)
        layer = controller.create_layer(f"bench-{size}", "polygon")
        for feature in _make_features(size):
            layer._features[feature.feature_id] = feature
        layer.data_revision += 1

        panel = LayerManagerPanel()
        panel.set_project_crs("EPSG:4326")
        display_layers = list(controller.snapshot_layers())
        panel.bind(canvas, display_layers)

        publish_ms = _bench(panel._publish)
        toggle_ms = _bench(
            lambda: (
                panel.set_layer_visible(layer.id, False),
                panel.set_layer_visible(layer.id, True),
            ),
            repeat=1,
        )
        opacity_ms = _bench(
            lambda: (
                panel.set_layer_opacity(layer.id, 0.55),
                panel.set_layer_opacity(layer.id, 1.0),
            ),
            repeat=1,
        )
        reorder_ms = _bench(
            lambda: (panel.move_layer(layer.id, +1), panel.move_layer(layer.id, -1)),
            repeat=1,
        )

        index = controller.snapping.index_for(layer)
        identify_ms = _bench(lambda: index.identify((0.5, 0.5), 0.01))
        controller.snapping.enabled = True
        snap_ms = _bench(
            lambda: controller.snapping.snap((0.5, 0.5), tolerance=0.01, layers=[layer])
        )

        controller.start_editing()
        session = layer.edit_session

        def _add_undo():
            session.add_feature(
                VectorFeature("bench-add", {"type": "Point", "coordinates": [0.5, 0.5]})
            )
            session.undo()

        add_undo_ms = _bench(_add_undo, repeat=1)
        session.add_feature(
            VectorFeature("bench-commit", {"type": "Point", "coordinates": [0.6, 0.6]})
        )

        class _Project:
            user_vector_layers: list = []

        project = _Project()
        commit_ms = _bench(
            lambda: (controller.save_edits(), controller.sync_to_project(project)),
            repeat=1,
        )

        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
        rows.append(
            {
                "features": size,
                "publish_ms": round(publish_ms, 2),
                "toggle_ms": round(toggle_ms, 3),
                "opacity_ms": round(opacity_ms, 3),
                "reorder_ms": round(reorder_ms, 3),
                "identify_ms": round(identify_ms, 2),
                "snap_ms": round(snap_ms, 2),
                "add_undo_ms": round(add_undo_ms, 3),
                "commit_sync_ms": round(commit_ms, 2),
                "rss_mb": round(rss_mb, 1),
            }
        )
        print(
            f"{size:>9} | {publish_ms:>8.2f} | {toggle_ms:>7.3f} | {opacity_ms:>7.3f} | "
            f"{reorder_ms:>7.3f} | {identify_ms:>7.2f} | {snap_ms:>7.2f} | {add_undo_ms:>8.3f} | "
            f"{commit_ms:>7.2f} | {rss_mb:>6.1f}"
        )
        controller.snapping._indexes.clear()
        canvas.shutdown()
        panel.deleteLater()
        app.processEvents()

    if args.json:
        Path(args.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
