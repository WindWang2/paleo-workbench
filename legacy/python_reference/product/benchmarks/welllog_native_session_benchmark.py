#!/usr/bin/env python3
"""Local native Session benchmark for complete WellLogEngine submissions.

Run with the locally built binding, for example::

  LD_PRELOAD=/usr/lib/libstdc++.so.6 \\
  PYTHONPATH=well-log-engine/build/dev-python/python:$PYTHONPATH \\
  QT_QPA_PLATFORM=minimal python benchmarks/welllog_native_session_benchmark.py

The minimal Qt platform intentionally measures retained-session work, not GPU
paint latency.  It writes no artifacts.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paleo_workbench.viz import welllog_engine_adapter as adapter


@dataclass
class Curve:
    name: str
    depth: np.ndarray
    values: np.ndarray
    unit: str = "api"
    display_range: tuple[float, float] = (0.0, 200.0)
    color: str = "#15803d"


@dataclass
class Well:
    well_name: str
    curves: list[Curve]
    top_depth: float
    bottom_depth: float
    lithology: list[object]
    facies: list[object]


def _well(samples: int, tracks: int, *, color: str = "#15803d") -> Well:
    depth = np.arange(1000.0, 1000.0 + samples, dtype=np.float64)
    depth.setflags(write=False)
    curves = []
    for index in range(tracks):
        values = (75.0 + index + np.sin(depth / (20.0 + index))).astype(np.float64)
        values.setflags(write=False)
        curves.append(Curve("GR" if index == 0 else f"C{index}", depth, values, color=color))
    return Well("NATIVE-BENCH", curves, float(depth[0]), float(depth[-1]), [], [])


def _dispose(view) -> None:
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _measure_update(view_class, first, action, repeats: int) -> tuple[float, float]:
    timings = []
    for _ in range(repeats):
        view = view_class()
        adapter.submit_plan_to_view(view, first)
        started = time.perf_counter()
        action(view)
        timings.append((time.perf_counter() - started) * 1000.0)
        _dispose(view)
    return statistics.median(timings), float(np.percentile(timings, 95))


def _wait_for_lod(view, document_id: str) -> tuple[dict, bool]:
    deadline = time.monotonic() + 10.0
    metrics = view.document_metrics(document_id)
    while metrics["preparation_state"] != 2 and time.monotonic() < deadline:
        view.poll_session()
        QCoreApplication.processEvents()
        time.sleep(0.002)
        metrics = view.document_metrics(document_id)
    return metrics, metrics["preparation_state"] == 2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=100_000)
    parser.add_argument("--tracks", type=int, default=4)
    parser.add_argument("--append", type=int, default=10_000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    _, view_class, _ = adapter.try_import_welllog()
    if view_class is None:
        raise SystemExit("built welllog binding is required on PYTHONPATH")
    QApplication.instance() or QApplication([])
    first = adapter.adapt_well_log_data(_well(args.samples, args.tracks))
    appended = adapter.adapt_well_log_data(_well(args.samples + args.append, args.tracks))
    styled = adapter.adapt_well_log_data(_well(args.samples, args.tracks, color="#b91c1c"))
    append_payload = adapter._append_payload(first, appended)
    assert append_payload is not None
    patch_payload = {
        "document_id": styled.document_id,
        "axis_id": adapter.stable_entity_id("document-axis", styled.well_name, "md"),
        "tracks": adapter._track_payload(styled),
    }

    def append(view) -> None:
        report = adapter.update_plan_to_view(view, appended, first)
        assert report["update_kind"] == "append"

    def style_patch(view) -> None:
        report = adapter.update_plan_to_view(view, styled, first)
        assert report["update_kind"] == "patch"

    # Each sample starts from the same already-submitted document; only the
    # replacement/append/patch operation is timed.
    full_p50, full_p95 = _measure_update(
        view_class, first, lambda view: adapter.submit_plan_to_view(view, appended), args.repeats
    )
    append_p50, append_p95 = _measure_update(view_class, first, append, args.repeats)
    patch_p50, patch_p95 = _measure_update(view_class, first, style_patch, args.repeats)
    bridge_append_p50, bridge_append_p95 = _measure_update(
        view_class, first, lambda view: view.append_curves(append_payload), args.repeats
    )
    bridge_patch_p50, bridge_patch_p95 = _measure_update(
        view_class, first, lambda view: view.patch_document(patch_payload), args.repeats
    )
    lod_view = view_class()
    adapter.submit_plan_to_view(lod_view, first)
    lod_before, lod_before_ready = _wait_for_lod(lod_view, first.document_id)
    lod_view.append_curves(append_payload)
    lod_after, lod_after_ready = _wait_for_lod(lod_view, appended.document_id)
    _dispose(lod_view)
    print("scenario samples tracks p50_ms p95_ms")
    print(f"full_replace {args.samples + args.append} {args.tracks} {full_p50:.2f} {full_p95:.2f}")
    print(f"adapter_append_{args.append} {args.samples} {args.tracks} {append_p50:.2f} {append_p95:.2f}")
    print(f"adapter_style_patch {args.samples} {args.tracks} {patch_p50:.2f} {patch_p95:.2f}")
    print(f"bridge_append_{args.append} {args.samples} {args.tracks} {bridge_append_p50:.2f} {bridge_append_p95:.2f}")
    print(f"bridge_style_patch {args.samples} {args.tracks} {bridge_patch_p50:.2f} {bridge_patch_p95:.2f}")
    print(
        "lod completed_tasks "
        f"{lod_before['completed_tasks']}->{lod_after['completed_tasks']} "
        f"derived_bytes {lod_before['cpu_derived_bytes']}->{lod_after['cpu_derived_bytes']} "
        f"prepared_points {lod_before['lod_points_avg']}->{lod_after['lod_points_avg']} "
        f"ready {lod_before_ready}->{lod_after_ready}"
    )


if __name__ == "__main__":
    main()
