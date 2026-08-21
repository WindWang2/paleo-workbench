#!/usr/bin/env python
"""QGIS authoring-path benchmark: mirror lifecycle + render at scale.

Measures the native bridge through the host seam (``QgisMapRenderBackend``)
with synthetic geological feature mixes at 10k / 100k features:

- initial snapshot+mirror creation (cold)
- first render
- pan / zoom renders (revision-keyed mirrors must not rebuild)
- style-only update (in-place re-style, no rebuild)
- visibility toggle
- categorized vs rule renderer cost
- render cancellation (request then cancel immediately)

Run (bridge required):
    QT_QPA_PLATFORM=offscreen python benchmarks/qgis_authoring_benchmark.py \
        [--sizes 10000 100000] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication


def _features(total: int) -> tuple[dict, ...]:
    """Geological mix: 50% well points, 30% contour lines, 20% facies polygons."""
    wells = total * 50 // 100
    lines = total * 30 // 100
    polygons = total - wells - lines
    features: list[dict] = []
    for index in range(wells):
        x = float(index % 500) * 2.0
        y = float(index % 400) * 2.5
        features.append(
            {
                "id": f"well-{index}",
                "geometry": {"type": "Point", "coordinates": [x, y]},
                "properties": {"well_type": "exploration" if index % 3 else "production", "name": f"W{index}"},
            }
        )
    for index in range(lines):
        x0 = float(index % 250) * 4.0
        features.append(
            {
                "id": f"contour-{index}",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[x0, 0.0], [x0 + 40.0, 60.0], [x0 + 80.0, 120.0]],
                },
                "properties": {"elevation": str(index % 90)},
            }
        )
    for index in range(polygons):
        x0 = float(index % 200) * 5.0
        features.append(
            {
                "id": f"facies-{index}",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[x0, 0.0], [x0 + 8.0, 0.0], [x0 + 8.0, 8.0], [x0, 8.0], [x0, 0.0]]],
                },
                "properties": {"lithology": ("sandstone" if index % 2 else "shale")},
            }
        )
    return tuple(features)


def _snapshot(features, *, style: dict | None = None, visible: bool = True,
              style_revision: int = 1):
    """One snapshot with three kind-homogeneous layers (well/contour/facies),
    mirroring how MapAuthoringDocument groups records."""
    from paleo_workbench.mapping.map_render_backend import (
        MapLayerSnapshot,
        MapRenderSnapshot,
    )

    def layer(layer_id: str, name: str, selected):
        kwargs: dict = {}
        if style is not None:
            kwargs["style"] = style
        return MapLayerSnapshot(
            id=layer_id,
            name=name,
            layer_type="vector",
            extent=(0.0, 0.0, 1200.0, 1000.0),
            crs="EPSG:3857",
            data_revision=1,
            style_revision=style_revision,
            visible=visible,
            features=tuple(feature for feature in features if feature["id"].startswith(selected)),
            **kwargs,
        )

    return MapRenderSnapshot(
        project_crs="EPSG:3857",
        layers=(
            layer("wells", "Wells", "well-"),
            layer("contours", "Contours", "contour-"),
            layer("facies", "Facies", "facies-"),
        ),
    )


def _timed(fn, *, repeat: int = 1):
    best = float("inf")
    for _ in range(repeat):
        started = time.perf_counter()
        fn()
        best = min(best, (time.perf_counter() - started) * 1000.0)
    return round(best, 1)


def run_scale(total: int) -> dict:
    from paleo_workbench.mapping.map_render_backend import QgisMapRenderBackend

    features = _features(total)
    backend = QgisMapRenderBackend()
    if not backend.is_available:
        raise SystemExit("qgis_render_bridge is not built; cannot benchmark the QGIS path")
    backend.initialize()
    results: dict = {"features": total}
    try:
        # Cold: snapshot encode + mirror build.
        started = time.perf_counter()
        backend.set_layer_snapshot(_snapshot(features))
        backend.set_extent((0.0, 0.0, 1200.0, 1000.0))
        backend.set_output_size(1200, 800)
        backend.set_dpi(96.0)
        results["initial_mirror_ms"] = round((time.perf_counter() - started) * 1000.0, 1)

        started = time.perf_counter()
        frame = backend.render_sync()
        results["first_render_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
        assert frame.width == 1200

        def pan():
            backend.set_extent((20.0, 10.0, 1220.0, 1010.0))
            return backend.render_sync()

        def zoom():
            backend.set_extent((300.0, 250.0, 700.0, 550.0))
            return backend.render_sync()

        results["pan_render_ms"] = _timed(pan, repeat=3)
        results["zoom_render_ms"] = _timed(zoom, repeat=3)

        # Style-only update on a fresh revision: must re-use the payload cache.
        before = backend.native_encoding_diagnostics()
        backend.set_layer_snapshot(
            _snapshot(features, style={"fill": "#8844aa"}, style_revision=2)
        )
        after = backend.native_encoding_diagnostics()
        results["style_only_update_ms"] = _timed(
            lambda: backend.render_sync(), repeat=2
        )
        results["feature_payload_reused_on_style_update"] = (
            after["feature_encoding_cache_hits"] > before["feature_encoding_cache_hits"]
        )

        # Visibility toggle.
        backend.set_layer_snapshot(_snapshot(features, style={"fill": "#8844aa"}, visible=False, style_revision=3))
        hidden = backend.render_sync()
        results["hidden_frame_opaque_px"] = sum(
            1 for index in range(0, len(hidden.rgba), 997) if hidden.rgba[index] != 0
        )

        # Categorized renderer.
        categorized = {
            "renderer": "categorized",
            "field": "lithology",
            "categories": {"sandstone": "#d9c58b", "shale": "#7f9db9"},
        }
        backend.set_layer_snapshot(_snapshot(features, style=categorized, style_revision=4))
        results["categorized_render_ms"] = _timed(lambda: backend.render_sync(), repeat=2)

        # Rule renderer over point attributes.
        ruled = {
            "renderer": "rule",
            "rules": [
                {"name": "exploration", "expression": "\"well_type\" = 'exploration'", "fill": "#22b8a7"},
                {"name": "production", "expression": "\"well_type\" = 'production'", "fill": "#e8590c"},
            ],
        }
        backend.set_layer_snapshot(_snapshot(features, style=ruled, style_revision=5))
        results["rule_render_ms"] = _timed(lambda: backend.render_sync(), repeat=2)

        # Cancellation: request then cancel; next render still correct.
        backend.request_render()
        backend.cancel_render()
        frame_after_cancel = backend.render_sync()
        results["render_after_cancel_ok"] = len(frame_after_cancel.rgba) == (
            frame_after_cancel.height * frame_after_cancel.stride
        )

        diagnostics = backend.native_encoding_diagnostics()
        results["encoding_cache_hits_total"] = diagnostics["feature_encoding_cache_hits"]
    finally:
        backend.shutdown()

    from paleo_workbench.mapping.map_render_backend import (
        shutdown_live_fallback_backends,
    )

    shutdown_live_fallback_backends()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="*", type=int, default=[10_000, 100_000])
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args()

    app = QApplication.instance() or QApplication([sys.argv[0]])

    output = {}
    for size in args.sizes:
        output[str(size)] = run_scale(size)
    print(json.dumps(output, indent=2))
    if app is None:  # pragma: no cover
        return 1
    if args.json:
        args.json.write_text(json.dumps(output, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
