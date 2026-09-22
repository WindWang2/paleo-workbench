"""#1130: SEG-Y decreasing inline/xline numbering must survive transcode.

- constant negative steps are stored and map logical values to indices;
- nonlinear (varying/zero-step) numbering fails closed with TranscodeError,
  never silently degrades to step=1.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

segyio = pytest.importorskip("segyio")
zarr = pytest.importorskip("zarr")

from geoviz_seismic import open_volume  # noqa: E402
from paleo_workbench.seismic_transcode import (  # noqa: E402
    TranscodeError,
    TranscodeParams,
    _axis_spec,
    transcode_segy_to_zarr,
)


def test_axis_spec_positive_step() -> None:
    assert _axis_spec(np.array([10, 12, 14]), "iline") == (10, 2)


def test_axis_spec_negative_step() -> None:
    assert _axis_spec(np.array([12, 10, 8]), "iline") == (12, -2)


def test_axis_spec_single_and_empty() -> None:
    assert _axis_spec(np.array([7]), "xline") == (7, 1)
    assert _axis_spec(np.array([]), "xline") == (1, 1)


def test_axis_spec_nonlinear_raises() -> None:
    with pytest.raises(TranscodeError):
        _axis_spec(np.array([10, 12, 15]), "iline")  # varying diffs
    with pytest.raises(TranscodeError):
        _axis_spec(np.array([10, 10, 10]), "iline")  # zero step


def _write_decreasing_segy(path: Path) -> np.ndarray:
    """3 inlines (12, 10, 8) x 2 xlines (100, 105); trace = il*1000+xl."""
    nil, nxl, nt = 3, 2, 4
    ilines = [12, 10, 8]
    xlines = [100, 105]
    cube = np.zeros((nil, nxl, nt), dtype=np.float32)
    spec = segyio.spec()
    spec.ilines = ilines
    spec.xlines = xlines
    spec.samples = list(range(nt))
    spec.format = 5
    with segyio.create(str(path), spec) as f:
        i = 0
        for a, il in enumerate(ilines):
            for b, xl in enumerate(xlines):
                f.header[i] = {
                    segyio.TraceField.INLINE_3D: il,
                    segyio.TraceField.CROSSLINE_3D: xl,
                }
                trace = np.full(nt, il * 1000 + xl, dtype=np.float32)
                f.trace[i] = trace
                cube[a, b] = trace
                i += 1
    return cube


def test_decreasing_lines_transcode_and_read_by_logical_value(tmp_path) -> None:
    segy = tmp_path / "dec.segy"
    cube = _write_decreasing_segy(segy)
    store = tmp_path / "store"
    transcode_segy_to_zarr(
        segy, store, params=TranscodeParams(chunk=(2, 2, 2), shard=(4, 4, 4), clevel=1)
    )
    attrs = json.loads((store / "zarr.json").read_text())["attributes"]
    assert attrs["iline"] == {"start": 12, "step": -2}
    assert attrs["xline"] == {"start": 100, "step": 5}

    vol = open_volume(store)
    assert vol.geometry.iline_step == -2
    np.testing.assert_array_equal(vol.read_inline(10), cube[1, :, :])
    np.testing.assert_array_equal(vol.read_inline(8), cube[2, :, :])
    np.testing.assert_array_equal(vol.read_crossline(105), cube[:, 1, :])
    np.testing.assert_array_equal(vol.read_trace(12, 100), cube[0, 0, :])
    with pytest.raises(IndexError):
        vol.read_inline(14)  # above the decreasing range
    with pytest.raises(IndexError):
        vol.read_inline(6)  # below the decreasing range
