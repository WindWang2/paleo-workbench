"""Issues #1172 / #1183 — manifest export stale guard + unchanged-write skip.

#1172: ``export_manifest`` wrote the in-memory document to catalog.json with
no stale protection, so state a flush had already refused to persist
(CatalogStaleWriteError) could be "revived" through the close-time manifest —
the very file a reopen re-imports from. The fix refuses the export with the
same store-vs-baseline comparison the flush uses.

#1183: close/export re-serialized the entire document (json.dumps indent=2)
and rewrote the manifest even when nothing changed. The store now keeps the
last written payload digest + manifest mtime and skips the whole cycle for an
unchanged document.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import (
    CatalogStaleWriteError,
    DataCatalogService,
)
from paleo_workbench.catalog.store import catalog_file_for


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


def _make_source(tmp_path: Path, name: str, payload: bytes) -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


@pytest.fixture
def service(tmp_path: Path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


# ----------------------------------------------------------------- #1172


def test_export_manifest_refuses_after_external_advance(service, tmp_path):
    """A store advanced by another process must not be overwritten via the
    manifest checkpoint."""
    src = _make_source(tmp_path, "mine.las", b"mine")
    service.import_raw(src)
    service.export_manifest()  # establish a manifest baseline
    manifest = catalog_file_for(service.project_path)
    baseline = manifest.read_text(encoding="utf-8")

    # A second process commits to the same canonical store.
    other = DataCatalogService.open(service.project_path)
    try:
        other.import_raw(_make_source(tmp_path, "theirs.las", b"theirs"))
    finally:
        # Close WITHOUT exporting: keep the manifest at our baseline so the
        # assertion below observes exactly what our stale export does.
        other._index.close()

    with pytest.raises(CatalogStaleWriteError):
        service.export_manifest()

    # The manifest was not overwritten with the stale in-memory state.
    assert manifest.read_text(encoding="utf-8") == baseline


def test_flush_and_export_agree_on_stale_semantics(service, tmp_path):
    """Both write paths refuse the same stale session (the guard is shared)."""
    other = DataCatalogService.open(service.project_path)
    try:
        other.import_raw(_make_source(tmp_path, "o.las", b"o"))
        other._index.close()
    finally:
        pass
    with pytest.raises(CatalogStaleWriteError):
        service.import_raw(_make_source(tmp_path, "s.las", b"s"))
    with pytest.raises(CatalogStaleWriteError):
        service.export_manifest()


def test_close_after_stale_does_not_revive_state(service, tmp_path):
    """close() swallows the manifest error but must not write the file."""
    src = _make_source(tmp_path, "c.las", b"c")
    service.import_raw(src)
    service.export_manifest()
    manifest = catalog_file_for(service.project_path)
    baseline = manifest.read_text(encoding="utf-8")

    other = DataCatalogService.open(service.project_path)
    try:
        other.import_raw(_make_source(tmp_path, "x.las", b"x"))
        other._index.close()
    finally:
        pass

    service.close()  # must not raise, must not write
    assert manifest.read_text(encoding="utf-8") == baseline
    # Reopen: the other process's commit survives.
    reopened = DataCatalogService.open(service.project_path)
    try:
        assert len(reopened.document.assets) == 2
    finally:
        reopened.close()


# ----------------------------------------------------------------- #1183


def test_unchanged_export_skips_rewrite(service, tmp_path):
    """A second export of an unchanged document leaves the file untouched."""
    src = _make_source(tmp_path, "u.las", b"u")
    service.import_raw(src)
    service.export_manifest()
    manifest = catalog_file_for(service.project_path)
    first_mtime = manifest.stat().st_mtime_ns
    first_bytes = manifest.read_bytes()

    service.export_manifest()

    assert manifest.read_bytes() == first_bytes
    assert manifest.stat().st_mtime_ns == first_mtime, (
        "unchanged manifest was rewritten on close/export"
    )


def test_changed_document_still_rewrites(service, tmp_path):
    """The skip must never swallow a real change."""
    service.import_raw(_make_source(tmp_path, "a.las", b"a"))
    service.export_manifest()
    manifest = catalog_file_for(service.project_path)
    before = manifest.read_text(encoding="utf-8")

    service.import_raw(_make_source(tmp_path, "b.las", b"b"))
    service.export_manifest()

    after = json.loads(manifest.read_text(encoding="utf-8"))
    assert after != json.loads(before)
    assert len(after["assets"]) == 2


def test_deleted_manifest_is_rewritten_even_when_unchanged(service, tmp_path):
    """The skip is anchored to the on-disk mtime: an externally deleted (or
    replaced) manifest defeats it and gets rewritten."""
    service.import_raw(_make_source(tmp_path, "d.las", b"d"))
    service.export_manifest()
    manifest = catalog_file_for(service.project_path)
    expected = manifest.read_text(encoding="utf-8")
    manifest.unlink()

    service.export_manifest()

    assert manifest.is_file()
    assert manifest.read_text(encoding="utf-8") == expected


def test_manifest_stays_human_readable(service, tmp_path):
    """The unchanged-skip preserves the pretty-printed manifest format."""
    service.import_raw(_make_source(tmp_path, "p.las", b"p"))
    service.export_manifest()
    text = catalog_file_for(service.project_path).read_text(encoding="utf-8")
    assert '\n  "catalog_revision"' in text
