from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from geoviz import GeoVizEngine, PreviewKind, PreviewOptions, PreviewRequest
from geoviz_seismic.loader import SeismicLoader
from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.classifier import classify_path
from paleo_workbench.ui.pages.preview_provider import PreviewProvider


pytestmark = pytest.mark.slow

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _default_data_root() -> Path:
    local_data = REPOSITORY_ROOT / "data"
    if local_data.is_dir():
        return local_data

    git_pointer = REPOSITORY_ROOT / ".git"
    if git_pointer.is_file():
        prefix = "gitdir:"
        value = git_pointer.read_text(encoding="utf-8").strip()
        if value.lower().startswith(prefix):
            git_dir = Path(value[len(prefix) :].strip())
            if not git_dir.is_absolute():
                git_dir = (REPOSITORY_ROOT / git_dir).resolve()
            common_git_dir = next(
                (path for path in (git_dir, *git_dir.parents) if path.name == ".git"),
                None,
            )
            if common_git_dir is not None:
                return common_git_dir.parent / "data"
    return local_data


DATA_ROOT = _default_data_root()


def _representative(relative_path: str) -> Path:
    path = DATA_ROOT / relative_path
    if not path.is_file():
        pytest.skip(f"representative data file is absent: {path}")
    return path


def _resource(path: Path) -> ResourceItem:
    semantic_type, format_name, status = classify_path(path)
    return ResourceItem(
        name=path.name,
        path=str(path),
        type=semantic_type,
        format=format_name,
        status=status,
    )


def _request(path: Path, semantic_type: str) -> PreviewRequest:
    return PreviewRequest(path.stem, str(path), semantic_type, path.suffix, path.stem)


def test_real_las_prepares_nonempty_bounded_payload():
    path = _representative("井曲线/A1.Las")
    options = PreviewOptions.local()

    preview = GeoVizEngine.default().prepare(_request(path, "well_log"), options)

    assert preview.kind is PreviewKind.WELL_LOG
    assert 0 < len(preview.payload.curves) <= options.max_curves
    for curve in preview.payload.curves:
        assert 0 < len(curve.depth) <= options.max_depth_samples
        assert len(curve.values) == len(curve.depth)
    assert preview.estimated_bytes > 0


@pytest.mark.parametrize(
    ("relative_path", "semantic_type", "expected_kind"),
    (
        ("井位/ExportWellHead.dat", "well_head", PreviewKind.XY_SCATTER),
        ("井分层/DC.dat", "well_stratification", PreviewKind.FORMATION_TOPS),
        ("层位/C3.dat", "horizon", PreviewKind.SURFACE),
        ("时深/TD/A1.dat", "time_depth", PreviewKind.TIME_DEPTH),
    ),
)
def test_real_dat_prepares_nonempty_bounded_payload(
    relative_path: str, semantic_type: str, expected_kind: PreviewKind
):
    path = _representative(relative_path)
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


def test_real_segy_reads_only_three_bounded_slices(monkeypatch):
    path = _representative("地震体/200P_seismic.sgy")
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


@pytest.mark.parametrize(
    "relative_path",
    (
        "外委资料/惠西南相图汇总/惠西南恩平组四段沉积相图 -mfy-lkv2.dfb",
        "外委资料/岩相古地理井资料12.23整理/"
        "HZ32-2-1井综合柱状图-1990-沉积-地化室-未钻遇烃源岩层-测井室-惠州勘探室.WLP",
    ),
)
def test_real_reference_format_has_image_or_message_fallback(relative_path: str):
    path = _representative(relative_path)

    result = PreviewProvider().preview(_resource(path))

    assert result.mode in {"image", "message"}
    if result.mode == "image":
        assert result.image_bytes or Path(result.path).is_file()
    else:
        assert result.message
