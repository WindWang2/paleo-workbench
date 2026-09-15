"""PR-gate real-format smoke (#1230).

Honest end-to-end prepare() coverage against tiny committed fixtures under
tests/fixtures/realdata/. Unlike tests/test_geoviz_real_data_smoke.py (slow /
nightly, large vendor data/), these must never skip when fixtures are missing
— a missing fixture is a gate failure.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from geoviz import GeoVizEngine, PreviewKind, PreviewOptions, PreviewRequest
from geoviz_seismic.loader import SeismicLoader

pytestmark = pytest.mark.realdata_smoke

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "realdata"


def _fixture(name: str) -> Path:
    path = FIXTURES / name
    if not path.is_file():
        pytest.fail(
            f"PR-gate realdata fixture missing (commit it, do not skip): {path}"
        )
    if path.stat().st_size == 0:
        pytest.fail(f"PR-gate realdata fixture is empty: {path}")
    return path


def _request(path: Path, semantic_type: str) -> PreviewRequest:
    return PreviewRequest(path.stem, str(path), semantic_type, path.suffix, path.stem)


def test_pr_fixture_tree_is_present_and_nonempty():
    expected = (
        "A1.Las",
        "ExportWellHead.dat",
        "DC.dat",
        "C3.dat",
        "A1_td.dat",
        "tiny.sgy",
    )
    for name in expected:
        path = _fixture(name)
        assert path.stat().st_size > 0


def test_pr_las_prepares_nonempty_bounded_payload():
    path = _fixture("A1.Las")
    options = PreviewOptions.local()

    preview = GeoVizEngine.default().prepare(_request(path, "well_log"), options)

    assert preview.kind is PreviewKind.WELL_LOG
    assert 0 < len(preview.payload.curves) <= options.max_curves
    for curve in preview.payload.curves:
        assert 0 < len(curve.depth) <= options.max_depth_samples
        assert len(curve.values) == len(curve.depth)
    assert preview.estimated_bytes > 0


@pytest.mark.parametrize(
    ("filename", "semantic_type", "expected_kind"),
    (
        ("ExportWellHead.dat", "well_head", PreviewKind.XY_SCATTER),
        ("DC.dat", "well_stratification", PreviewKind.FORMATION_TOPS),
        ("C3.dat", "horizon", PreviewKind.SURFACE),
        ("A1_td.dat", "time_depth", PreviewKind.TIME_DEPTH),
    ),
)
def test_pr_dat_prepares_nonempty_bounded_payload(
    filename: str, semantic_type: str, expected_kind: PreviewKind
):
    path = _fixture(filename)
    options = PreviewOptions.local()

    preview = GeoVizEngine.default().prepare(_request(path, semantic_type), options)

    assert preview.kind is expected_kind
    assert preview.estimated_bytes > 0
    payload = preview.payload
    if expected_kind is PreviewKind.XY_SCATTER:
        assert 0 < len(payload.names) <= options.max_points
        assert len(payload.x) == len(payload.y) == len(payload.names)
        assert np.all(np.isfinite(payload.x))
        assert np.all(np.isfinite(payload.y))
    elif expected_kind is PreviewKind.FORMATION_TOPS:
        assert 0 < len(payload) <= options.max_points
    elif expected_kind is PreviewKind.SURFACE:
        assert 0 < len(payload.grid_x) <= options.surface_grid_size
        assert 0 < len(payload.grid_y) <= options.surface_grid_size
        assert payload.grid_z.shape == (len(payload.grid_y), len(payload.grid_x))
        assert np.all(np.isfinite(payload.grid_z))
    else:
        assert 0 < len(payload.depth) <= options.max_points
        assert len(payload.time_ms) == len(payload.depth)
        assert np.all(np.isfinite(payload.depth))
        assert np.all(np.isfinite(payload.time_ms))


def test_pr_segy_reads_only_three_bounded_slices(monkeypatch):
    path = _fixture("tiny.sgy")
    options = PreviewOptions.local()

    def reject_full_volume(*args, **kwargs):
        pytest.fail("local preview must not load a full seismic volume")

    monkeypatch.setattr(SeismicLoader, "get_volume_downsampled", reject_full_volume)
    preview = GeoVizEngine.default().prepare(_request(path, "seismic"), options)

    assert preview.kind is PreviewKind.SEISMIC_2D
    assert set(preview.payload.slices) == {"inline", "crossline", "time"}
    for seismic_slice in preview.payload.slices.values():
        assert seismic_slice.data.ndim == 2
        assert seismic_slice.data.size > 0
        assert max(seismic_slice.data.shape) <= options.max_slice_axis
        assert np.all(np.isfinite(seismic_slice.data))
    assert preview.estimated_bytes > 0
