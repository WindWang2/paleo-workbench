from __future__ import annotations

import numpy as np
import pytest

from paleo_workbench.viz.well_log_api import (
    HAS_CPP_WELL_LOG,
    fast_las_parse_data,
    minmax_downsample,
)


def test_has_cpp_well_log_flag_is_bool():
    assert isinstance(HAS_CPP_WELL_LOG, bool)


def test_minmax_downsample_preserves_envelope_and_shape():
    np.random.seed(42)
    depth = np.linspace(1000, 2000, 10000, dtype=np.float32)
    values = np.sin(depth / 10.0).astype(np.float32) * 50.0 + np.random.randn(10000).astype(np.float32)

    target_pixels = 500
    d_out, v_out = minmax_downsample(depth, values, target_pixels)

    assert isinstance(d_out, np.ndarray)
    assert isinstance(v_out, np.ndarray)
    assert d_out.ndim == 1
    assert v_out.ndim == 1
    assert len(d_out) == len(v_out)
    assert len(d_out) <= target_pixels * 2
    # Extreme values should be preserved in envelope
    assert np.isclose(v_out.min(), values.min(), atol=1e-3)
    assert np.isclose(v_out.max(), values.max(), atol=1e-3)


def test_fast_las_parse_data_valid_ascii():
    content = """~Curve Information
DEPT.M : Depth
GR.API  : Gamma Ray
DEN.G/CC: Density
~A DEPT GR DEN
1000.00 45.2 2.35
1000.125 48.6 2.38
1000.250 52.1 NaN
"""
    headers, data = fast_las_parse_data(content)
    assert headers == ("DEPT", "GR", "DEN")
    assert isinstance(data, np.ndarray)
    assert data.shape == (3, 3)
    assert data[0, 0] == 1000.00
    assert np.isnan(data[2, 2])
