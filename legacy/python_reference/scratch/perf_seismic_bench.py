"""Benchmark script for 3D seismic volume loading and Time slice slider dragging performance."""
from __future__ import annotations

import time
import numpy as np


def benchmark_time_slice_extraction(shape=(500, 500, 500)):
    vol = np.random.randn(*shape).astype(np.float32)

    # Measure Time slice extraction (axis 2)
    t0 = time.perf_counter()
    for t_idx in range(0, 100, 5):
        _slice = vol[:, :, t_idx].copy()
    t_extract = (time.perf_counter() - t0) / 20.0

    print(f"[BENCHMARK] 3D Time slice extraction ({shape}): {t_extract * 1000.0:.2f} ms per frame")
    return t_extract


if __name__ == "__main__":
    benchmark_time_slice_extraction()
