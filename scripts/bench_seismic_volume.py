#!/usr/bin/env python3
"""Local seismic volume source / cache / preview benchmarks (not unit CI).

Usage:
  python scripts/bench_seismic_volume.py
  python scripts/bench_seismic_volume.py /path/to/file.sgy
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np


def _synthetic_segy(path: Path, n_il: int, n_xl: int, n_s: int) -> Path:
    import segyio

    spec = segyio.spec()
    spec.sorting = 2
    spec.format = 1
    spec.samples = list(range(n_s))
    spec.ilines = list(range(1, n_il + 1))
    spec.xlines = list(range(1, n_xl + 1))
    with segyio.create(str(path), spec) as f:
        for ili, il in enumerate(spec.ilines):
            for xli, xl in enumerate(spec.xlines):
                tr = np.linspace(0.0, 1.0, n_s, dtype=np.float32) + 0.01 * ili
                f.header[ili * n_xl + xli] = {
                    segyio.TraceField.INLINE_3D: il,
                    segyio.TraceField.CROSSLINE_3D: xl,
                }
                f.trace[ili * n_xl + xli] = tr
    return path


def bench_path(path: Path) -> dict:
    from paleo_workbench.viz.seismic_volume_cache import reset_global_seismic_cache
    from paleo_workbench.viz.seismic_volume_source import (
        SeismicVolumeSource,
        clear_seismic_source_registry,
    )

    clear_seismic_source_registry()
    reset_global_seismic_cache()

    src = SeismicVolumeSource(path)
    t0 = time.perf_counter()
    meta = src.metadata()
    metadata_ms = (time.perf_counter() - t0) * 1000.0

    # Cold first slice
    t0 = time.perf_counter()
    _ = src.read_inline(0)
    cold_ms = (time.perf_counter() - t0) * 1000.0
    cold_phys = src.physical_reads

    # Warm same
    t0 = time.perf_counter()
    _ = src.read_inline(0)
    warm_ms = (time.perf_counter() - t0) * 1000.0
    warm_phys = src.physical_reads

    # Adjacent scrub
    latencies = []
    for i in range(min(20, meta.n_inlines)):
        t0 = time.perf_counter()
        _ = src.read_inline(i)
        latencies.append((time.perf_counter() - t0) * 1000.0)
    latencies_sorted = sorted(latencies)
    p50 = latencies_sorted[len(latencies_sorted) // 2]
    p95 = latencies_sorted[int(len(latencies_sorted) * 0.95)]

    # Preview LOD0
    t0 = time.perf_counter()
    vol, _w = src.read_preview(max_dim=128, max_budget=128**3)
    preview_ms = (time.perf_counter() - t0) * 1000.0

    # Naive full-res upper bound estimate (would be full materialisation)
    naive_voxels = meta.n_inlines * meta.n_crosslines * meta.n_samples
    preview_voxels = int(np.prod(vol.shape)) if vol is not None else 0

    stats = src._cache.stats()
    src.close()
    return {
        "path": str(path),
        "shape": list(meta.shape),
        "metadata_ms": metadata_ms,
        "cold_slice_ms": cold_ms,
        "warm_slice_ms": warm_ms,
        "cold_physical_reads": cold_phys,
        "warm_physical_reads_delta": warm_phys - cold_phys,
        "scrub_p50_ms": p50,
        "scrub_p95_ms": p95,
        "preview_ms": preview_ms,
        "preview_shape": list(vol.shape) if vol is not None else None,
        "naive_full_voxels": naive_voxels,
        "preview_voxels": preview_voxels,
        "voxel_ratio": (preview_voxels / naive_voxels) if naive_voxels else None,
        "cache": stats,
        "warm_vs_cold_speedup": (cold_ms / warm_ms) if warm_ms > 0 else None,
    }


def main() -> None:
    rows = []
    if len(sys.argv) > 1:
        rows.append(bench_path(Path(sys.argv[1])))
    else:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            for label, shape in [
                ("small_128", (64, 64, 64)),
                ("medium_256", (128, 128, 64)),
            ]:
                p = _synthetic_segy(td_path / f"{label}.sgy", *shape)
                row = bench_path(p)
                row["label"] = label
                rows.append(row)
    print(json.dumps({"rows": rows}, indent=2))


if __name__ == "__main__":
    main()
