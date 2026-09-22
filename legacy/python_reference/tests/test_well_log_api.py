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


# ---------------------------------------------------------------------------
# #433 — ~A trailing words are a title, not column headers; ~CURVE is the
# authoritative column/header source (CWLS LAS 2.0: "~A LOG DATA").
# ---------------------------------------------------------------------------

_CURVE_BLOCK = """~CURVE INFORMATION
 DEPT  .M                   : DEPTH
 GR    .API                 : GAMMA RAY
 RHOB  .G/CC                : BULK DENSITY
"""

_DATA_ROWS = """ 2000.00   45.2   2.35
 2001.00   52.1   2.38
 2002.00   61.8   2.41
"""


@pytest.mark.parametrize(
    "a_line",
    [
        "~A LOG DATA",   # CWLS title form: must NOT become column headers
        "~A DEPT GR DEN",  # true inline header form: same mnemonics as ~CURVE
        "~A",            # bare marker
        "~ASCII",        # attached suffix is part of the section name
    ],
)
def test_433_headers_come_from_curve_block(a_line):
    content = _CURVE_BLOCK + a_line + "\n" + _DATA_ROWS
    for force_python in (False, True):
        if force_python:
            from paleo_workbench.native_backend import disabled_acceleration

            with disabled_acceleration():
                headers, data = fast_las_parse_data(content)
        else:
            headers, data = fast_las_parse_data(content)
        assert headers == ("DEPT", "GR", "RHOB")
        assert data.shape == (3, 3)


def test_433_no_curve_block_keeps_inline_header_fallback():
    from paleo_workbench.native_backend import disabled_acceleration

    content = "~A DEPT GR DEN\n" + _DATA_ROWS
    with disabled_acceleration():
        headers, data = fast_las_parse_data(content)
    assert headers == ("DEPT", "GR", "DEN")
    assert data.shape == (3, 3)


def test_433_curve_block_always_wins_over_inline_words():
    """~A words that disagree with ~CURVE count must be ignored (2 != 3)."""
    from paleo_workbench.native_backend import disabled_acceleration

    content = _CURVE_BLOCK + "~A LOG DATA\n" + _DATA_ROWS
    with disabled_acceleration():
        headers, data = fast_las_parse_data(content)
    assert headers == ("DEPT", "GR", "RHOB")
    assert data.shape == (3, 3)
    assert data[1, 2] == 2.38  # RHOB column survives
