from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from paleo_workbench.viz import well_log_api
from paleo_workbench.viz.well_log_api import (
    HAS_CPP_WELL_LOG,
    fast_las_parse_data,
    minmax_downsample,
)


from paleo_workbench.native_backend import disabled_acceleration

# These tests assert C++ well_log_core behaviour; CI only builds map_edit_core,
# so skip the whole module when the well_log extension is absent.
pytestmark = pytest.mark.skipif(
    not HAS_CPP_WELL_LOG,
    reason="well_log_core C++ extension not built in this environment",
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

    # Force Python fallback path via disabled_acceleration seam
    with disabled_acceleration():
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

    # Force Python fallback path via disabled_acceleration seam
    with disabled_acceleration():
        h_py, d_py = fast_las_parse_data(content)

    assert h_cpp == h_py
    np.testing.assert_array_equal(np.isnan(d_cpp), np.isnan(d_py))
    np.testing.assert_allclose(d_cpp[~np.isnan(d_cpp)], d_py[~np.isnan(d_py)], rtol=1e-5)


def test_c4_minmax_downsample_mismatched_shape_or_dim_raises():
    depth = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    val_short = np.array([1.0, 2.0], dtype=np.float32)
    val_2d = np.array([[1.0, 2.0, 3.0]], dtype=np.float32)

    for v in [val_short, val_2d]:
        with pytest.raises(ValueError):
            minmax_downsample(depth, v, 10)

        with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
            with pytest.raises(ValueError):
                minmax_downsample(depth, v, 10)


@pytest.mark.parametrize("target_px", [0, -5])
def test_i5_minmax_downsample_negative_target_pixels_raises(target_px):
    depth = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    val = np.array([1.0, 2.0, 3.0], dtype=np.float32)

    with pytest.raises(ValueError):
        minmax_downsample(depth, val, target_px)

    with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
        with pytest.raises(ValueError):
            minmax_downsample(depth, val, target_px)


def test_m7_minmax_downsample_nan_inf_policy():
    depth = np.linspace(1.0, 10.0, 10, dtype=np.float32)
    values = np.array([np.nan, 2.0, np.nan, 8.0, np.inf, -np.inf, np.nan, np.nan, np.nan, np.nan], dtype=np.float32)

    d_cpp, v_cpp = minmax_downsample(depth, values, target_pixels=2)
    with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
        d_py, v_py = minmax_downsample(depth, values, target_pixels=2)

    np.testing.assert_array_equal(d_cpp, d_py)
    np.testing.assert_array_equal(np.isnan(v_cpp), np.isnan(v_py))


def test_m9_fast_las_parse_inf_converted_to_nan():
    content = """~A DEPT GR
100.0 inf
100.1 -infinity
100.2 50.0
"""
    h_cpp, d_cpp = fast_las_parse_data(content)
    with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
        h_py, d_py = fast_las_parse_data(content)

    assert h_cpp == ("DEPT", "GR")
    assert h_py == ("DEPT", "GR")
    assert np.isnan(d_cpp[0, 1]) and np.isnan(d_cpp[1, 1])
    assert np.isnan(d_py[0, 1]) and np.isnan(d_py[1, 1])
    assert d_cpp[2, 1] == 50.0 and d_py[2, 1] == 50.0


def test_i4_las_parse_null_value_strict_masking():
    content = """~A DEPT GR
100.0 -999.0
100.1 -999.25
100.2 -1000.0
"""
    # Default null_value = -999.0: only -999.0 is masked as NaN
    _, d_cpp = fast_las_parse_data(content, null_value=-999.0)
    with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
        _, d_py = fast_las_parse_data(content, null_value=-999.0)

    assert np.isnan(d_cpp[0, 1]) and np.isnan(d_py[0, 1])
    assert d_cpp[1, 1] == -999.25 and d_py[1, 1] == -999.25
    assert d_cpp[2, 1] == -1000.0 and d_py[2, 1] == -1000.0

    # Custom null_value = -999.25: only -999.25 is masked as NaN
    _, d_cpp2 = fast_las_parse_data(content, null_value=-999.25)
    with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
        _, d_py2 = fast_las_parse_data(content, null_value=-999.25)

    assert d_cpp2[0, 1] == -999.0 and d_py2[0, 1] == -999.0
    assert np.isnan(d_cpp2[1, 1]) and np.isnan(d_py2[1, 1])


def test_m8_las_parse_row_truncation_warning():
    content = """~A DEPT GR
100.0 50.0 99.0 12.0
100.1 60.0
"""
    with pytest.warns(UserWarning, match="more columns than the 2 declared header"):
        h_cpp, d_cpp = fast_las_parse_data(content)

    with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
        with pytest.warns(UserWarning, match="more columns than the 2 declared header"):
            h_py, d_py = fast_las_parse_data(content)

    assert d_cpp.shape == (2, 2)
    assert d_py.shape == (2, 2)




def test_433_a_log_data_parity_both_paths():
    """~A LOG DATA must not truncate columns; ~CURVE mnemonics are authoritative."""
    content = """~CURVE INFORMATION
 DEPT  .M                   : DEPTH
 GR    .API                 : GAMMA RAY
 RHOB  .G/CC                : BULK DENSITY
~A LOG DATA
 2000.00   45.2   2.35
 2001.00   52.1   2.38
 2002.00   61.8   2.41
"""
    h_cpp, d_cpp = fast_las_parse_data(content)
    with disabled_acceleration():
        h_py, d_py = fast_las_parse_data(content)

    assert h_cpp == ("DEPT", "GR", "RHOB")
    assert h_py == ("DEPT", "GR", "RHOB")
    assert d_cpp.shape == (3, 3)
    assert d_py.shape == (3, 3)
    assert d_cpp[1, 2] == 2.38
    assert d_py[1, 2] == 2.38
