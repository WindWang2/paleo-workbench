"""L5b — full-resolution arbitrary line through the real chunked path.

Production loop: SEG-Y → transcode → SeismicView.set_chunked_volume →
draw a polyline → ArbitraryLineWorker gathers via read_arbitrary_line →
the arbitrary PROFILE renders full-resolution data (not the preview
curtain). Verifies the windowed-read semantics end-to-end on a small
volume — no full-volume materialization beyond the transcode fixture.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PySide6")
segyio = pytest.importorskip("segyio")
zarr = pytest.importorskip("zarr")

from geoviz_seismic.seismic_view import SeismicView
from paleo_workbench.seismic_transcode import (
    TranscodeParams,
    transcode_segy_to_zarr,
)

NIL, NXL, NT = 8, 8, 64
IL_START, XL_START, STEP = 100, 200, 1


def _write_segy(path: Path) -> np.ndarray:
    rng = np.random.default_rng(5)
    cube = (rng.standard_normal((NIL, NXL, NT)) * 0.5).astype(np.float32)
    spec = segyio.spec()
    spec.ilines = list(range(IL_START, IL_START + NIL))
    spec.xlines = list(range(XL_START, XL_START + NXL))
    spec.samples = [float(s) for s in range(NT)]
    spec.format = 5
    with segyio.create(str(path), spec) as f:
        for il in range(NIL):
            for xl in range(NXL):
                i = il * NXL + xl
                f.header[i] = {
                    segyio.TraceField.INLINE_3D: IL_START + il,
                    segyio.TraceField.CROSSLINE_3D: XL_START + xl,
                    segyio.TraceField.TRACE_SEQUENCE_LINE: i + 1,
                }
                f.trace[i] = cube[il, xl]
    return cube


@pytest.fixture(scope="module")
def chunked_volume(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("arb")
    segy = tmp / "small.segy"
    cube = _write_segy(segy)
    store = tmp / "store"
    transcode_segy_to_zarr(segy, store, params=TranscodeParams(chunk=(4, 4, 16)))
    return cube, segy, store


def test_fullres_arbitrary_profile_replaces_preview_quality(qtbot, chunked_volume):
    cube, segy, store = chunked_volume
    view = SeismicView(auto_load=False)
    qtbot.addWidget(view)
    view.show()
    view.resize(1200, 800)
    qtbot.waitExposed(view)

    # 1. Load the RAW volume (async worker; wait for the loaded signal) so
    #    survey meta and the preview volume exist before attaching the store.
    with qtbot.waitSignal(view.segy_loaded, timeout=15000):
        view.load_segy(str(segy))
    assert view._meta is not None
    view.set_chunked_volume(str(store))

    # 2. Draw an arbitrary line diagonally across the Time slice.
    fracs = [(0.1, 0.1), (0.5, 0.4), (0.9, 0.8)]
    before = getattr(view._profile_arb, "_current_data", None)
    view._on_polyline_drawn(fracs)
    assert view._arb_survey_points is not None, "chunked store attached → full-res requested"

    # 3. The worker emits the gather asynchronously; wait for the panel to
    #    hold (n_samples, n_points) data with full vertical resolution.
    def fullres_arrived() -> bool:
        data = getattr(view._profile_arb, "_current_data", None)
        if data is None:
            return False
        return data.shape[1] == len(fracs)

    qtbot.waitUntil(fullres_arrived, timeout=8000)
    data = view._profile_arb._current_data
    assert data is not before
    # 3 polyline points → 3 columns; full-resolution vertical axis (the
    # preview curtain would carry fewer samples than NT for a downsampled
    # preview, and never a transposed (points, samples) shape).
    assert data.shape == (NT, len(fracs))

    # 4. Values match a direct read_arbitrary_line on the store (display
    #    path stays honest to the data).
    from geoviz_seismic.chunked import open_volume

    reader = open_volume(str(store))
    m = view._meta
    df = getattr(view, "_ds_factor", (1, 1, 1)) or (1, 1, 1)
    expected = reader.read_arbitrary_line(
        view._arb_survey_points, lod=0, interpolate=True
    )
    np.testing.assert_allclose(
        np.asarray(data, dtype=np.float32), expected.T, rtol=1e-4, atol=1e-5
    )

    # Production teardown contract: stop the workers BEFORE widget death,
    # mirroring what the hosting panel does on shutdown/project switch.
    view.cleanup()
