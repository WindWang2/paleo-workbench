#!/usr/bin/env python3
"""Local-only benchmark for map edit picking and frame/snapshot delivery.

Run with ``QT_QPA_PLATFORM=offscreen python scripts/bench_map_interaction.py``.
It deliberately prints results only; profiles and datasets are not written into
the repository.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

import geoviz as api
from paleo_workbench.mapping import map_render_backend as backend_module
from paleo_workbench.mapping.map_render_backend import (
    MapLayerSnapshot,
    MapRenderSnapshot,
    QgisMapRenderBackend,
)
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene


def _percentile(samples: list[float], percent: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percent)))]


def _summary(samples: list[float]) -> str:
    return f"p50={statistics.median(samples):.3f}ms p95={_percentile(samples, .95):.3f}ms"


def _wells(count: int) -> PaleoMapDocument:
    side = max(1, int(count**0.5))
    return PaleoMapDocument(
        name="benchmark",
        linked_target_horizon="H",
        well_overlays=[
            {
                "id": f"well-{index}",
                "name": "well",
                "x": float(index % side) * 10.0,
                "y": float(index // side) * 10.0,
            }
            for index in range(count)
        ],
    )


def _measure_hit_path(scene: MapEditScene, *, queries: int, rounds: int) -> tuple[str, str, float, int]:
    count = scene.feature_count()
    side = max(1, int(count**0.5))
    targets = [
        (float((index % count) % side) * 10.0, float((index % count) // side) * 10.0)
        for index in range(queries)
    ]
    legacy_samples: list[float] = []
    bounded_samples: list[float] = []
    for _ in range(rounds):
        for x, y in targets:
            started = time.perf_counter()
            records = [item.to_record() for item in scene._items_by_id.values()]
            api.hit_test(records, x, y, tolerance=0.5)
            legacy_samples.append((time.perf_counter() - started) * 1_000)
        for x, y in targets:
            started = time.perf_counter()
            scene.hit_test_at(x, y, tolerance=0.5)
            bounded_samples.append((time.perf_counter() - started) * 1_000)
    diagnostics = scene.hit_query_diagnostics()
    candidates = diagnostics["candidate_count"] / max(1, diagnostics["query_count"])
    return _summary(legacy_samples), _summary(bounded_samples), candidates, diagnostics["record_build_count"]


def _snapshot(count: int, *, data_revision: int = 1, style_revision: int = 1) -> MapRenderSnapshot:
    side = max(1, int(count**0.5))
    features = tuple(
        {
            "id": f"point-{index}",
            "geometry": {
                "type": "Point",
                "coordinates": [float(index % side) * 10.0, float(index // side) * 10.0],
            },
            "properties": {"group": str(index % 4)},
        }
        for index in range(count)
    )
    layer = MapLayerSnapshot(
        id="points",
        name="Points",
        layer_type="vector",
        extent=(0.0, 0.0, float(side * 10), float(side * 10)),
        crs="EPSG:3857",
        data_revision=data_revision,
        style_revision=style_revision,
        features=features,
        style={"fill": "#55b6ff"},
    )
    return MapRenderSnapshot(project_crs="EPSG:3857", layers=(layer,))


def _measure_snapshot(count: int, rounds: int) -> tuple[str, str, str]:
    snapshot = _snapshot(count)
    cold: list[float] = []
    warm: list[float] = []
    single_feature_edit: list[float] = []
    for _ in range(rounds):
        backend = QgisMapRenderBackend()
        started = time.perf_counter()
        backend_module._qgis_snapshot(
            snapshot,
            vector_feature_payloads=backend._vector_feature_payloads,
            vector_feature_entries=backend._vector_feature_entries,
            encoding_stats=backend,
        )
        cold.append((time.perf_counter() - started) * 1_000)
        styled = replace(snapshot.layers[0], style_revision=snapshot.layers[0].style_revision + 1)
        started = time.perf_counter()
        backend_module._qgis_snapshot(
            MapRenderSnapshot(project_crs=snapshot.project_crs, layers=(styled,)),
            vector_feature_payloads=backend._vector_feature_payloads,
            vector_feature_entries=backend._vector_feature_entries,
            encoding_stats=backend,
        )
        warm.append((time.perf_counter() - started) * 1_000)
        changed_feature = dict(snapshot.layers[0].features[0])
        changed_feature["geometry"] = {"type": "Point", "coordinates": [-1.0, -1.0]}
        changed_layer = replace(
            snapshot.layers[0],
            data_revision=snapshot.layers[0].data_revision + 1,
            features=(changed_feature, *snapshot.layers[0].features[1:]),
        )
        started = time.perf_counter()
        backend_module._qgis_snapshot(
            MapRenderSnapshot(project_crs=snapshot.project_crs, layers=(changed_layer,)),
            vector_feature_payloads=backend._vector_feature_payloads,
            vector_feature_entries=backend._vector_feature_entries,
            encoding_stats=backend,
        )
        single_feature_edit.append((time.perf_counter() - started) * 1_000)
    return _summary(cold), _summary(warm), _summary(single_feature_edit)


def _measure_qimage(width: int, height: int, rounds: int) -> tuple[str, str]:
    payload = bytes(width * height * 4)
    deep: list[float] = []
    wrapped: list[float] = []
    for _ in range(rounds):
        started = time.perf_counter()
        QImage(payload, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
        deep.append((time.perf_counter() - started) * 1_000)
        started = time.perf_counter()
        QImage(payload, width, height, width * 4, QImage.Format.Format_RGBA8888)
        wrapped.append((time.perf_counter() - started) * 1_000)
    return _summary(deep), _summary(wrapped)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", type=int, nargs="+", default=[1_000, 10_000, 50_000])
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    QApplication.instance() or QApplication([])
    for count in args.counts:
        scene = MapEditScene()
        scene.load_document(_wells(count))
        before, after, candidates, serializations = _measure_hit_path(
            scene, queries=args.queries, rounds=args.rounds
        )
        print(
            f"hit {count:>6}: before {before}; after {after}; "
            f"serializations/query before={count} after=0; candidates/query={candidates:.2f}; "
            f"initial records={serializations}"
        )
    snapshot_count = max(args.counts)
    cold, warm, single_feature_edit = _measure_snapshot(snapshot_count, args.rounds)
    print(
        f"snapshot {snapshot_count:>6}: cold {cold}; style-only cached {warm}; "
        f"single-feature cached {single_feature_edit}"
    )
    for width, height in ((1600, 1600), (3840, 2160)):
        deep, wrapped = _measure_qimage(width, height, args.rounds)
        print(
            f"qimage {width}x{height} ({width * height * 4 / 1024 / 1024:.2f} MiB): "
            f"deep-copy {deep}; wrapped {wrapped}"
        )


if __name__ == "__main__":
    main()
