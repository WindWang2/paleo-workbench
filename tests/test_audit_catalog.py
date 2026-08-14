"""Regression tests for the 2026-08 deep code audit fixes (catalog + resources).

Covers: preview registry project-relative path resolution, purge/restore
crash ordering, blob-dedup keep_source, produced-output checksum forwarding,
atomic exporter writes, dedup.is_cas_path correctness, and bounded GeoTIFF
overview reads.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.catalog.checksum import sha256_file
from paleo_workbench.catalog.models import CatalogError, DataStage
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.storage import (
    blob_dir_for,
    catalog_dir_for,
    place_managed_file,
)
from paleo_workbench.catalog.store import CatalogStore
from paleo_workbench.catalog import dedup
from paleo_workbench.catalog.adapter import CoreCatalogAdapter
from paleo_workbench.project.models import ResourceItem


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def _make_source(tmp_path: Path, name: str = "well.las", payload: bytes = b"las-bytes") -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


# --- F1: preview registry resolves project-relative asset paths --------------


def _text_settings():
    from paleo_workbench.ui.pages.preview_settings import PreviewSettings

    return PreviewSettings.defaults()


def test_build_preview_resolves_project_relative_path(tmp_path, monkeypatch):
    from paleo_workbench.resources.preview_parsers.registry import PreviewRegistry

    project_root = tmp_path / "proj"
    (project_root / "data").mkdir(parents=True)
    (project_root / "data" / "notes.txt").write_text("hello preview", encoding="utf-8")

    asset = ResourceItem(
        name="notes.txt",
        path="data/notes.txt",
        type="document",
        format="txt",
        status="parsed",
    )
    # CWD is NOT the project dir (pytest runs from the repo root).
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    result = PreviewRegistry().build_preview(asset, _text_settings())
    assert result.status == "missing"

    resolved = PreviewRegistry().build_preview(
        asset, _text_settings(), project_root=project_root
    )
    assert resolved.status != "missing"
    assert "hello preview" in (resolved.text or "")


def test_build_preview_project_root_blocks_escape(tmp_path, monkeypatch):
    from paleo_workbench.resources.preview_parsers.registry import PreviewRegistry

    project_root = tmp_path / "proj"
    project_root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    asset = ResourceItem(
        name="outside.txt",
        path="../outside.txt",
        type="document",
        format="txt",
        status="parsed",
    )
    monkeypatch.chdir(elsewhere)
    result = PreviewRegistry().build_preview(
        asset, _text_settings(), project_root=project_root
    )
    # A relative path that escapes the project root must stay unresolved
    # (the file does not exist at the CWD-relative location either).
    assert result.status == "missing"


def test_data_asset_registry_parse_preview_forwards_project_root(tmp_path, monkeypatch):
    from paleo_workbench.resources.data_asset_registry import DataAssetRegistry

    project_root = tmp_path / "proj"
    (project_root / "data").mkdir(parents=True)
    (project_root / "data" / "notes.txt").write_text("forwarded", encoding="utf-8")
    asset = ResourceItem(
        name="notes.txt", path="data/notes.txt", type="document", format="txt"
    )
    monkeypatch.chdir(tmp_path)
    result = DataAssetRegistry().parse_preview(asset, _text_settings(), project_root)
    assert result.status != "missing"


# --- F2: purge_trashed saves catalog state before unlinking payloads ---------


def test_purge_trashed_failed_save_keeps_payloads_restorable(service, tmp_path, monkeypatch):
    v1 = service.import_raw(_make_source(tmp_path, payload=b"payload-one"))
    v2 = service.import_raw(_make_source(tmp_path, name="two.las", payload=b"payload-two"))
    service.trash_asset(v1.asset_id, reason="cleanup")
    service.trash_asset(v2.asset_id, reason="cleanup")
    trash_paths = [service.resolve_path(v) for v in (v1, v2)]
    assert all(p.is_file() for p in trash_paths)

    def boom(_self, _document):
        raise OSError("disk full")

    monkeypatch.setattr(CatalogStore, "save", boom)
    with pytest.raises(OSError):
        service.purge_trashed()

    # Save failed: catalog state rolled back AND payloads still on disk, so a
    # later restore finds its bytes (old code unlinked before the save).
    assert all(p.is_file() for p in trash_paths)
    versions = {v.id: v for v in service.document.versions}
    assert versions[v1.id].trashed and versions[v2.id].trashed

    monkeypatch.undo()
    assert service.purge_trashed() == 4  # 2 versions + 2 assets
    assert not any(p.exists() for p in trash_paths)
    assert service.document.versions == []


# --- F3: restore rollback only touches versions the restore modified ---------


def test_restore_asset_failed_save_keeps_live_version_live(service, tmp_path, monkeypatch):
    v1 = service.import_raw(_make_source(tmp_path, payload=b"v1-bytes"))
    working = service.create_working_copy(v1.id)
    working.write_bytes(b"v2-bytes")
    v2 = service.commit_working_copy(working, asset_id=v1.asset_id)

    service.trash_asset(v1.asset_id, reason="cleanup")
    # Partially restore: v1 comes back while the asset (and v2) stay trashed.
    service.restore_version(v1.id)
    assert v1.trashed is False
    live_path = service.resolve_path(v1)
    assert live_path.is_file()

    def boom(_self, _document):
        raise OSError("disk full")

    monkeypatch.setattr(CatalogStore, "save", boom)
    with pytest.raises(OSError):
        service.restore_asset(v1.asset_id)

    # v1 was NOT modified by the failed restore_asset: it must stay live with
    # its payload at the stage location (old rollback re-trashed it and moved
    # the payload back into trash/).
    assert v1.trashed is False
    assert live_path.is_file()
    # v2 (actually restored-then-rolled-back) keeps its tombstone AND reason.
    assert v2.trashed is True
    assert v2.metadata["trash"]["reason"] == "cleanup"
    assert service._asset_or_raise(v1.asset_id).trashed is True


def test_restore_version_failed_save_preserves_reason(service, tmp_path, monkeypatch):
    v = service.import_raw(_make_source(tmp_path))
    service.trash_version(v.id, reason="duplicate")

    def boom(_self, _document):
        raise OSError("disk full")

    monkeypatch.setattr(CatalogStore, "save", boom)
    with pytest.raises(OSError):
        service.restore_version(v.id)

    assert v.trashed is True
    assert v.metadata["trash"]["reason"] == "duplicate"


# --- F4: blob-dedup fast path honors keep_source=False -----------------------


def test_place_managed_file_dedup_hit_consumes_source(service, tmp_path):
    src = _make_source(tmp_path, payload=b"dedup-content")
    digest = sha256_file(src)
    dedup.place_blob(service.project_path, src)
    assert dedup.has_blob(service.project_path, digest)

    working = tmp_path / "working" / "copy.las"
    working.parent.mkdir(parents=True, exist_ok=True)
    working.write_bytes(b"dedup-content")

    rel, size, sha = place_managed_file(
        working,
        service.project_path,
        DataStage.DERIVED,
        "asset-1",
        "version-1",
        keep_source=False,
        known_sha256=digest,
    )
    assert sha == digest
    assert dedup.is_cas_path(service.project_path, rel)
    # The source working file must not be orphaned in working/ forever.
    assert not working.exists()


def test_register_version_move_true_dedup_hit_removes_working_file(service, tmp_path):
    src = _make_source(tmp_path, payload=b"same-bytes")
    parent = service.import_raw(src)  # registers the blob via the import path
    working = service.create_working_copy(parent.id)
    working.write_bytes(b"same-bytes")

    version = service.register_version(
        parent.asset_id,
        working,
        DataStage.DERIVED,
        move=True,
        known_sha256=sha256_file(working),
    )
    assert dedup.is_cas_path(service.project_path, version.path)
    assert not working.exists()


# --- F5: produced outputs forward the caller-provided checksum ---------------


def test_register_output_forwards_checksum(service, tmp_path):
    adapter = CoreCatalogAdapter(service)
    src = _make_source(tmp_path, name="out.csv", payload=b"produced-bytes")
    run = adapter.begin_run(operation="audit-test", input_version_ids=[])
    digest = sha256_file(src)

    ref = adapter.register_output(
        run_id=run.run_id, name="out.csv", path=str(src), checksum=digest
    )
    assert service.get_version(ref.version_id).sha256 == digest


def test_register_output_rejects_wrong_checksum(service, tmp_path):
    adapter = CoreCatalogAdapter(service)
    src = _make_source(tmp_path, name="out.csv", payload=b"produced-bytes")
    run = adapter.begin_run(operation="audit-test", input_version_ids=[])

    with pytest.raises(CatalogError):
        adapter.register_output(
            run_id=run.run_id,
            name="out.csv",
            path=str(src),
            checksum="0" * 64,
        )


def test_register_output_dedups_to_existing_blob(service, tmp_path):
    adapter = CoreCatalogAdapter(service)
    payload = b"shared-output-bytes"
    src = _make_source(tmp_path, name="a.csv", payload=payload)
    imported = service.import_raw(src)  # registers the blob

    out = _make_source(tmp_path, name="b.csv", payload=payload)
    run = adapter.begin_run(
        operation="audit-test", input_version_ids=[imported.id]
    )
    ref = adapter.register_output(
        run_id=run.run_id,
        name="b.csv",
        path=str(out),
        checksum=imported.sha256,
    )
    version = service.get_version(ref.version_id)
    assert version.sha256 == imported.sha256
    assert dedup.is_cas_path(service.project_path, version.path)


# --- F6: exporters write atomically ------------------------------------------


def test_atomic_output_failure_removes_temp_and_keeps_original(tmp_path):
    from paleo_workbench.resources.exporters import atomic_output

    target = tmp_path / "out.json"
    target.write_text("ORIGINAL", encoding="utf-8")
    with pytest.raises(RuntimeError):
        with atomic_output(target) as tmp:
            tmp.write_text("PARTIAL", encoding="utf-8")
            raise RuntimeError("converter blew up mid-write")
    assert target.read_text(encoding="utf-8") == "ORIGINAL"
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


def test_atomic_output_success_replaces_target(tmp_path):
    from paleo_workbench.resources.exporters import atomic_output

    target = tmp_path / "out.csv"
    with atomic_output(target) as tmp:
        assert tmp.parent == tmp_path
        assert tmp.name.startswith(".out.csv.")
        tmp.write_text("DONE", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "DONE"
    assert [p.name for p in tmp_path.iterdir()] == ["out.csv"]


def test_failed_conversion_leaves_no_output(tmp_path):
    from paleo_workbench.resources.exporters import ExportError, geojson_normalize

    src = tmp_path / "broken.geojson"
    src.write_text("{not json", encoding="utf-8")
    out = tmp_path / "broken-normalized.geojson"
    with pytest.raises(ExportError):
        geojson_normalize(src, out)
    assert not out.exists()
    assert list(tmp_path.iterdir()) == [src]


def test_geojson_normalize_success_is_unchanged(tmp_path):
    from paleo_workbench.resources.exporters import geojson_normalize

    src = tmp_path / "ok.geojson"
    src.write_text(
        json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8"
    )
    out = tmp_path / "ok-normalized.geojson"
    geojson_normalize(src, out)
    assert json.loads(out.read_text(encoding="utf-8"))["type"] == "FeatureCollection"


# --- F7: dedup.is_cas_path resolves against the project root -----------------


def test_dedup_is_cas_path_distinguishes_stage_and_blob_paths(tmp_path):
    project_path = _make_project(tmp_path)
    blobs_root = blob_dir_for(project_path)
    stage_rel = "demo.artifacts/raw/asset-1/version-1/well.las"
    blob_rel = "demo.artifacts/blobs/ab/" + "ab" * 32

    # Old duplicate joined rel paths onto the blobs ROOT: any project-relative
    # path (stage copies included) reported True.
    assert dedup.is_cas_path(project_path, stage_rel) is False
    assert dedup.is_cas_path(project_path, blob_rel) is True

    blob_abs = blobs_root / "ab" / ("ab" * 32)
    blob_abs.parent.mkdir(parents=True, exist_ok=True)
    blob_abs.write_bytes(b"blob")
    assert dedup.is_cas_path(project_path, str(blob_abs)) is True
    assert dedup.is_cas_path(project_path, str(tmp_path / "outside.bin")) is False


def test_dedup_is_cas_path_matches_storage_semantics(tmp_path):
    from paleo_workbench.catalog import storage

    project_path = _make_project(tmp_path)
    for rel in (
        "demo.artifacts/blobs/ab/" + "ab" * 32,
        "demo.artifacts/raw/a/v/f.las",
        "demo.artifacts/trash/v1/f.las",
    ):
        assert dedup.is_cas_path(project_path, rel) is storage.is_cas_path(
            project_path, rel
        )


# --- F8: geotiff preview reads a bounded overview ----------------------------


class _ReadSpy:
    """Wrap a rasterio dataset, capturing every read() call."""

    def __init__(self, dataset):
        self._dataset = dataset
        self.reads: list[tuple] = []

    def read(self, *args, **kwargs):
        self.reads.append((args, kwargs.get("out_shape")))
        return self._dataset.read(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._dataset, name)

    def __enter__(self):
        self._dataset.__enter__()
        return self

    def __exit__(self, *exc):
        return self._dataset.__exit__(*exc)


def test_geotiff_preview_reads_single_bounded_overview(tmp_path, monkeypatch):
    rasterio = pytest.importorskip("rasterio")
    numpy = pytest.importorskip("numpy")
    from paleo_workbench.resources.preview_parsers.document_parsers import geotiff_preview

    src = tmp_path / "big.tif"
    height, width = 2000, 8000
    data = numpy.zeros((1, height, width), dtype="uint8")
    data[0, :, :] = numpy.arange(width, dtype="uint8")[None, :]
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "uint8",
    }
    with rasterio.open(src, "w", **profile) as dst:
        dst.write(data)
        dst.build_overviews([2, 4, 8])

    real_open = rasterio.open
    spy_holder: dict[str, _ReadSpy] = {}

    def spy_open(*args, **kwargs):
        dataset = real_open(*args, **kwargs)
        spy = _ReadSpy(dataset)
        spy_holder["spy"] = spy
        return spy

    monkeypatch.setattr(rasterio, "open", spy_open)

    resource = ResourceItem(
        name="big.tif", path=str(src), type="image_reference", format="tif"
    )
    result = geotiff_preview(resource, _text_settings())

    assert result.mode == "geotiff"
    assert result.image_bytes
    spy = spy_holder["spy"]
    # Exactly one read, first band only, at a bounded overview size — never
    # the full-resolution raster (old code: dataset.read() with no bounds).
    assert len(spy.reads) == 1
    (args, out_shape) = spy.reads[0]
    assert args == (1,)
    assert max(out_shape) <= 2048


def test_geotiff_preview_without_overviews_still_bounded(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    numpy = pytest.importorskip("numpy")
    from paleo_workbench.resources.preview_parsers.document_parsers import geotiff_preview

    src = tmp_path / "small.tif"
    profile = {"driver": "GTiff", "height": 64, "width": 64, "count": 1, "dtype": "uint8"}
    with rasterio.open(src, "w", **profile) as dst:
        dst.write(numpy.zeros((1, 64, 64), dtype="uint8"))

    resource = ResourceItem(
        name="small.tif", path=str(src), type="image_reference", format="tif"
    )
    result = geotiff_preview(resource, _text_settings())
    assert result.mode == "geotiff"
    assert result.image_bytes
