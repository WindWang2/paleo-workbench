"""Tests for C++ downsample injection into the geoviz engine."""
from __future__ import annotations

import numpy as np

from geoviz_well_log.renderer.downsample import (
    get_downsample_provider,
    numpy_minmax_downsample,
    set_downsample_provider,
)

from paleo_workbench.viz.render_accel import install_geoviz_acceleration


def setup_function():
    set_downsample_provider(None)


def teardown_function():
    set_downsample_provider(None)


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
    depths = [float(i) * 0.125 for i in range(n)]
    rng = np.random.default_rng(42)
    values = (rng.random(n) * 100).tolist()
    out_d, out_v = provider(depths, values, 200)
    assert len(out_d) == len(out_v)
    assert len(out_d) <= 2 * 200 + 4
    assert max(out_v) == max(values)
    assert min(out_v) == min(values)
    assert all(b >= a for a, b in zip(out_d, out_d[1:]))


def test_injected_provider_passthrough_when_small():
    install_geoviz_acceleration()
    provider = get_downsample_provider()
    out_d, out_v = provider([1.0, 2.0], [3.0, 4.0], 100)
    assert list(out_d) == [1.0, 2.0]
    assert list(out_v) == [3.0, 4.0]
