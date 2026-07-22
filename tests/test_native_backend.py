"""Tests for NativeEngineBackend deep module interface and seam toggling."""
from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.native_backend import (
    NativeEngineBackend,
    disabled_acceleration,
    install_all_hooks,
    is_accelerated,
    native_backend,
)


def test_native_backend_singleton_instance():
    assert isinstance(native_backend, NativeEngineBackend)


def test_is_accelerated_returns_bool():
    for feature in ["seismic_3d", "well_log", "map_edit"]:
        val = is_accelerated(feature)
        assert isinstance(val, bool)


def test_disabled_acceleration_context_manager():
    # Inside disabled_acceleration block, is_accelerated returns False
    with disabled_acceleration():
        assert is_accelerated("seismic_3d") is False
        assert is_accelerated("well_log") is False
        assert is_accelerated("map_edit") is False

    # Outside block, returns original state
    assert is_accelerated("seismic_3d") == native_backend.has_cpp("seismic_3d")


def test_dispatch_fast_slice_extract_parity():
    vol = np.arange(8 * 12 * 16, dtype=np.float32).reshape(8, 12, 16)

    # Accelerated or default path
    slice_accel = native_backend.dispatch("fast_slice_extract", vol, axis=0, index=2)

    # Disabled acceleration path
    with disabled_acceleration():
        slice_py = native_backend.dispatch("fast_slice_extract", vol, axis=0, index=2)

    np.testing.assert_array_equal(slice_accel, slice_py)


def test_dispatch_minmax_downsample_parity():
    depths = np.linspace(100.0, 500.0, 1000, dtype=np.float32)
    values = np.random.randn(1000).astype(np.float32)

    d_acc, v_acc = native_backend.dispatch("minmax_downsample", depths, values, 100)
    with disabled_acceleration():
        d_py, v_py = native_backend.dispatch("minmax_downsample", depths, values, 100)

    np.testing.assert_array_equal(d_acc, d_py)
    np.testing.assert_array_equal(v_acc, v_py)


def test_install_all_hooks_idempotent():
    # Must run cleanly without error
    install_all_hooks()
    install_all_hooks()
