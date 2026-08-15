"""Tests for the native scalar-grid rasteriser (`grid_render_core`) and its parity.

Three layers:
  1. Golden behaviour of the pure-Python parity fallback (byte values). Runs everywhere.
  2. SymmetricParityContract: when the C++ extension is built, its output must match the
     Python fallback byte-for-byte for gamma == 1.0 (no transcendental involved) and
     within ±1 index for gamma != 1.0.
  3. Facade + FactorGridResult integration.

The golden values are the same ones asserted by the C++ selftest
(`native/grid_render_core/src/standalone_test.cpp`), so the two implementations are
pinned to one contract.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from paleo_workbench.native_backend import (
    NativeEngineBackend,
    _py_render_grid_rgba,
    disabled_acceleration,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult
from paleo_workbench.viz.grid_render import render_grid_rgba

HAS_CPP = NativeEngineBackend().has_cpp("grid_render")


def _gray_lut(alpha: int = 255, size: int = 256) -> np.ndarray:
    lut = np.zeros((size, 4), dtype=np.uint8)
    vals = np.arange(size, dtype=np.uint8)
    lut[:, 0] = vals
    lut[:, 1] = vals
    lut[:, 2] = vals
    lut[:, 3] = alpha
    return lut


def _py(grid_z, lut, lo, hi, mask=None, gamma=1.0, opacity=255):
    gz = np.ascontiguousarray(grid_z, dtype=np.float32)
    return _py_render_grid_rgba(gz, mask, lut, lo, hi, gamma, opacity)


# --- golden behaviour (pure-Python fallback; identical contract to C++) -----------


def test_basic_ramp_normalisation():
    lut = _gray_lut()
    grid = np.array([[0.0, 0.25], [0.5, 1.0]], dtype=np.float32)
    out = _py(grid, lut, 0.0, 1.0)
    assert out[0, 0, 0] == 0 and out[0, 0, 3] == 255          # v=0 -> idx 0
    assert out[0, 1, 0] == 63                                 # 0.25 -> int(63.75)=63
    assert out[1, 0, 0] == 127                                # 0.5 -> int(127.5)=127
    assert out[1, 1, 0] == 255                                # 1.0 -> idx 255


def test_out_of_range_clamps_to_endpoints():
    lut = _gray_lut()
    grid = np.array([[2.0, -1.0]], dtype=np.float32)  # above hi, below lo
    out = _py(grid, lut, 0.0, 1.0)
    assert out[0, 0, 0] == 255   # v>hi -> top
    assert out[0, 1, 0] == 0     # v<lo -> bottom


def test_nodata_and_mask_are_transparent():
    lut = _gray_lut()
    grid = np.array([[float("nan"), 0.5]], dtype=np.float32)
    out = _py(grid, lut, 0.0, 1.0)
    assert out[0, 0, 3] == 0 and out[0, 0, 0] == 0           # NaN -> transparent
    assert out[0, 1, 3] == 255 and out[0, 1, 0] == 127       # valid renders

    mask = np.array([[1, 0]], dtype=np.uint8)
    out2 = _py(grid, lut, 0.0, 1.0, mask=mask)
    assert out2[0, 1, 3] == 0                                 # masked -> transparent


def test_opacity_alpha_multiply():
    lut = _gray_lut()
    grid = np.array([[1.0]], dtype=np.float32)
    out = _py(grid, lut, 0.0, 1.0, opacity=128)
    assert out[0, 0, 3] == 128                                # 255*128/255

    lut51 = _gray_lut(alpha=51)
    out2 = _py(grid, lut51, 0.0, 1.0, opacity=5)
    assert out2[0, 0, 3] == 1                                 # 51*5/255 = 1 (int div)


def test_gamma():
    lut = _gray_lut()
    grid = np.array([[0.5]], dtype=np.float32)
    assert _py(grid, lut, 0.0, 1.0, gamma=2.0)[0, 0, 0] == 63   # 0.5^2=0.25 -> 63
    assert _py(grid, lut, 0.0, 1.0, gamma=0.5)[0, 0, 0] == 180  # sqrt(0.5) -> 180
    assert _py(grid, lut, 0.0, 1.0, gamma=-1.0)[0, 0, 0] == 127  # <=0 -> 1.0


def test_degenerate_range_hi_eq_lo():
    lut = _gray_lut()
    grid = np.array([[5.0]], dtype=np.float32)
    out = _py(grid, lut, 5.0, 5.0)
    assert out[0, 0, 0] == 0 and out[0, 0, 3] == 255          # t=0, still opaque


# --- SymmetricParityContract: C++ vs Python --------------------------------------


def _cpp(grid_z, lut, lo, hi, mask=None, gamma=1.0, opacity=255):
    backend = NativeEngineBackend()
    assert backend.has_cpp("grid_render"), "C++ grid_render_core not built"
    gz = np.ascontiguousarray(grid_z, dtype=np.float32)
    mask_buf = None if mask is None else np.ascontiguousarray(mask, dtype=np.uint8)
    return backend.dispatch(
        "render_grid_rgba", gz, mask_buf, lut, lo, hi, gamma, opacity
    )


@pytest.mark.skipif(not HAS_CPP, reason="grid_render_core C++ extension not built")
def test_cpp_matches_python_gamma_one():
    rng = np.random.default_rng(42)
    lut = _gray_lut()
    grid = rng.random((40, 50)).astype(np.float32)
    grid[0, 0] = float("nan")
    grid[1, 1] = float("inf")
    mask = (rng.random((40, 50)) > 0.3).astype(np.uint8)
    cpp = _cpp(grid, lut, 0.0, 1.0, mask=mask, gamma=1.0, opacity=200)
    py = _py(grid, lut, 0.0, 1.0, mask=mask, gamma=1.0, opacity=200)
    # gamma == 1.0 is pure float arithmetic -> must be byte-identical.
    np.testing.assert_array_equal(cpp, py)


@pytest.mark.skipif(not HAS_CPP, reason="grid_render_core C++ extension not built")
def test_cpp_matches_python_gamma_within_tolerance():
    rng = np.random.default_rng(7)
    lut = _gray_lut()
    grid = rng.random((40, 50)).astype(np.float32)
    cpp = _cpp(grid, lut, 0.0, 1.0, gamma=2.2, opacity=255)
    py = _py(grid, lut, 0.0, 1.0, gamma=2.2, opacity=255)
    # gamma != 1.0 involves powf; allow at most ±1 index drift on RGB, identical alpha.
    diff = np.abs(cpp[:, :, :3].astype(np.int16) - py[:, :, :3].astype(np.int16))
    assert diff.max() <= 1
    np.testing.assert_array_equal(cpp[:, :, 3], py[:, :, 3])


# --- facade + FactorGridResult integration ---------------------------------------


def test_facade_renders_factor_grid_result():
    lut = _gray_lut()
    r = FactorGridResult.from_engine_dict(
        {"grid_x": [0.0, 1.0], "grid_y": [0.0, 1.0],
         "grid_z": [[0.0, 0.5], [float("nan"), 1.0]], "backend": "idw",
         "n_points": 3, "min": 0.0, "max": 1.0, "mean": 0.5, "r_squared": None},
        factor_name="porosity",
    )
    out = render_grid_rgba(r.grid_z, lut, lo=0.0, hi=1.0)
    assert out.shape == (2, 2, 4) and out.dtype == np.uint8
    assert out[0, 0, 0] == 0        # 0.0
    assert out[0, 1, 0] == 127      # 0.5
    assert out[1, 0, 3] == 0        # nodata transparent
    assert out[1, 1, 0] == 255      # 1.0


def test_facade_rgb_lut_gets_alpha_255():
    lut_rgb = np.zeros((4, 3), dtype=np.uint8)
    lut_rgb[3] = [255, 255, 255]
    grid = np.array([[1.0]], dtype=np.float32)
    out = render_grid_rgba(grid, lut_rgb, lo=0.0, hi=1.0)
    assert out[0, 0, 3] == 255  # RGB LUT -> opaque


# --- Issue #446: native/fallback boundary parity --------------------------


@pytest.mark.skipif(not HAS_CPP, reason="grid_render_core C++ extension not built")
@pytest.mark.parametrize(
    "grid, mask, lut, lo, hi, gamma, opacity",
    [
        # near-degenerate range: hi - lo = 1e-10 is positive in float64 but
        # collapses to 0.0f in float32 — the range must be honoured anyway
        (np.array([[0.0, 1.0]], dtype=np.float32), None, _gray_lut(), 0.0, 1e-10, 1.0, 255),
        # hi == lo degenerate range
        (np.array([[5.0]], dtype=np.float32), None, _gray_lut(), 5.0, 5.0, 1.0, 255),
        # float64 grid_z (forcecast to float32 on both paths)
        (np.array([[0.0, 1.0]], dtype=np.float64), None, _gray_lut(), 0.0, 1.0, 1.0, 255),
        # NaN/Inf nodata + gamma != 1
        (np.array([[np.nan, np.inf, 0.5]], dtype=np.float32), None, _gray_lut(), 0.0, 1.0, 2.2, 255),
        # mask with valid shape
        (np.ones((2, 3), dtype=np.float32), np.ones((2, 3), dtype=np.uint8), _gray_lut(), 0.0, 1.0, 1.0, 100),
        # negative lo with gamma
        (np.array([[-2.0, 2.0]], dtype=np.float32), None, _gray_lut(), -2.0, 2.0, 0.5, 255),
    ],
)
def test_grid_render_boundary_parity(grid, mask, lut, lo, hi, gamma, opacity):
    """Dtype, value and degenerate-range parity across both backends."""
    backend = NativeEngineBackend()
    cpp = backend.dispatch("render_grid_rgba", grid, mask, lut, lo, hi, gamma, opacity)
    with disabled_acceleration():
        py = backend.dispatch("render_grid_rgba", grid, mask, lut, lo, hi, gamma, opacity)
    np.testing.assert_array_equal(cpp, py)


@pytest.mark.skipif(not HAS_CPP, reason="grid_render_core C++ extension not built")
def test_grid_render_near_degenerate_range_uses_float64_judgement():
    """hi - lo = 1e-10 must NOT be judged as 'no range' (which flattened the
    whole grid to the ramp bottom on the native path only)."""
    lut = _gray_lut()
    grid = np.array([[0.0, 1.0]], dtype=np.float32)
    backend = NativeEngineBackend()
    cpp = backend.dispatch("render_grid_rgba", grid, None, lut, 0.0, 1e-10, 1.0, 255)
    with disabled_acceleration():
        py = backend.dispatch("render_grid_rgba", grid, None, lut, 0.0, 1e-10, 1.0, 255)
    np.testing.assert_array_equal(cpp, py)
    assert cpp[0, 0, 0] == 0    # v=0.0 -> ramp bottom
    assert cpp[0, 1, 0] == 255  # v=1.0 -> ramp top (not flattened to bottom)


@pytest.mark.skipif(not HAS_CPP, reason="grid_render_core C++ extension not built")
@pytest.mark.parametrize(
    "grid, mask, lut",
    [
        (np.zeros((2, 2), dtype=np.float32), None, np.zeros((0, 4), dtype=np.uint8)),
        (np.zeros((2, 2), dtype=np.float32), None, np.zeros((5, 3), dtype=np.uint8)),
        (np.zeros((2, 2), dtype=np.float32), None, np.zeros(4, dtype=np.uint8)),
        (np.zeros((2, 2), dtype=np.float32), np.ones((1, 2), dtype=np.uint8), _gray_lut()),
        (np.zeros((2, 4), dtype=np.float32), np.ones((4, 2), dtype=np.uint8), _gray_lut()),
        (np.zeros(4, dtype=np.float32), None, _gray_lut()),
        (np.zeros((2, 2, 2), dtype=np.float32), None, _gray_lut()),
        (np.zeros((2, 2), dtype=np.float32), np.zeros((2, 2, 2), dtype=np.uint8), _gray_lut()),
    ],
)
def test_grid_render_malformed_inputs_raise_on_both_paths(grid, mask, lut):
    """Malformed LUT/mask shapes raise ValueError on both backends instead of
    the fallback silently returning an all-zero raster or broadcasting."""
    backend = NativeEngineBackend()
    with pytest.raises(ValueError):
        backend.dispatch("render_grid_rgba", grid, mask, lut, 0.0, 1.0, 1.0, 255)
    with disabled_acceleration():
        with pytest.raises(ValueError):
            backend.dispatch("render_grid_rgba", grid, mask, lut, 0.0, 1.0, 1.0, 255)
