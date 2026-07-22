"""Regression tests for cpp-core-review findings in well_log_core.

Each test exercises a degenerate / adversarial input and asserts the C++
path and Python fallback behave identically. Findings reference
.superpowers/sdd/cpp-core-review.md §2.
"""
from __future__ import annotations

import warnings
from unittest.mock import patch

import numpy as np
import pytest

from paleo_workbench.viz import well_log_api
from paleo_workbench.viz.well_log_api import (
    HAS_CPP_WELL_LOG,
    fast_las_parse_data,
    minmax_downsample,
)
import well_log_core

pytestmark = pytest.mark.skipif(
    not HAS_CPP_WELL_LOG,
    reason="well_log_core C++ extension not installed",
)


def _both_paths(fn, *args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            cpp = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            cpp = exc
        with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
            try:
                py = fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                py = exc
    return cpp, py


def _both_raise(fn, *args, **kwargs) -> None:
    cpp, py = _both_paths(fn, *args, **kwargs)
    assert isinstance(cpp, Exception), f"C++ path did not raise (got {type(cpp)})"
    assert isinstance(py, Exception), f"Python path did not raise (got {type(py)})"


# ---------------------------------------------------------------------------
# C4 — no shape/length validation in minmax_downsample -> OOB read
# ---------------------------------------------------------------------------


def test_c4_mismatched_lengths_raise_on_both_paths():
    depth = np.arange(5, dtype=np.float32)
    values = np.arange(3, dtype=np.float32)
    _both_raise(minmax_downsample, depth, values, 2)


def test_c4_zero_dim_array_raises_on_both_paths():
    _both_raise(
        minmax_downsample,
        np.array(1.0, dtype=np.float32),
        np.array(1.0, dtype=np.float32),
        2,
    )


def test_c4_two_dim_array_raises_on_both_paths():
    _both_raise(
        minmax_downsample,
        np.zeros((2, 2), dtype=np.float32),
        np.zeros((2, 2), dtype=np.float32),
        2,
    )


# ---------------------------------------------------------------------------
# I5 — target_pixels <= 0 unvalidated (UB / silent full copy)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_target", [0, -1, -100])
def test_i5_nonpositive_target_pixels_raises_on_both_paths(bad_target):
    _both_raise(
        minmax_downsample,
        np.arange(10, dtype=np.float32),
        np.arange(10, dtype=np.float32),
        bad_target,
    )


# ---------------------------------------------------------------------------
# M7 — NaN in values poisons bucket min/max
# M9 — inf leaks into output
# ---------------------------------------------------------------------------


def test_m7_nan_values_do_not_poison_output_on_both_paths():
    depth = np.arange(10, dtype=np.float32)
    values = np.array([1, np.nan, 3, 2, np.nan, 5, 4, np.nan, 7, 6], dtype=np.float32)
    cpp, py = _both_paths(minmax_downsample, depth, values, 2)
    assert not isinstance(cpp, Exception)
    # NaN must not survive as a min or max in finite buckets.
    assert not np.isnan(cpp[1]).any(), "C++ path leaked NaN into output"
    assert not np.isnan(py[1]).any(), "Python path leaked NaN into output"
    # Parity between the two backends.
    np.testing.assert_array_equal(cpp[0], py[0])
    np.testing.assert_array_equal(cpp[1], py[1])


def test_m9_inf_treated_as_nan_in_las_parsing():
    content = "~A DEPT GR\n1.0 inf\n2.0 5.0\n"
    _h_cpp, d_cpp = well_log_core.fast_las_parse_data(content)
    assert np.isnan(d_cpp[0, 1]), "C++ LAS parser leaked inf"
    with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
        _h_py, d_py = well_log_api.fast_las_parse_data(content)
    assert np.isnan(d_py[0, 1]), "Python LAS fallback leaked inf"


# ---------------------------------------------------------------------------
# I4 — hard-coded <= -999.0 overrode the null_value contract
# ---------------------------------------------------------------------------


def test_i4_value_below_minus_999_is_kept_with_default_null():
    """A legitimate -999.25 is data, not null, when null_value defaults to -999.0."""
    content = "~A DEPT GR\n100.0 -999.25\n"
    _h_cpp, d_cpp = well_log_core.fast_las_parse_data(content)
    assert not np.isnan(d_cpp[0, 1])
    assert d_cpp[0, 1] == -999.25
    with patch.object(well_log_api, "HAS_CPP_WELL_LOG", False):
        _h_py, d_py = well_log_api.fast_las_parse_data(content)
    assert d_py[0, 1] == -999.25


def test_i4_default_null_value_still_masks():
    content = "~A DEPT GR\n100.0 -999.0\n"
    _h, d = well_log_core.fast_las_parse_data(content)
    assert np.isnan(d[0, 1])


def test_i4_custom_null_value_masks_exact_match_only():
    content = "~A DEPT GR\n1.0 -1000.0\n2.0 -999.0\n"
    _h, d = well_log_core.fast_las_parse_data(content, null_value=-1000.0)
    assert np.isnan(d[0, 1]), "custom null_value should mask -1000.0"
    assert d[1, 1] == -999.0, "-999.0 is data when null_value is -1000.0"


# ---------------------------------------------------------------------------
# M8 — rows longer than header count are silently truncated
# ---------------------------------------------------------------------------


def test_m8_long_row_emits_warning():
    content = "~A DEPT GR\n1.0 2.0 3.0 4.0\n5.0 6.0\n"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        well_log_core.fast_las_parse_data(content)
    assert any("truncated" in str(w.message) for w in caught), "expected truncation warning"
