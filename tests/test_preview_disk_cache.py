from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from geoviz import PreparedPreview, PreviewKind
from geoviz.previews.dat import XYPreviewPayload

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider
from paleo_workbench.ui.pages.preview_disk_cache import (
    CACHEABLE_RESOURCE_TYPES,
    DIR_NAME,
    PreviewDiskCache,
)
from paleo_workbench.ui.pages.preview_provider import PreviewResult
from paleo_workbench.ui.pages.preview_worker import PreviewRequestController


def _wait_controller_idle(qtbot, controller: PreviewRequestController, timeout: int = 5000) -> None:
    """Block until in-flight preview workers finish (avoids Qt teardown aborts)."""
    qtbot.waitUntil(
        lambda: (
            controller._active_job.thread is None
            and controller._pending is None
        ),
        timeout=timeout,
    )


def _well_head_result(
    path: Path,
    *,
    resource_id: str = "",
    source_version: str = "",
) -> PreviewResult:
    has_identity = bool(resource_id or source_version)
    prepared = PreparedPreview(
        kind=PreviewKind.XY_SCATTER,
        title="wells",
        payload=XYPreviewPayload(
            names=("A1",),
            x=np.array([1.0]),
            y=np.array([2.0]),
            resource_id=resource_id,
            record_ids=(0,) if has_identity else (),
            source_rows=(3,) if has_identity else (),
            source_version=source_version,
        ),
        estimated_bytes=32,
    )
    return PreviewResult(
        mode="geoviz",
        title="wells",
        path=str(path),
        format="dat",
        type_label="well_head",
        engine_preview=prepared,
        estimated_bytes=32,
    )


def test_same_file_for_different_resources_keeps_separate_cached_identity(
    tmp_path: Path,
):
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "wells.dat"
    src.write_text("#WellHead File From SMI\n", encoding="utf-8")
    first = ResourceItem(
        id="resource-a",
        name="wells-a",
        path=str(src),
        type="well_head",
        format="dat",
        checksum="same-content",
    )
    second = first.model_copy(update={"id": "resource-b", "name": "wells-b"})
    cache = PreviewDiskCache(project_root=root)

    cache.store(
        first,
        _well_head_result(
            src,
            resource_id=first.id,
            source_version="checksum:same-content",
        ),
    )
    cache.store(
        second,
        _well_head_result(
            src,
            resource_id=second.id,
            source_version="checksum:same-content",
        ),
    )

    loaded_first = cache.try_load(first)
    loaded_second = cache.try_load(second)
    assert loaded_first is not None
    assert loaded_second is not None
    assert loaded_first.engine_preview.payload.resource_id == first.id
    assert loaded_second.engine_preview.payload.resource_id == second.id


@pytest.mark.parametrize(
    "update",
    [
        {"checksum": "content-v2"},
        {"crs": "EPSG:4326"},
        {
            "parsed_summary": {
                "coordinate_units": "ft",
                "comparison_crs": "EPSG:3857",
            }
        },
        {
            "parsed_summary": {
                "coordinate_units": "m",
                "comparison_crs": "EPSG:4326",
            }
        },
    ],
    ids=("checksum", "source-crs", "coordinate-units", "comparison-crs"),
)
def test_changed_xy_trust_metadata_does_not_reuse_cached_payload(
    tmp_path: Path,
    update: dict[str, object],
):
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "wells.dat"
    src.write_text("#WellHead File From SMI\n", encoding="utf-8")
    asset = ResourceItem(
        id="resource-a",
        name="wells",
        path=str(src),
        type="well_head",
        format="dat",
        checksum="content-v1",
        crs="EPSG:32648",
        parsed_summary={
            "coordinate_units": "m",
            "comparison_crs": "EPSG:3857",
        },
    )
    cache = PreviewDiskCache(project_root=root)
    cache.store(asset, _well_head_result(src))

    changed_asset = asset.model_copy(update=update)

    assert cache.try_load(changed_asset) is None


def test_store_and_load_roundtrip(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "wells.dat"
    src.write_text("#WellHead File From SMI\n", encoding="utf-8")
    asset = ResourceItem(
        id="r1", name="wells", path=str(src), type="well_head", format="dat"
    )
    cache = PreviewDiskCache(project_root=root)
    cache.store(asset, _well_head_result(src))
    loaded = cache.try_load(asset)
    assert loaded is not None
    assert loaded.mode == "geoviz"
    assert isinstance(loaded.engine_preview, PreparedPreview)
    assert loaded.engine_preview.kind is PreviewKind.XY_SCATTER


def test_mtime_change_is_miss(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "wells.dat"
    src.write_text("v1\n", encoding="utf-8")
    asset = ResourceItem(
        id="r1", name="wells", path=str(src), type="well_head", format="dat"
    )
    cache = PreviewDiskCache(project_root=root)
    cache.store(asset, _well_head_result(src))
    src.write_text("v2\n", encoding="utf-8")
    assert cache.try_load(asset) is None


def test_corrupt_payload_is_miss(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "wells.dat"
    src.write_text("v1\n", encoding="utf-8")
    asset = ResourceItem(
        id="r1", name="wells", path=str(src), type="well_head", format="dat"
    )
    cache = PreviewDiskCache(project_root=root)
    cache.store(asset, _well_head_result(src))
    entries = list((root / ".preview_cache" / "entries").iterdir())
    assert entries
    corrupt = entries[0]
    (corrupt / "payload.npz").write_bytes(b"not-npz")
    assert cache.try_load(asset) is None
    # Corrupt entries are removed so they do not accumulate.
    assert not corrupt.exists()


def test_is_disk_cacheable_rejects_las_and_sgy():
    from paleo_workbench.ui.pages.preview_disk_cache import is_disk_cacheable

    las = ResourceItem(
        id="l1", name="a", path="/tmp/a.las", type="well_log", format="las"
    )
    sgy = ResourceItem(
        id="s1", name="b", path="/tmp/b.sgy", type="seismic", format="sgy"
    )
    assert not is_disk_cacheable(las)
    assert not is_disk_cacheable(sgy)


def test_roundtrip_preserves_xy_arrays(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "wells.dat"
    src.write_text("#WellHead\n", encoding="utf-8")
    asset = ResourceItem(
        id="r1", name="wells", path=str(src), type="well_head", format="dat"
    )
    cache = PreviewDiskCache(project_root=root)
    original = _well_head_result(src)
    cache.store(asset, original)
    loaded = cache.try_load(asset)
    assert loaded is not None
    np.testing.assert_array_equal(loaded.engine_preview.payload.x, np.array([1.0]))
    np.testing.assert_array_equal(loaded.engine_preview.payload.y, np.array([2.0]))
    assert loaded.engine_preview.payload.names == ("A1",)


def test_clear_removes_entries(tmp_path: Path):
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "wells.dat"
    src.write_text("v1\n", encoding="utf-8")
    asset = ResourceItem(
        id="r1", name="wells", path=str(src), type="well_head", format="dat"
    )
    cache = PreviewDiskCache(project_root=root)
    cache.store(asset, _well_head_result(src))
    cache.clear()
    assert cache.try_load(asset) is None
    assert not (root / ".preview_cache" / "entries").exists() or not any(
        (root / ".preview_cache" / "entries").iterdir()
    )


def test_no_project_root_skips_disk(tmp_path: Path):
    src = tmp_path / "wells.dat"
    src.write_text("v1\n", encoding="utf-8")
    asset = ResourceItem(
        id="r1", name="wells", path=str(src), type="well_head", format="dat"
    )
    cache = PreviewDiskCache(project_root=None)
    cache.store(asset, _well_head_result(src))
    assert cache.try_load(asset) is None


def test_cacheable_type_set():
    assert CACHEABLE_RESOURCE_TYPES == {
        "horizon",
        "well_stratification",
        "well_head",
    }


def test_second_request_uses_disk_without_prepare(tmp_path: Path, qtbot):
    """After first prepare, memory-only clear still serves from disk without prepare."""
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "wells.dat"
    src.write_text(
        "#WellHead File From SMI\n"
        "#Name X Y KB TotalDepth BottomX BottomY WellType\n"
        "A1 100 200 0 1000 100 200 0\n",
        encoding="utf-8",
    )
    asset = ResourceItem(
        id="r1", name="wells", path=str(src), type="well_head", format="dat"
    )

    provider = LocalVisualizationProvider()
    prepare_calls = {"n": 0}
    original_prepare = provider.engine.prepare

    def counting_prepare(*args, **kwargs):
        prepare_calls["n"] += 1
        return original_prepare(*args, **kwargs)

    provider.engine.prepare = counting_prepare  # type: ignore[method-assign]

    controller = PreviewRequestController(provider)
    controller.set_project_root(root)
    results: list[PreviewResult] = []
    controller.result_ready.connect(results.append)

    controller.request(asset)
    _wait_controller_idle(qtbot, controller)

    assert prepare_calls["n"] == 1
    assert len(results) == 1
    assert results[0].mode == "geoviz"
    assert isinstance(results[0].engine_preview, PreparedPreview)
    entries = root / DIR_NAME / "entries"
    assert entries.is_dir()
    assert any(entries.iterdir())

    # Memory LRU only — disk entry must remain.
    controller.cache.clear()

    controller.request(asset)
    _wait_controller_idle(qtbot, controller)

    assert prepare_calls["n"] == 1
    assert len(results) == 2
    assert results[1].mode == "geoviz"
    assert isinstance(results[1].engine_preview, PreparedPreview)

    controller.shutdown()


def test_las_never_writes_preview_cache(tmp_path: Path, qtbot):
    """LAS is not disk-cacheable; preview must not create .preview_cache entries."""
    root = tmp_path / "proj"
    root.mkdir()
    src = root / "well.las"
    src.write_text("~Version\nVERS. 2.0 :\n~Well\n~Curve\n~A\n", encoding="utf-8")
    asset = ResourceItem(
        id="las1", name="well.las", path=str(src), type="well_log", format="las"
    )

    controller = PreviewRequestController(LocalVisualizationProvider())
    controller.set_project_root(root)
    results: list[PreviewResult] = []
    controller.result_ready.connect(results.append)

    controller.request(asset)
    _wait_controller_idle(qtbot, controller)
    assert results  # preview completed (geoviz or fallback)

    cache_root = root / DIR_NAME
    assert not cache_root.exists() or not any(
        (cache_root / "entries").glob("*") if (cache_root / "entries").exists() else []
    )

    controller.shutdown()
