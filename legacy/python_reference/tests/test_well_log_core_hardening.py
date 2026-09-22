"""Regression tests for cpp-core-review findings in well_log_core.

Each test exercises a degenerate / adversarial input and asserts the C++
path and Python fallback behave identically. Findings reference
.superpowers/sdd/cpp-core-review.md §2.
"""
from __future__ import annotations

import warnings

import numpy as np
import pytest

from paleo_workbench.native_backend import disabled_acceleration
from paleo_workbench.viz.well_log_api import (
    HAS_CPP_WELL_LOG,
    fast_las_parse_data,
    minmax_downsample,
)

# Defer the hard C++ import so missing extensions skip via pytestmark below
# instead of crashing collection. ``well_log_core`` is only referenced inside
# test bodies guarded by ``HAS_CPP_WELL_LOG``.
try:
    import well_log_core  # noqa: F401
except ImportError:
    pass

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
        # Force the Python fallback via the native_backend seam. The old
        # patch.object(HAS_CPP_WELL_LOG, False) idiom was dead after the façade
        # migrated to native_backend.dispatch — it ran the C++ path twice.
        with disabled_acceleration():
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
    with disabled_acceleration():
        _h_py, d_py = fast_las_parse_data(content)
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
    with disabled_acceleration():
        _h_py, d_py = fast_las_parse_data(content)
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


# ---------------------------------------------------------------------------
# Issue #421 (NAT-8) — fast LAS native/fallback boundary parity
# ---------------------------------------------------------------------------

_LAS_BOUNDARY_CORPUS = {
    "no_inline_headers": "~Ascii\n1 2 3\n",
    "pure_A_no_mnemonics": "~A\n1 2\n",
    "long_row_no_headers": "~A\n1 2\n2 3 4 5\n",
    "hex_float_token": "~A\n0x1p3 1.0\n",
    "nbsp_between_numbers": "~A\n1.0\u00a02.5\n",
    "nbsp_leading_token": "~A\n\u00a01.0 2.0\n",
    "vt_ff_line_separators": "~A DEPT GR\n1.0 2.0\x0b3.0 4.0\x0c5.0 6.0",
    "vt_ff_inline": "~A DEPT GR\x0b1.0 2.0\x0c3.0 4.0\x0b5.0 6.0",
    "bytes_payload": b"~A DEPT GR\n1.0 2.0\n",
    "numeric_prefix_garbage": "~A\n123abc 1.5e 1..2 .5e2\n",
    "crlf_and_indent": "~A\n  1.0 2.0\r\n",
    "comment_lines": "~A DEPT GR\n# comment\n1.0 2.0\n",
    "inf_and_nan": "~A\n1.0 inf nan\n",
    "underflow_to_nan": "~A\n1e-999 1.0\n",
    "subnormal_kept": "~A\n5e-324 1.0\n",
    "overflow_to_nan": "~A\n1e309 1.0\n",
    "long_row_with_headers": "~A DEPT GR\n1.0 2.0 3.0 4.0\n",
    "empty_data_section": "~A DEPT GR\n",
    "no_data_at_all": "~V 1.0\n# nothing\n",
    "lowercase_marker": "~a DEPT\n1.0\n",
    "blank_data_lines": "~A\n\n1.0 2.0\n",
    "custom_null_value": "~A DEPT GR\n1.0 -999.0\n2.0 -999.25\n",
}


@pytest.mark.parametrize("name", sorted(_LAS_BOUNDARY_CORPUS))
def test_las_parse_boundary_parity(name):
    """Every boundary input must yield identical headers/array/warnings on the
    C++ and Python-fallback paths (dispatch-level, both acceleration states)."""
    content = _LAS_BOUNDARY_CORPUS[name]
    null_value = -999.25 if name == "custom_null_value" else -999.0

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            h_cpp, d_cpp = fast_las_parse_data(content, null_value=null_value)
            cpp = ("ok", h_cpp, d_cpp)
        except Exception as exc:  # noqa: BLE001
            cpp = ("err", type(exc))
        cpp_warns = sorted(str(w.message) for w in caught)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with disabled_acceleration():
            try:
                h_py, d_py = fast_las_parse_data(content, null_value=null_value)
                py = ("ok", h_py, d_py)
            except Exception as exc:  # noqa: BLE001
                py = ("err", type(exc))
            py_warns = sorted(str(w.message) for w in caught)

    assert cpp[0] == py[0], f"{name}: one path raised, the other did not"
    if cpp[0] == "err":
        assert cpp[1] is py[1], f"{name}: exception types differ"
        return
    assert cpp[1] == py[1], f"{name}: headers differ"
    np.testing.assert_array_equal(cpp[2], py[2])
    assert cpp_warns == py_warns, f"{name}: warnings differ"


def test_las_nbsp_frozen_single_column():
    """U+00A0 is token content (not a separator): the row is one column."""
    with disabled_acceleration():
        h, d = fast_las_parse_data("~A\n1.0\u00a02.5\n")
    assert h == ()
    assert d.shape == (1, 1)
    assert d[0, 0] == 1.0


def test_las_vt_ff_frozen_headers_and_rows():
    """VT/FF are whitespace, not line breaks: one data row, declared headers."""
    content = "~A DEPT GR\n1.0 2.0\x0b3.0 4.0\x0c5.0 6.0"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with disabled_acceleration():
            h, d = fast_las_parse_data(content)
    assert h == ("DEPT", "GR")
    assert d.shape == (1, 2)
    np.testing.assert_array_equal(d[0], [1.0, 2.0])
    assert any("truncated" in str(w.message) for w in caught)


def test_las_no_inline_headers_returns_empty_headers_on_both_paths():
    content = "~Ascii\n1 2 3\n"
    h_cpp, d_cpp = well_log_core.fast_las_parse_data(content)
    assert h_cpp == ()
    assert d_cpp.shape == (1, 3)
    with disabled_acceleration():
        h_py, d_py = fast_las_parse_data(content)
    assert h_py == ()
    assert d_py.shape == (1, 3)
    np.testing.assert_array_equal(d_cpp, d_py)


def test_las_bytes_payload_parses_on_both_paths():
    content = b"~A DEPT GR\n1.0 2.0\n"
    h_cpp, d_cpp = well_log_core.fast_las_parse_data(content)
    with disabled_acceleration():
        h_py, d_py = fast_las_parse_data(content)
    assert h_cpp == h_py == ("DEPT", "GR")
    np.testing.assert_array_equal(d_cpp, d_py)


def test_las_non_string_content_raises_type_error_on_both_paths():
    _both_raise(fast_las_parse_data, 123)


def test_minmax_downsample_huge_target_pixels_raises_on_both_paths():
    """target_pixels=2**30 must raise ValueError on both paths (parity fix)."""
    depth = np.arange(10, dtype=np.float32)
    values = np.arange(10, dtype=np.float32)
    _both_raise(minmax_downsample, depth, values, 2**30)
