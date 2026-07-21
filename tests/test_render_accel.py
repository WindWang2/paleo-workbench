"""Tests for C++ downsample injection into the geoviz engine (ndarray protocol)."""
from __future__ import annotations

import numpy as np

from geoviz_well_log.renderer.downsample import (
    get_downsample_provider,
    numpy_minmax_downsample,
    set_downsample_provider,
)

import paleo_workbench.viz.render_accel as render_accel
from paleo_workbench.viz.render_accel import install_geoviz_acceleration


def setup_function():
    set_downsample_provider(None)
    render_accel._installed_provider = None


def teardown_function():
    set_downsample_provider(None)
    render_accel._installed_provider = None


def test_install_replaces_provider():
    assert get_downsample_provider() is numpy_minmax_downsample
    install_geoviz_acceleration()
    assert get_downsample_provider() is not numpy_minmax_downsample


def test_install_is_idempotent():
    install_geoviz_acceleration()
    first = get_downsample_provider()
    install_geoviz_acceleration()
    assert get_downsample_provider() is first


def test_injected_provider_preserves_extrema_and_order():
    install_geoviz_acceleration()
    provider = get_downsample_provider()
    n = 5000
    depths = np.arange(n, dtype=np.float64) * 0.125
    rng = np.random.default_rng(42)
    values = rng.random(n) * 100
    out_d, out_v = provider(depths, values, 200)
    assert isinstance(out_d, np.ndarray) and isinstance(out_v, np.ndarray)
    assert len(out_d) == len(out_v)
    assert len(out_d) <= 2 * 200 + 4
    # Provider casts to float32 at the C++ boundary; extrema are selections
    # of the float32-cast inputs.
    values32 = values.astype(np.float32)
    assert out_v.max() == values32.max()
    assert out_v.min() == values32.min()
    assert np.all(np.diff(out_d) >= 0)


def test_injected_provider_passthrough_when_small():
    install_geoviz_acceleration()
    provider = get_downsample_provider()
    depths = np.array([1.0, 2.0])
    values = np.array([3.0, 4.0])
    out_d, out_v = provider(depths, values, 100)
    np.testing.assert_array_equal(out_d, depths)
    np.testing.assert_array_equal(out_v, values)
