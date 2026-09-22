#!/usr/bin/env python3
"""Local before/after benchmark for the Workbench well-log typed adapter.

The ``legacy`` column deliberately models the pre-session adapter hot path:
Python list materialization followed by a per-sample ``math.isfinite`` scan.
The ``retained`` column calls the production adapter with immutable NumPy
buffers.  It is a local diagnostic; it writes no benchmark artifacts.
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# Allow ``python benchmarks/welllog_adapter_benchmark.py`` from a checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paleo_workbench.viz.welllog_engine_adapter import adapt_well_log_data


@dataclass
class Curve:
    name: str
    depth: np.ndarray
    values: np.ndarray
    unit: str = "api"
    display_range: tuple[float, float] = (0.0, 200.0)


@dataclass
class Well:
    well_name: str
    curves: list[Curve]
    top_depth: float
    bottom_depth: float
    lithology: list[object]
    facies: list[object]


def _legacy_normalize(curve: Curve) -> tuple[np.ndarray, np.ndarray]:
    """The former list/Python-loop normalization, retained only for baseline."""
    depth = np.asarray(list(curve.depth), dtype=np.float64).reshape(-1)
    values = np.asarray(list(curve.values), dtype=np.float64).reshape(-1)
    count = min(depth.size, values.size)
    keep = [
        index
        for index in range(count)
        if math.isfinite(float(depth[index])) and math.isfinite(float(values[index]))
    ]
    return depth[keep], values[keep]


def _make_well(samples: int, tracks: int) -> Well:
    depth = np.linspace(1000.0, 1000.0 + samples / 10.0, samples, dtype=np.float64)
    depth.setflags(write=False)
    curves: list[Curve] = []
    for index in range(tracks):
        values = (80.0 + index * 3.0 + np.sin(depth / (7.0 + index))).astype(
            np.float64, copy=False
        )
        values.setflags(write=False)
        curves.append(
            Curve(
                name=("GR" if index == 0 else f"CURVE_{index}"),
                depth=depth,
                values=values,
                unit="api",
            )
        )
    return Well("BENCH", curves, float(depth[0]), float(depth[-1]), [], [])


def _measure(action, repeats: int) -> tuple[float, float]:
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        action()
        samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(samples), float(np.percentile(samples, 95))


def _parse_csv(raw: str) -> list[int]:
    return [int(part) for part in raw.split(",") if part.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", default="10000,100000,1000000")
    parser.add_argument("--tracks", default="1,4,8")
    parser.add_argument("--repeats", type=int, default=5)
    args = parser.parse_args()

    print(
        "samples tracks legacy_p50_ms legacy_p95_ms retained_p50_ms "
        "retained_p95_ms speedup zero_copy_curves"
    )
    for sample_count in _parse_csv(args.samples):
        for track_count in _parse_csv(args.tracks):
            well = _make_well(sample_count, track_count)
            legacy_p50, legacy_p95 = _measure(
                lambda: [_legacy_normalize(curve) for curve in well.curves], args.repeats
            )
            retained_p50, retained_p95 = _measure(
                lambda: adapt_well_log_data(well), args.repeats
            )
            plan = adapt_well_log_data(well)
            zero_copy = sum(
                np.shares_memory(curve.depth, source.depth)
                and np.shares_memory(curve.values, source.values)
                for curve, source in zip(plan.curves, well.curves)
            )
            print(
                f"{sample_count} {track_count} {legacy_p50:.2f} {legacy_p95:.2f} "
                f"{retained_p50:.2f} {retained_p95:.2f} "
                f"{legacy_p50 / retained_p50:.1f}x "
                f"{zero_copy}/{track_count}"
            )


if __name__ == "__main__":
    main()
