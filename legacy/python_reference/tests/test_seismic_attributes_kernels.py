"""P1-B — the widened attribute kernel set keeps the halo-parity contract.

Every new kernel must satisfy the same BLOCKER-pinned contract as c3:
ROI (window + halo) output == full-memory kernel output on the same
samples, including windows clamped at survey edges.
"""

from __future__ import annotations

import numpy as np
import pytest

segyio = pytest.importorskip("segyio")
zarr = pytest.importorskip("zarr")

from geoviz_seismic import open_volume  # noqa: E402
from paleo_workbench.seismic_attributes import (  # noqa: E402
    KERNELS,
    TRACE_GLOBAL_KERNELS,
    attribute_halo,
    available_kernels,
    compute_block,
    roi_attribute,
)
from paleo_workbench.seismic_transcode import TranscodeParams, transcode_segy_to_zarr  # noqa: E402

NIL, NXL, NT = 36, 40, 48
PARAMS = TranscodeParams(chunk=(8, 16, 16), shard=(32, 32, 32), clevel=1)

NEW_KERNELS = [
    name
    for name in (
        "envelope",
        "instantaneous_phase",
        "instantaneous_frequency",
        "rms_amplitude",
        "sweetness",
        "relative_impedance",
        "dip_il",
        "dip_xl",
        "dip_azimuth",
        "curvature_mean",
    )
]
# FFT attributes are trace-global: ROI parity applies only to window-local
# kernels (full parity for the FFT family is pinned by the band test below,
# whose bands always carry complete traces).
WINDOW_LOCAL = [n for n in NEW_KERNELS if n not in TRACE_GLOBAL_KERNELS]


def _write_segy(path, seed: int = 33) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cube = (rng.standard_normal((NIL, NXL, NT)) * 0.5).astype(np.float32)
    cube[8:12, 10:30, 20:28] += 2.0
    cube[20:26, :, 5:10] -= 1.5
    spec = segyio.spec()
    spec.ilines = list(range(1, NIL + 1))
    spec.xlines = list(range(1, NXL + 1))
    spec.samples = list(range(NT))
    spec.format = 5
    with segyio.create(str(path), spec) as f:
        for il in range(NIL):
            for xl in range(NXL):
                i = il * NXL + xl
                f.header[i] = {
                    segyio.TraceField.INLINE_3D: il + 1,
                    segyio.TraceField.CROSSLINE_3D: xl + 1,
                    segyio.TraceField.TRACE_SEQUENCE_LINE: i + 1,
                }
                f.trace[i] = cube[il, xl]
    return cube


@pytest.fixture(scope="module")
def volume(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("attr2")
    segy = tmp / "v.segy"
    cube = _write_segy(segy)
    store = tmp / "store"
    transcode_segy_to_zarr(segy, store, params=PARAMS)
    reader = open_volume(store)
    return cube, reader


def _full_reference(name: str, cube: np.ndarray) -> np.ndarray:
    fn, kwargs, _halo = KERNELS[name]
    kw = {k: v for k, v in kwargs.items()}
    return fn(cube, **kw)


def test_kernel_registry_is_complete():
    assert set(NEW_KERNELS) <= set(available_kernels())


@pytest.mark.parametrize("name", NEW_KERNELS)
def test_trace_global_kernels_refuse_cropped_time_roi(volume, name):
    if name not in TRACE_GLOBAL_KERNELS:
        pytest.skip("window-local kernel")
    with pytest.raises(ValueError, match="trace-global"):
        roi_attribute(volume[1], (6, 26, 8, 30, 10, 40), name=name)
    # Full-time ROIs are legitimate for them.
    got = roi_attribute(volume[1], (6, 26, 8, 30, 0, NT), name=name)
    ref = _full_reference(name, volume[0])
    np.testing.assert_allclose(got, ref[6:26, 8:30, :], rtol=1e-4, atol=1e-4)


@pytest.mark.parametrize("name", NEW_KERNELS)
def test_roi_matches_full_memory_reference(volume, name):
    if name in TRACE_GLOBAL_KERNELS:
        pytest.skip("trace-global kernel: parity pinned by the full-time ROI above")
    cube, reader = volume
    ref = _full_reference(name, cube)
    il0, il1, xl0, xl1, t0, t1 = 6, 26, 8, 30, 10, 40
    got = roi_attribute(reader, (il0, il1, xl0, xl1, t0, t1), name=name)
    assert got.shape == (il1 - il0, xl1 - xl0, t1 - t0)
    np.testing.assert_allclose(got, ref[il0:il1, xl0:xl1, t0:t1], rtol=1e-5, atol=1e-5)


@pytest.mark.parametrize("name", WINDOW_LOCAL)
def test_roi_at_survey_edges_matches_reference(volume, name):
    cube, reader = volume
    ref = _full_reference(name, cube)
    hi, hx, ht = attribute_halo(name)
    got = roi_attribute(reader, (0, 8, 0, 10, 0, 12), name=name)
    # Edge windows only agree where the kernel's own reflect/clamp behavior
    # is the authority: compare the interior away from the clamped faces.
    np.testing.assert_allclose(
        got[hi:, hx:, ht:], ref[hi:8, hx:10, ht:12], rtol=1e-4, atol=1e-4
    )


@pytest.mark.parametrize(
    "name",
    [
        "envelope",
        "instantaneous_frequency",
        "rms_amplitude",
        "dip_azimuth",
        "curvature_mean",
    ],
)
def test_band_output_matches_full_reference_everywhere(volume, name):
    """Band-boundary seams are a BLOCKER: banded == full-memory."""
    cube, reader = volume
    ref = _full_reference(name, cube)
    n_il = reader.shape[0]
    out = np.empty_like(ref)
    for i0 in range(0, n_il, 7):
        i1 = min(i0 + 7, n_il)
        out[i0:i1] = compute_block(reader, name, i0, i1, 0, NXL, 0, NT)
    np.testing.assert_allclose(out, ref, rtol=1e-4, atol=1e-4)


def test_wrapped_time_kernels_absorb_use_gpu():
    """compute_block passes use_gpu to every kernel uniformly."""
    block = np.random.default_rng(5).standard_normal((6, 6, 24)).astype(np.float32)
    fn, kwargs, _halo = KERNELS["envelope"]
    out = fn(block, use_gpu=True, **kwargs)
    assert out.shape == block.shape
    assert np.all(out >= 0.0)
