#!/usr/bin/env python
"""Local render-engine benchmark: snapshot build + fallback render at three scales.

Measures the unified composition path end to end with synthetic geological
feature mixes (well points, contour lines, facies polygons):

- snapshot build time (document_render_snapshot with authoritative revisions)
- first render (cold: includes geometry preparation)
- viewport-change render (warm prepared cache, new frame)
- unchanged re-render (frame cache hit)
- zoomed-in render (viewport culling active)
- peak process RSS

Run:
    QT_QPA_PLATFORM=offscreen python benchmarks/render_engine_benchmark.py [--sizes 100 10000 100000] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _build_records(total: int) -> list[dict]:
    """Geologically-shaped mix: 50% wells, 30% contours, 20% facies polygons."""
    records: list[dict] = []
    wells = total * 50 // 100
    lines = total * 30 // 100
    polygons = max(0, total - wells - lines)
    for index in range(wells):
        records.append(
            {
                "id": f"well-{index}",
                "kind": "well",
                "name": f"W{index}",
                "coordinates": [(index * 1.3) % 1000.0, (index * 2.7) % 1000.0],
                "properties": {"name": f"well-{index}"},
            }
        )
    for index in range(lines):
        coordinates = [
            [((index * 13.7 + step * 0.9) % 1000.0), ((index * 7.1 + step * 1.1) % 1000.0)]
            for step in range(40)
        ]
        records.append(
            {
                "id": f"line-{index}",
                "kind": "line",
                "name": f"L{index}",
                "coordinates": coordinates,
                "properties": {},
            }
        )
    for index in range(polygons):
        base_x, base_y = (index * 17.3) % 900.0, (index * 29.9) % 900.0
        ring = [[base_x, base_y]]
        ring.extend([base_x + 30 * (1 + (step % 3)), base_y + 25 * ((step % 4) + 1)] for step in range(8))
        ring.append([base_x, base_y])
        records.append(
            {
                "id": f"facies-{index}",
                "kind": "facies",
                "name": f"F{index}",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "coordinates": [ring],
                "properties": {"facies": "delta"},
            }
        )
    return records


def _rss_mb() -> float:
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmHWM:"):
                    return float(line.split()[1]) / 1024.0
    except OSError:
        pass
    return -1.0


# ---------------------------------------------------------------------------
# Legacy reference renderer: the origin/main fallback implementation, kept
# verbatim so the benchmark measures old-vs-new under identical machine load
# in the same process.
# ---------------------------------------------------------------------------


def _legacy_render_ms(snapshot, extent, width, height) -> float:
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF

    background = QColor("#181c22")

    def color(value, fallback):
        result = QColor(str(value or fallback))
        return result if result.isValid() else QColor(fallback)

    xmin, ymin, xmax, ymax = extent

    def screen_point(point):
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            return None
        try:
            x, y = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            return None
        return QPointF(
            (x - xmin) * width / (xmax - xmin),
            height - (y - ymin) * height / (ymax - ymin),
        )

    def path_of(rings):
        path = QPainterPath()
        for ring in rings if isinstance(rings, (list, tuple)) else ():
            polygon = QPolygonF()
            for point in ring if isinstance(ring, (list, tuple)) else ():
                screen = screen_point(point)
                if screen is not None:
                    polygon.append(screen)
            if len(polygon) >= 3:
                path.addPolygon(polygon)
        path.setFillRule(Qt.FillRule.OddEvenFill)
        return path

    def draw_geometry(painter, geometry, style):
        if not isinstance(geometry, dict):
            return
        geometry_type = str(geometry.get("type") or "")
        coordinates = geometry.get("coordinates")
        fill = color(style.get("fill"), "#6c8ebf")
        stroke = color(style.get("stroke"), "#26364d")
        try:
            pen_width = max(0.0, float(style.get("stroke_width", 1.0)))
        except (TypeError, ValueError):
            pen_width = 1.0
        painter.setPen(QPen(stroke, pen_width))
        painter.setBrush(fill)
        if geometry_type == "Point":
            center = screen_point(coordinates)
            if center is None:
                return
            try:
                radius = max(1.0, float(style.get("marker_size", 6.0)) / 2.0)
            except (TypeError, ValueError):
                radius = 3.0
            painter.drawEllipse(center, radius, radius)
            return
        if geometry_type == "MultiPoint" and isinstance(coordinates, (list, tuple)):
            for point in coordinates:
                draw_geometry(painter, {"type": "Point", "coordinates": point}, style)
            return
        if geometry_type == "LineString":
            points = [screen_point(point) for point in coordinates or ()]
            valid = [point for point in points if point is not None]
            if len(valid) >= 2:
                path = QPainterPath(valid[0])
                for point in valid[1:]:
                    path.lineTo(point)
                painter.drawPath(path)
            return
        if geometry_type == "MultiLineString" and isinstance(coordinates, (list, tuple)):
            for line in coordinates:
                draw_geometry(painter, {"type": "LineString", "coordinates": line}, style)
            return
        if geometry_type == "Polygon":
            painter.drawPath(path_of(coordinates))
            return
        if geometry_type == "MultiPolygon" and isinstance(coordinates, (list, tuple)):
            for polygon in coordinates:
                painter.drawPath(path_of(polygon))

    image = QImage(width, height, QImage.Format.Format_RGBA8888)
    painter = QPainter(image)
    started = time.perf_counter()
    image.fill(background)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for layer in snapshot.layers:
        if not layer.visible or layer.opacity <= 0.0:
            continue
        painter.save()
        painter.setOpacity(max(0.0, min(1.0, float(layer.opacity))))
        for feature in layer.features:
            draw_geometry(painter, feature.get("geometry"), layer.style)
        painter.restore()
    painter.end()
    return (time.perf_counter() - started) * 1000.0


def run_size(total: int, *, viewport: tuple[float, float, float, float] = (0.0, 0.0, 1000.0, 1000.0)) -> dict:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])

    from paleo_workbench.mapping.map_render_backend import FallbackMapRenderBackend
    from paleo_workbench.mapping.map_document_snapshot import document_render_snapshot
    from paleo_workbench.project.models import PaleoMapDocument

    document = PaleoMapDocument(id=f"bench-{total}", name="bench", linked_target_horizon="H1")
    records = _build_records(total)

    # --- snapshot build (first, cold) ---
    revisions = {"facies": 1, "well": 1, "line": 1, "label": 1}

    class _Owner:
        """Weakref-able stand-in for MapAuthoringDocument (cache is owner-scoped)."""

    owner = _Owner()
    started = time.perf_counter()
    snapshot = document_render_snapshot(
        document, project_crs="EPSG:3857", records=records, data_revisions=revisions,
        cache_owner=owner,
    )
    snapshot_cold_ms = (time.perf_counter() - started) * 1000.0

    # --- snapshot build (repeated, revisions unchanged → cached) ---
    started = time.perf_counter()
    document_render_snapshot(
        document, project_crs="EPSG:3857", records=records, data_revisions=revisions,
        cache_owner=owner,
    )
    snapshot_warm_ms = (time.perf_counter() - started) * 1000.0

    backend = FallbackMapRenderBackend()
    backend.initialize()
    backend.set_layer_snapshot(snapshot)
    backend.set_extent(viewport)
    backend.set_output_size(1200, 800)
    backend.set_dpi(96.0)

    # --- first render (cold: geometry preparation + paint + RGBA copy) ---
    started = time.perf_counter()
    backend.render_sync()
    first_render_ms = (time.perf_counter() - started) * 1000.0

    # --- viewport change (warm prepared cache) ---
    backend.set_extent((100.0, 100.0, 900.0, 900.0))
    started = time.perf_counter()
    backend.render_sync()
    pan_render_ms = (time.perf_counter() - started) * 1000.0

    # --- unchanged composition (frame cache) ---
    started = time.perf_counter()
    backend.render_sync()
    cached_render_ms = (time.perf_counter() - started) * 1000.0

    # --- zoomed to 5% of extent (culling) ---
    backend.set_extent((400.0, 400.0, 450.0, 450.0))
    started = time.perf_counter()
    backend.render_sync()
    zoom_render_ms = (time.perf_counter() - started) * 1000.0

    # --- legacy (origin/main renderer) reference under identical load ---
    legacy_full_ms = _legacy_render_ms(snapshot, viewport, 1200, 800)

    diagnostics = backend.render_diagnostics()
    backend.shutdown()
    return {
        "features": total,
        "snapshot_build_cold_ms": round(snapshot_cold_ms, 2),
        "snapshot_build_warm_ms": round(snapshot_warm_ms, 2),
        "first_render_ms": round(first_render_ms, 2),
        "pan_render_ms": round(pan_render_ms, 2),
        "cached_render_ms": round(cached_render_ms, 3),
        "zoom_render_ms": round(zoom_render_ms, 2),
        "legacy_full_view_ms": round(legacy_full_ms, 2),
        "features_total": diagnostics["features_total"],
        "cull_ratio_at_zoom": diagnostics["features_drawn"] / max(1, diagnostics["features_total"]),
        "vertices_simplified": diagnostics["vertices_simplified"],
        "peak_rss_mb": round(_rss_mb(), 1),
        "app": bool(app),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="*", type=int, default=[100, 10_000, 100_000])
    parser.add_argument("--json", type=Path, default=None, help="also write results as JSON")
    args = parser.parse_args()

    results = []
    header = (
        f"{'features':>9} | {'snap cold':>9} | {'snap warm':>9} | {'1st render':>10} | "
        f"{'pan':>8} | {'cached':>8} | {'zoom(cull%)':>11} | {'legacy full':>11} | {'RSS MB':>7}"
    )
    print(header)
    print("-" * len(header))
    for size in args.sizes:
        result = run_size(size)
        results.append(result)
        print(
            f"{result['features']:>9} | {result['snapshot_build_cold_ms']:>8.2f} | "
            f"{result['snapshot_build_warm_ms']:>8.2f} | {result['first_render_ms']:>9.2f} | "
            f"{result['pan_render_ms']:>7.2f} | {result['cached_render_ms']:>7.3f} | "
            f"{result['zoom_render_ms']:>5.2f}/{result['cull_ratio_at_zoom']*100:>3.0f}% | "
            f"{result['legacy_full_view_ms']:>10.2f} | "
            f"{result['peak_rss_mb']:>7.1f}"
        )
        sys.stdout.flush()

    if args.json is not None:
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
