"""Seismic 3D consistency/performance benchmark (LOD ladder, slices, fence).

Deterministic synthetic SEGY; measures the joint-3D hot paths so regressions
in load latency, memory, or slice/fence interaction costs are reproducible.

Usage (mirrors run_env.sh environment)::

    python benchmarks/seismic_3d_consistency_benchmark.py [--big]
"""

from __future__ import annotations

import argparse
import os
import resource
import statistics
import sys
import tempfile
import time

import numpy as np


def rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def ms(fn, repeats=3) -> float:
    vals = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        vals.append((time.perf_counter() - t0) * 1e3)
    return statistics.median(vals)


def make_segy(path, ni, nx, ns, dt_ms=4.0):
    import segyio

    spec = segyio.spec()
    spec.format = 1
    spec.samples = np.arange(ns, dtype=np.float64) * dt_ms
    spec.sorting = segyio.TraceSortingFormat.INLINE_SORTING
    spec.ilines = np.arange(1, ni + 1)
    spec.xlines = np.arange(1, nx + 1)
    rng = np.random.default_rng(7)
    t = np.linspace(0, 4 * np.pi, ns, dtype=np.float32)
    with segyio.create(path, spec) as f:
        for i, il in enumerate(spec.ilines):
            base = np.sin(t + 0.05 * i) + 0.4 * np.sin(2.3 * t - 0.02 * i)
            for j, xl in enumerate(spec.xlines):
                tr = i * nx + j
                f.header[tr][segyio.TraceField.INLINE_3D] = int(il)
                f.header[tr][segyio.TraceField.CROSSLINE_3D] = int(xl)
                f.trace[tr] = base + 0.12 * rng.standard_normal(ns).astype(np.float32)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--big", action="store_true", help="256x256x512 cube")
    args = parser.parse_args()

    ni, nx, ns = (256, 256, 512) if args.big else (101, 103, 205)
    segy = make_segy(
        os.path.join(tempfile.mkdtemp(prefix="seisbench-"), "cube.sgy"), ni, nx, ns
    )
    print(f"cube {ni}x{nx}x{ns} · file {os.path.getsize(segy)/1e6:.1f} MB · RSS {rss_mb():.0f} MB")

    from paleo_workbench.viz.seismic_volume_cache import SeismicVolumeCache
    from paleo_workbench.viz.seismic_volume_source import SeismicVolumeSource
    from paleo_workbench.viz.source_backed_volume_access import (
        SourceBackedVolumeAccess,
    )

    cache = SeismicVolumeCache()
    src = SeismicVolumeSource(segy, cache=cache)
    meta = src.metadata()

    print(f"metadata_ms {meta.metadata_ms:.1f} shape {meta.shape}")

    # --- LOD ladder ---------------------------------------------------
    for level in (0, 1, 2):
        t0 = time.perf_counter()
        vol, warning = src.read_lod_volume(level=level)
        dt = (time.perf_counter() - t0) * 1e3
        shape = tuple(int(x) for x in vol.shape) if vol is not None else None
        print(
            f"L{level}_load_ms {dt:.1f} shape {shape} "
            f"voxels {int(np.prod(shape)) if shape else 0} RSS {rss_mb():.0f} MB"
        )

    # --- orthogonal slices (source-backed, native resolution) ---------
    access = SourceBackedVolumeAccess(src)
    il_mid, xl_mid, t_mid = (
        meta.n_inlines // 2,
        meta.n_crosslines // 2,
        meta.n_samples // 2,
    )
    print(f"slice_inline_cold_ms {ms(lambda: src.read_inline(il_mid)):.2f}")
    print(f"slice_inline_warm_ms {ms(lambda: src.read_inline(il_mid)):.2f}")
    print(f"slice_crossline_cold_ms {ms(lambda: src.read_crossline(xl_mid)):.2f}")
    print(f"slice_timeslice_cold_ms {ms(lambda: src.read_timeslice(t_mid)):.2f}")
    if hasattr(src, "read_trace"):
        print(f"read_trace_ms {ms(lambda: src.read_trace(il_mid, xl_mid)):.2f}")

    # --- fence extraction: before display (source path) vs after ------
    try:
        from geoviz_well_seismic_3d import FenceSection, WellSeismicScene

        scene = WellSeismicScene()
        corners = (
            (1.0, 1.0, 0.0, 0.0),
            (1.0, float(nx), 50.0 * (nx - 1), 0.0),
            (float(ni), float(nx), 50.0 * (nx - 1), 50.0 * (ni - 1)),
        )
        scene.set_survey_from_corners(
            *corners, n_samples=meta.n_samples, dt_ms=meta.sample_interval_ms,
            t0_ms=meta.t0_ms,
        )
        scene.set_volume_access(access)
        fence = FenceSection(
            name="bench",
            vertices_xy=np.array(
                [[0.0, 0.0], [50.0 * (nx - 1), 50.0 * (ni - 1)]], dtype=np.float64
            ),
        )
        scene.add_fence(fence)
        t0 = time.perf_counter()
        ext = scene.extract_active_fence(n_along=128)
        print(
            f"fence_extract_source_ms {(time.perf_counter()-t0)*1e3:.1f} "
            f"axis[{ext.sample_axis[0]:.1f}..{ext.sample_axis[-1]:.1f}]"
        )
        vol0, _ = src.read_lod_volume(level=0)
        try:
            from paleo_workbench.viz.seismic_volume_source import preview_strides

            strides = preview_strides(
                meta.n_inlines, meta.n_crosslines, meta.n_samples
            )
        except Exception:
            strides = (1, 1, 1)
        try:
            access.set_display_data(vol0, lod_level=0, strides=strides)
        except TypeError:
            access.set_display_data(vol0, lod_level=0)
        scene.set_volume_access(access)
        t0 = time.perf_counter()
        ext2 = scene.extract_active_fence(n_along=128)
        print(
            f"fence_extract_display_ms {(time.perf_counter()-t0)*1e3:.1f} "
            f"same_amplitude={np.array_equal(ext.amplitude, ext2.amplitude)}"
        )
    except Exception as exc:  # engine optional in this bench
        print(f"fence path unavailable: {exc}")

    stats = cache.stats()
    print(
        f"cache entries={stats.get('entries')} bytes={stats.get('bytes', 0)/1e6:.1f}MB "
        f"hits={stats.get('hits')} misses={stats.get('misses')}"
    )
    print(f"final RSS {rss_mb():.0f} MB")
    src.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
