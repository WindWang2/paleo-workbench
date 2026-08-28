"""Unified volume access (#1080): open_volume + ChunkedVolumeReader/SegyVolumeReader.

Contracts pinned here:
- factory dispatch (zarr dir vs .segy) with no format knowledge leaking up;
- logical inline/crossline VALUES at every LOD level (caller never passes a
  downsampled index), including non-unit grid steps;
- read_voxel_window == one batched store slice (parity with direct zarr);
- read_arbitrary_line == one bounding-box read + memory interpolation
  (bitwise parity with a per-point reference over the full in-memory cube);
- the SEG-Y backend satisfies the same contract (browse-during-transcode).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pytest

segyio = pytest.importorskip("segyio")
zarr = pytest.importorskip("zarr")

from geoviz_seismic import (  # noqa: E402
    ChunkedVolumeReader,
    SegyVolumeReader,
    VolumeGeometry,
    open_volume,
)
from paleo_workbench.seismic_transcode import (  # noqa: E402
    TranscodeParams,
    transcode_segy_to_zarr,
)

# Irregular sizes on purpose (odd tails per axis) and NON-unit grid steps:
# ilines 10,12,...  xlines 100,105,...
NIL, NXL, NT = 41, 47, 65
IL_START, IL_STEP = 10, 2
XL_START, XL_STEP = 100, 5

PARAMS = TranscodeParams(chunk=(8, 16, 16), shard=(16, 32, 32), clevel=1)


def _write_segy(path: Path, seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cube = (rng.standard_normal((NIL, NXL, NT)) * 0.5).astype(np.float32)
    spec = segyio.spec()
    spec.ilines = list(range(IL_START, IL_START + NIL * IL_STEP, IL_STEP))
    spec.xlines = list(range(XL_START, XL_START + NXL * XL_STEP, XL_STEP))
    spec.samples = list(range(NT))
    spec.format = 5
    with segyio.create(str(path), spec) as f:
        for il in range(NIL):
            for xl in range(NXL):
                i = il * NXL + xl
                f.header[i] = {
                    segyio.TraceField.INLINE_3D: IL_START + il * IL_STEP,
                    segyio.TraceField.CROSSLINE_3D: XL_START + xl * XL_STEP,
                    segyio.TraceField.TRACE_SEQUENCE_LINE: i + 1,
                }
                f.trace[i] = cube[il, xl]
    return cube


@pytest.fixture(scope="module")
def volume(tmp_path_factory):
    """(cube, segy_path, zarr_path) — transcode once for the whole module."""
    tmp = tmp_path_factory.mktemp("vol")
    segy = tmp / "small.segy"
    cube = _write_segy(segy)
    store = tmp / "store"
    transcode_segy_to_zarr(segy, store, params=PARAMS)
    return cube, segy, store


# ------------------------------------------------------------------ factory


def test_open_volume_dispatch_by_format(volume):
    _, segy, store = volume
    assert isinstance(open_volume(store), ChunkedVolumeReader)
    assert isinstance(open_volume(segy), SegyVolumeReader)
    with pytest.raises(FileNotFoundError):
        open_volume("/nonexistent/thing.npy")


def test_transcoder_writes_grid_attributes(volume, tmp_path):
    _, _, store = volume
    meta = json.loads((store / "zarr.json").read_text())
    attrs = meta["attributes"]
    assert attrs["iline"] == {"start": IL_START, "step": IL_STEP}
    assert attrs["xline"] == {"start": XL_START, "step": XL_STEP}
    reader = open_volume(store)
    assert reader.geometry.source == "store"
    assert reader.geometry.iline_step == IL_STEP
    assert reader.geometry.xline_start == XL_START


# ------------------------------------------------------------- plane reads


def test_inline_crossline_timeslice_parity_with_source(volume):
    cube, _, store = volume
    vol = open_volume(store)
    il_value = IL_START + 3 * IL_STEP
    xl_value = XL_START + 5 * XL_STEP
    np.testing.assert_array_equal(vol.read_inline(il_value), cube[3, :, :])
    np.testing.assert_array_equal(vol.read_crossline(xl_value), cube[:, 5, :])
    np.testing.assert_array_equal(vol.read_timeslice(7), cube[:, :, 7])
    np.testing.assert_array_equal(vol.read_trace(il_value, xl_value), cube[3, 5, :])


def test_logical_values_rejected_outside_survey(volume):
    _, _, store = volume
    vol = open_volume(store)
    with pytest.raises(IndexError):
        vol.read_inline(IL_START - 3 * IL_STEP)  # well past the nearest edge
    with pytest.raises(IndexError):
        vol.read_inline(IL_START + NIL * IL_STEP)  # one full step past the last
    with pytest.raises(IndexError):
        vol.read_crossline(XL_START - 20 * XL_STEP)


# --------------------------------------------------------------------- LOD


def _floor_half(arr: np.ndarray) -> np.ndarray:
    """Floor-halving on the last two axes (LOD semantics: odd tails drop)."""
    h2, w2 = arr.shape[0] // 2, arr.shape[1] // 2
    return arr[: h2 * 2 : 2, : w2 * 2 : 2]


def test_lod_keeps_logical_coordinates(volume):
    """read_inline(SAME VALUE, lod=k) — never a level index.

    Level semantics: base index i maps to level cell ``i >> lod`` whose
    content decimates from the base cell START (``(i >> lod) << lod``).
    """
    _, _, store = volume
    vol = open_volume(store)
    assert not Path(f"{store}_l1").exists(), "LOD store must be lazy"
    base_i = 9
    il_value = IL_START + base_i * IL_STEP
    base = vol.read_inline(il_value, lod=0)
    for lod in (1, 2):
        at_lod = vol.read_inline(il_value, lod=lod)
        snapped_i = (base_i >> lod) << lod
        snapped = vol.read_inline(IL_START + snapped_i * IL_STEP, lod=0)
        ref = snapped
        for _ in range(lod):
            ref = _floor_half(ref)
        np.testing.assert_array_equal(at_lod, ref)


def test_lod_levels_are_sibling_stores_and_lazy(volume):
    _, _, store = volume
    vol = open_volume(store)
    vol.ensure_lods(2)
    assert vol.has_lod(1) and vol.has_lod(2)
    lvl1 = json.loads((Path(f"{store}_l1") / "zarr.json").read_text())
    assert list(lvl1["shape"]) == [NIL // 2, NXL // 2, NT // 2]
    lvl2 = json.loads((Path(f"{store}_l2") / "zarr.json").read_text())
    assert list(lvl2["shape"]) == [NIL // 4, NXL // 4, NT // 4]
    # mean strategy must not alias: it builds its OWN level stores
    vol_mean = open_volume(store, lod_strategy="mean")
    assert vol_mean._level_path(1) == f"{store}_l1_mean"
    a = vol.read_inline(IL_START + 9 * IL_STEP, lod=1)
    b = vol_mean.read_inline(IL_START + 9 * IL_STEP, lod=1)
    assert not np.allclose(a, b)
    assert Path(f"{store}_l1_mean").exists()


def test_maxabs_lod_preserves_strongest_event(volume):
    """maxabs level cells carry the strongest sample of each 2x2x2 base
    block (inline PAIRS included), sign-preserved."""
    cube, _, store = volume
    vol = open_volume(store, lod_strategy="maxabs")
    at1 = vol.read_inline(IL_START, lod=1)
    nx2, nt2 = at1.shape  # plane axes are (xline, time)
    blocks = cube[0:2, : nx2 * 2, : nt2 * 2].reshape(1, 2, nx2, 2, nt2, 2)
    flat = blocks.reshape(1, nx2, nt2, 8)
    idx = np.abs(flat).argmax(axis=-1)
    ref = np.take_along_axis(flat, idx[..., None], axis=-1)[..., 0]
    np.testing.assert_allclose(at1, ref[0], atol=1e-6)


# ----------------------------------------------------------- voxel window


def test_voxel_window_parity_direct_zarr_slice(volume):
    cube, _, store = volume
    vol = open_volume(store)
    win = vol.read_voxel_window(3, 30, 5, 40, 7, 60)
    np.testing.assert_array_equal(win, cube[3:30, 5:40, 7:60])
    # unaligned/half-open edges clamp, not error
    win2 = vol.read_voxel_window(NIL - 5, NIL + 99, 0, 3, 0, NT + 99)
    np.testing.assert_array_equal(win2, cube[NIL - 5 :, 0:3, :])


def test_voxel_window_lod_stride_semantics(volume):
    cube, _, store = volume
    vol = open_volume(store)
    win = vol.read_voxel_window(4, 36, 6, 44, 8, 62, lod=1)
    ref = cube[4:36, 6:44, 8:62][::2, ::2, ::2]
    np.testing.assert_allclose(win, ref[: win.shape[0], : win.shape[1], : win.shape[2]])


# -------------------------------------------------------- arbitrary line


def _reference_bilinear(cube, pts):
    """Straight per-point reference over the full in-memory cube."""
    out = []
    for il_v, xl_v in pts:
        fi = (il_v - IL_START) / IL_STEP
        fj = (xl_v - XL_START) / XL_STEP
        i0, j0 = int(np.floor(fi)), int(np.floor(fj))
        di, dj = fi - i0, fj - j0
        i0 = min(max(i0, 0), NIL - 2)
        j0 = min(max(j0, 0), NXL - 2)
        t00, t01 = cube[i0, j0, :], cube[i0, j0 + 1, :]
        t10, t11 = cube[i0 + 1, j0, :], cube[i0 + 1, j0 + 1, :]
        out.append(
            (t00 * (1 - dj) + t01 * dj) * (1 - di)
            + (t10 * (1 - dj) + t11 * dj) * di
        )
    return np.stack(out)


def test_arbitrary_line_batch_matches_reference(volume):
    cube, _, store = volume
    vol = open_volume(store)
    rng = np.random.default_rng(3)
    i_lo, i_hi = 2, NIL - 3
    j_lo, j_hi = 2, NXL - 3
    pts = [
        (
            IL_START + rng.uniform(i_lo, i_hi) * IL_STEP,
            XL_START + rng.uniform(j_lo, j_hi) * XL_STEP,
        )
        for _ in range(100)
    ]
    t0 = time.perf_counter()
    got = vol.read_arbitrary_line(pts, interpolate=True)
    dt = time.perf_counter() - t0
    ref = _reference_bilinear(cube, pts)
    np.testing.assert_allclose(got, ref, rtol=1e-5, atol=1e-5)
    assert dt < 0.2, f"100-point arbitrary line took {dt * 1000:.0f} ms"

    # nearest gather hits exact traces
    grid_pts = [
        (IL_START + 4 * IL_STEP, XL_START + 9 * XL_STEP),
        (IL_START + 20 * IL_STEP, XL_START + 30 * XL_STEP),
    ]
    got_n = vol.read_arbitrary_line(grid_pts, interpolate=False)
    np.testing.assert_allclose(got_n, np.stack([cube[4, 9, :], cube[20, 30, :]]), atol=1e-6)


def test_arbitrary_line_lod_decimates_output(volume):
    """Nearest gather at lod maps the point to a level CELL; that cell's
    trace is the base trace at (cell << lod) decimated."""
    _, _, store = volume
    vol = open_volume(store)
    base_il, base_xl = 4, 9
    pts = [
        (
            IL_START + base_il * IL_STEP,
            XL_START + base_xl * XL_STEP,
        )
    ]
    full = vol.read_arbitrary_line(pts, lod=0)[0]
    at1 = vol.read_arbitrary_line(pts, lod=1, interpolate=False)[0]
    k_i, k_j = round(base_il / 2), round(base_xl / 2)
    snapped = vol.read_trace(
        IL_START + (k_i * 2) * IL_STEP, XL_START + (k_j * 2) * XL_STEP
    )
    np.testing.assert_allclose(at1, snapped[: (len(snapped) // 2) * 2 : 2], atol=1e-6)
    assert full.shape[0] == NT


# ------------------------------------------------------------- SEG-Y path


def test_segy_backend_same_contract(volume):
    cube, segy, _ = volume
    vol = open_volume(segy)
    assert vol.geometry.iline_start == IL_START
    assert vol.geometry.iline_step == IL_STEP
    assert vol.geometry.xline_step == XL_STEP
    il_value = IL_START + 3 * IL_STEP
    xl_value = XL_START + 5 * XL_STEP
    np.testing.assert_allclose(vol.read_inline(il_value), cube[3, :, :], atol=1e-6)
    np.testing.assert_allclose(vol.read_trace(il_value, xl_value), cube[3, 5, :], atol=1e-6)
    win = vol.read_voxel_window(3, 12, 5, 20, 7, 40)
    np.testing.assert_allclose(win, cube[3:12, 5:20, 7:40], atol=1e-5)
    # lod decimates after read (floor-halving, odd tails drop)
    at1 = vol.read_inline(il_value, lod=1)
    ref = cube[3]
    ref = ref[: (ref.shape[0] // 2) * 2 : 2, : (ref.shape[1] // 2) * 2 : 2]
    np.testing.assert_allclose(at1, ref, atol=1e-6)


def test_segy_backend_arbitrary_line_nearest(volume):
    cube, segy, _ = volume
    vol = open_volume(segy)
    pts = [
        (IL_START + 4 * IL_STEP, XL_START + 9 * XL_STEP),
        (IL_START + 20 * IL_STEP, XL_START + 30 * XL_STEP),
    ]
    got = vol.read_arbitrary_line(pts, interpolate=False)
    np.testing.assert_allclose(got, np.stack([cube[4, 9, :], cube[20, 30, :]]), atol=1e-5)


# ---------------------------------------------------------------- geometry


def test_geometry_validation_and_assumed_fallback(tmp_path):
    g = VolumeGeometry(shape=(4, 4, 4), iline_start=100, iline_step=10)
    assert g.iline_to_index(130) == 3
    assert g.iline_to_index(134) == 3  # nearest grid point
    with pytest.raises(IndexError):
        g.iline_to_index(139)  # past last (100..130)

    # store without geometry attrs → assumed 1-based unit grid
    store = tmp_path / "legacy"
    a = zarr.create_array(str(store), shape=(3, 3, 3), dtype="f4")
    a[:] = np.arange(27, dtype="f4").reshape(3, 3, 3)
    vol = open_volume(store)
    assert vol.geometry.source == "assumed"
    np.testing.assert_array_equal(vol.read_inline(2), np.arange(9, 18, dtype="f4").reshape(3, 3))
    # explicit rebinding wins
    vol.attach_geometry(VolumeGeometry(shape=(3, 3, 3), iline_start=1000))
    assert vol.geometry.iline_start == 1000
