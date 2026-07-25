"""Regression: Time slice axis order must match volume[:,:,t] (3D vs 2D)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from paleo_workbench.env_bootstrap import ensure_geoviz_on_path

ensure_geoviz_on_path()


@pytest.fixture(scope="module")
def demo_segy() -> Path:
    path = Path("data/地震体/200P_seismic.sgy")
    if not path.is_file():
        pytest.skip("demo SEGY not available")
    return path


def test_read_timeslice_matches_volume_axes(demo_segy: Path):
    """2D Time profile source and 3D horizontal plane must share (IL, XL) order."""
    from geoviz_seismic.loader import SeismicLoader

    loader = SeismicLoader(str(demo_segy))
    try:
        meta = loader.inspect()
        t = meta.n_samples // 2
        ts = loader.read_timeslice(t)
        assert ts.shape == (meta.n_inlines, meta.n_crosslines), (
            f"timeslice {ts.shape} != volume axes "
            f"({meta.n_inlines}, {meta.n_crosslines})"
        )
        # Must match assembly from inlines (canonical volume layout)
        manual = np.empty((meta.n_inlines, meta.n_crosslines), dtype=np.float32)
        f = loader._open()
        for i, il in enumerate(f.ilines.tolist()):
            manual[i, :] = np.asarray(f.iline[il], dtype=np.float32)[:, t]
        np.testing.assert_allclose(ts, manual, rtol=0, atol=0)

        # Downsampled volume time plane agrees with strided timeslice
        factor = (6, 4, 8)
        vol = loader.get_volume_downsampled(factor)
        t_idx = vol.shape[2] // 2
        t_full = t_idx * factor[2]
        ts2 = loader.read_timeslice(t_full)
        a = ts2[:: factor[0], :: factor[1]][: vol.shape[0], : vol.shape[1]]
        b = vol[: a.shape[0], : a.shape[1], t_idx]
        corr = float(np.corrcoef(a.ravel().astype(float), b.ravel().astype(float))[0, 1])
        assert corr > 0.95, f"3D preview time vs timeslice strided corr={corr}"
    finally:
        loader.close()


def test_normalize_timeslice_swaps_segyio_order():
    from geoviz_seismic.loader import SeismicLoader
    from geoviz_seismic.models import SeismicVolumeMeta

    meta = SeismicVolumeMeta(
        filename="x",
        n_inlines=4,
        n_crosslines=3,
        n_samples=2,
        sample_interval=2.0,
        iline_start=1,
        iline_step=1,
        xline_start=10,
        xline_step=1,
        dt_ms=2.0,
    )
    # Simulate segyio depth_slice orientation (XL, IL)
    swapped = np.arange(12, dtype=np.float32).reshape(3, 4)
    fixed = SeismicLoader._normalize_timeslice_axes(swapped, meta)
    assert fixed.shape == (4, 3)
    np.testing.assert_array_equal(fixed, swapped.T)
