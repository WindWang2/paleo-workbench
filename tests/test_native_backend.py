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


def test_is_accelerated_reflects_cpp_capability():
    for feature in ["seismic_3d", "well_log", "map_edit"]:
        assert is_accelerated(feature) is native_backend.has_cpp(feature)
    assert is_accelerated("no_such_feature") is False


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
    """install_all_hooks() twice must wire the geoviz provider hooks and stay clean."""
    try:
        from geoviz import (
            get_downsample_provider,
            get_isosurface_extractor,
            get_las_parser_provider,
            set_downsample_provider,
            set_isosurface_extractor,
            set_las_parser_provider,
        )
    except ImportError:
        pytest.skip("geoviz not importable in this environment")

    from paleo_workbench.native_backend import _cpp_las_parser_provider, _cpp_minmax_provider

    prev = (
        get_downsample_provider(),
        get_isosurface_extractor(),
        get_las_parser_provider(),
    )
    try:
        install_all_hooks()
        install_all_hooks()
        assert get_downsample_provider() is _cpp_minmax_provider
        assert get_las_parser_provider() is _cpp_las_parser_provider
        assert get_isosurface_extractor() is not None
    finally:
        set_downsample_provider(prev[0])
        set_isosurface_extractor(prev[1])
        set_las_parser_provider(prev[2])
