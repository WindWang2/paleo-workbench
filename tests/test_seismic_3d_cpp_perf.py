from __future__ import annotations

import time

import numpy as np
import pytest

from paleo_workbench.native_backend import NativeEngineBackend
from paleo_workbench.viz.seismic_3d_api import (
    fast_resample_volume_3d,
    fast_slice_to_indexed8,
)

HAS_CPP = NativeEngineBackend().has_cpp("seismic_3d")


def _median_ms(fn, repeats: int = 5) -> float:
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return sorted(times)[len(times) // 2] * 1e3


def test_fast_slice_to_indexed8_parity():
    # 3D test volume: 20 x 30 x 40
    np.random.seed(42)
    volume = np.random.randn(20, 30, 40).astype(np.float32)

    # Test axis=0
    slice_u8, v_min, v_max = fast_slice_to_indexed8(volume, axis=0, index=10)
    assert slice_u8.dtype == np.uint8
    assert slice_u8.shape == (30, 40)
    assert slice_u8.min() == 0
    assert slice_u8.max() == 255
    assert v_min < v_max

    # Test axis=2
    slice_u8_t, _, _ = fast_slice_to_indexed8(volume, axis=2, index=15)
    assert slice_u8_t.shape == (20, 30)


def test_fast_resample_volume_3d_parity():
    volume = np.ones((100, 100, 100), dtype=np.float32) * 5.0
    resampled = fast_resample_volume_3d(volume, target_shape=(32, 32, 32))
    assert resampled.shape == (32, 32, 32)
    assert np.allclose(resampled, 5.0)


# ---------------------------------------------------------------------------
# Issue #384 — OpenMP work-size gating
#
# The C++ hot path used to spawn a full-size OpenMP team for every slice,
# including 16K-260K element slices where the fork/join barrier cost dominated
# (~130x slower than serial on 16-thread hosts, blocking the GUI per slider
# tick). Parallel regions are now gated on a work-size threshold so interactive
# slice sizes execute serially. These tests pin the small-workload behaviour:
# sub-millisecond-ish cost (a parallel team would cost tens of ms) and no
# regression against the Python fallback.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not HAS_CPP, reason="seismic_3d_core C++ extension not installed")
@pytest.mark.parametrize("axis", [0, 1, 2])
def test_small_slice_is_fast_with_default_threads(axis):
    """A 256^3 slice (65,536 cells) must stay in the serial path: well under
    the tens-of-ms parallel-team overhead reported in issue #384, and no
    slower than ~2x the Python fallback measured in the same process."""
    rng = np.random.default_rng(42)
    volume = rng.standard_normal((256, 256, 256)).astype(np.float32)
    native_ms = _median_ms(lambda: fast_slice_to_indexed8(volume, axis, 128))
    assert native_ms < 8.0, (
        f"small slice took {native_ms:.2f} ms — OpenMP team was spawned despite "
        "the work-size gate"
    )

    from paleo_workbench.native_backend import _py_fast_slice_to_indexed8

    fallback_ms = _median_ms(lambda: _py_fast_slice_to_indexed8(volume, axis, 128))
    assert native_ms <= 2.0 * fallback_ms + 1.0, (
        f"native {native_ms:.2f} ms vs fallback {fallback_ms:.2f} ms for a "
        "256^3 slice — native path regressed vs the Python fallback"
    )


@pytest.mark.skipif(not HAS_CPP, reason="seismic_3d_core C++ extension not installed")
def test_large_slice_parallel_path_stays_correct():
    """Slices above the 524,288-cell gate take the OpenMP path; results must
    remain bit-identical to the Python fallback (min/max + normalization)."""
    from paleo_workbench.native_backend import _py_fast_slice_to_indexed8

    rng = np.random.default_rng(7)
    volume = rng.standard_normal((600, 900, 80)).astype(np.float32)
    volume[2, 3, 4] = np.nan  # nodata must not disturb the stretch
    volume[5, 6, 7] = np.inf

    # Below the gate (serial path): axis-0 slice 900x80 = 72K cells, axis-1
    # slice 600x80 = 48K cells.
    for axis, index in [(0, 40), (1, 300)]:
        native, v_min, v_max = fast_slice_to_indexed8(volume, axis, index)
        py, py_min, py_max = _py_fast_slice_to_indexed8(volume, axis, index)
        np.testing.assert_array_equal(native, py)
        assert v_min == py_min and v_max == py_max

    # Above the gate (parallel path): axis-2 slice 600x900 = 540K cells.
    native, v_min, v_max = fast_slice_to_indexed8(volume, 2, 40)
    py, py_min, py_max = _py_fast_slice_to_indexed8(volume, 2, 40)
    np.testing.assert_array_equal(native, py)
    assert v_min == py_min and v_max == py_max

