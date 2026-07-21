from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from paleo_workbench.viz import well_log_api
from paleo_workbench.viz.well_log_api import (
    HAS_CPP_WELL_LOG,
    fast_las_parse_data,
    generate_crossover_fill,
    minmax_downsample,
)


def test_well_log_cpp_extension_is_loaded():
    assert HAS_CPP_WELL_LOG is True


def test_minmax_downsample_parity_with_python():
    np.random.seed(99)
    depth = np.linspace(100.0, 500.0, 5000, dtype=np.float32)
    values = np.random.randn(5000).astype(np.float32)

    target_px = 200

    # C++ path
    d_cpp, v_cpp = minmax_downsample(depth, values, target_px)

    # Force Python fallback path
    with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
        d_py, v_py = minmax_downsample(depth, values, target_px)

    np.testing.assert_array_equal(d_cpp, d_py)
    np.testing.assert_array_equal(v_cpp, v_py)


def test_fast_las_parse_data_parity_with_python():
    content = """~A DEPT GR DEN
100.0 45.0 2.2
100.1 48.0 2.3
100.2 -999.25 2.4
"""
    # C++ path
    h_cpp, d_cpp = fast_las_parse_data(content)

    # Force Python fallback path
    with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
        h_py, d_py = fast_las_parse_data(content)

    assert h_cpp == h_py
    np.testing.assert_array_equal(np.isnan(d_cpp), np.isnan(d_py))
    np.testing.assert_allclose(d_cpp[~np.isnan(d_cpp)], d_py[~np.isnan(d_py)], rtol=1e-5)


def test_generate_crossover_fill_parity_with_python():
    depth = np.array([10.0, 20.0, 30.0], dtype=np.float32)
    ca = np.array([1.0, 5.0, 2.0], dtype=np.float32)
    cb = np.array([2.0, 3.0, 2.0], dtype=np.float32)

    # C++ path
    pa_cpp, pb_cpp = generate_crossover_fill(depth, ca, cb)

    # Force Python fallback path
    with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
        pa_py, pb_py = generate_crossover_fill(depth, ca, cb)

    np.testing.assert_array_equal(pa_cpp, pa_py)
    np.testing.assert_array_equal(pb_cpp, pb_py)
