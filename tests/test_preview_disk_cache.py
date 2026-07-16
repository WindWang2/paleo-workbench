from __future__ import annotations

from pathlib import Path

import numpy as np

from geoviz import PreparedPreview, PreviewKind
from geoviz.previews.dat import XYPreviewPayload

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.preview_disk_cache import (
    CACHEABLE_RESOURCE_TYPES,
    PreviewDiskCache,
)
from paleo_workbench.ui.pages.preview_provider import PreviewResult


def _well_head_result(path: Path) -> PreviewResult:
    prepared = PreparedPreview(
        kind=PreviewKind.XY_SCATTER,
        title="wells",
        payload=XYPreviewPayload(
            names=("A1",),
            x=np.array([1.0]),
            y=np.array([2.0]),
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
    (entries[0] / "payload.npz").write_bytes(b"not-npz")
    assert cache.try_load(asset) is None


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
