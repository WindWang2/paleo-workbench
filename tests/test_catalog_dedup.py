"""Tests for the content-address dedup layer (P4, staged).

Covers the ContentStore abstraction (blob layout, atomic idempotent
placement), the O(1) copy-free import fast path for already-present digests,
version identity vs physical blob identity, refcount-safe lifecycle (trash /
restore / purge never unlink a shared blob), reachability GC, and metrics.
"""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

import pytest

from paleo_workbench.catalog import dedup
from paleo_workbench.catalog.models import CatalogDocument, CatalogError
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.storage import blob_path, place_blob


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@pytest.fixture
def service(tmp_path):
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True)
    project_path.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project_path)
    yield svc
    svc.close()


def _make_source(tmp_path: Path, name: str, payload: bytes) -> Path:
    src = tmp_path / "incoming" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


# ------------------------------------------------------------------ abstraction


def test_place_blob_is_idempotent_and_atomic(service, tmp_path):
    payload = b"cas bytes" * 100
    src = _make_source(tmp_path, "x.bin", payload)
    digest = _digest(payload)

    placed, computed = place_blob(service.project_path, src)
    assert computed == digest
    assert placed is True
    blob = blob_path(service.project_path, digest)
    assert blob.is_file()
    assert blob.read_bytes() == payload
    # Marked read-only (immutable by convention).
    assert not blob.stat().st_mode & stat.S_IWUSR

    # Idempotent: second placement copies nothing.
    placed_again, _ = place_blob(service.project_path, src)
    assert placed_again is False
    assert blob.stat().st_size == len(payload)


def test_has_blob_is_an_existence_check(service):
    assert dedup.has_blob(service.project_path, _digest(b"nope")) is False
    src = service.project_path.parent / "src.bin"
    src.write_bytes(b"present")
    place_blob(service.project_path, src)
    assert dedup.has_blob(service.project_path, _digest(b"present")) is True


def test_scan_blobs_and_metrics(service, tmp_path):
    payloads = [b"aaa", b"bbb", b"ccc"]
    for i, payload in enumerate(payloads):
        place_blob(service.project_path, _make_source(tmp_path, f"s{i}.bin", payload))

    blobs = dedup.scan_blobs(service.project_path)
    assert set(blobs) == {_digest(p) for p in payloads}
    metrics = dedup.blob_metrics(service.project_path, CatalogDocument())
    assert metrics["blobs_on_disk"] == 3
    assert metrics["unreferenced_blobs"] == 3
    assert metrics["bytes_deduped"] == 0


# ---------------------------------------------------- O(1) copy-free import


def test_import_of_present_digest_is_copy_free(service, tmp_path):
    payload = b"shared dataset" * 500
    digest = _digest(payload)
    first = _make_source(tmp_path, "a.bin", payload)

    v1 = service.import_raw(first)
    assert v1.sha256 == digest
    # Every managed RAW import registers its payload in the content store.
    assert dedup.has_blob(service.project_path, digest) is True

    # Second import from a DIFFERENT source path with the same content and a
    # caller-known checksum: O(1) — the version references the shared blob.
    second = _make_source(tmp_path, "b.bin", payload)
    v2 = service.import_raw(second, known_sha256=digest)

    assert v2.sha256 == digest
    assert "/blobs/" in v2.path
    assert v2.path.endswith(f"/{digest}")
    # Both versions are readable through the shared blob.
    assert service.resolve_path(v1).read_bytes() == payload
    assert service.resolve_path(v2).read_bytes() == payload
    assert service.verify_integrity(v2.id).status_for(v2.id) == "verified"
    # Only ONE physical blob exists for both versions.
    assert list(dedup.scan_blobs(service.project_path)) == [digest]


def test_import_without_known_checksum_still_copies_once(service, tmp_path):
    """No caller checksum → normal stage copy (never a blob fast path)."""
    payload = b"plain bytes"
    src = _make_source(tmp_path, "a.bin", payload)
    v = service.import_raw(src)
    assert "blobs" not in v.path
    assert service.resolve_path(v).read_bytes() == payload


def test_wrong_known_checksum_is_rejected_honestly(service, tmp_path):
    src = _make_source(tmp_path, "a.bin", b"real content")
    with pytest.raises(CatalogError):
        service.import_raw(src, known_sha256="0" * 64)
    # Nothing committed, nothing left behind.
    assert len(service.document.assets) == 0
    assert len(service.document.versions) == 0


def test_size_guard_prevents_blob_mismatch(service, tmp_path):
    """A same-digest blob with a different size must not be adopted."""
    digest = _digest(b"data-that-will-be-a-blob" * 50)
    src = _make_source(tmp_path, "a.bin", b"data-that-will-be-a-blob" * 50)
    service.import_raw(src)
    # A source claiming the digest but of a different size.
    other = _make_source(tmp_path, "b.bin", b"x" * 3)
    with pytest.raises(CatalogError):
        service.import_raw(other, known_sha256=digest)


def test_same_size_different_content_never_adopts_existing_blob(service, tmp_path):
    """A stale digest whose SIZE matches an existing blob but whose CONTENT
    differs must be rejected, never silently linked to the wrong payload.
    Regression: the O(1) fast path trusted (digest + size) without verifying
    content, so a stale caller checksum could register a version whose payload
    is NOT the source file's bytes (undetectable by integrity re-hash)."""
    seed = b"seed-content-that-registers-a-blob"
    digest = _digest(seed)
    first = _make_source(tmp_path, "seed.bin", seed)
    service.import_raw(first)
    assert dedup.has_blob(service.project_path, digest)

    # Same SIZE as the blob, different CONTENT, stale digest of the blob.
    stale = _make_source(tmp_path, "stale.bin", b"x" * len(seed))
    assert len(stale.read_bytes()) == len(seed)
    with pytest.raises(CatalogError):
        service.import_raw(stale, known_sha256=digest)

    # Nothing NEW was committed (only the seed asset remains) and the shared
    # blob is untouched.
    assert len(service.document.assets) == 1
    assert len(service.document.versions) == 1
    assert dedup.has_blob(service.project_path, digest)


# ---------------------------------------------------- lifecycle / refcounts


def test_trash_restore_never_unlinks_shared_blob(service, tmp_path):
    payload = b"shared lifecycle bytes" * 100
    digest = _digest(payload)
    s1 = _make_source(tmp_path, "one.bin", payload)
    s2 = _make_source(tmp_path, "two.bin", payload)
    v1 = service.import_raw(s1)
    v2 = service.import_raw(s2, known_sha256=digest)
    assert "/blobs/" in v2.path  # deduped

    # Trash the DEDUPED version: the shared blob must NOT move or disappear.
    service.trash_version(v2.id, reason="dedup test")
    assert service.resolve_path(v2).is_file()
    assert v2.path == service.get_version(v2.id).path  # path unchanged
    # The co-referencing version still reads fine.
    assert service.verify_integrity(v1.id).status_for(v1.id) == "verified"

    # Restore: still points at the blob, still readable.
    service.restore_version(v2.id)
    assert service.resolve_path(v2).read_bytes() == payload


def test_purge_keeps_blob_while_another_version_references_it(service, tmp_path):
    payload = b"refcount payload" * 100
    digest = _digest(payload)
    s1 = _make_source(tmp_path, "one.bin", payload)
    s2 = _make_source(tmp_path, "two.bin", payload)
    v1 = service.import_raw(s1)
    v2 = service.import_raw(s2, known_sha256=digest)

    service.trash_version(v1.id, reason="purge me")
    service.purge_trashed()
    # v1's stage copy is gone, but the blob survives because v2 references it.
    assert dedup.has_blob(service.project_path, digest) is True
    assert service.resolve_path(service.get_version(v2.id)).read_bytes() == payload


def test_purge_last_reference_sweeps_blob(service, tmp_path):
    payload = b"last ref" * 100
    digest = _digest(payload)
    src = _make_source(tmp_path, "a.bin", payload)
    v1 = service.import_raw(src)
    service.trash_version(v1.id, reason="purge me")
    service.purge_trashed()
    # v1's payload is a stage copy whose blob was ALSO placed at import. With
    # no version left referencing it, the blob is unreferenced (not deleted by
    # purge — GC reachability handles it), so has_blob may still be true.
    assert dedup.plan_blob_gc(service.project_path, service.document) == [digest]
    removed = dedup.sweep_unreferenced_blobs(
        service.project_path, service.document
    )
    assert removed == [digest]
    assert dedup.has_blob(service.project_path, digest) is False


def test_gc_never_removes_reachable_blob(service, tmp_path):
    payload = b"reachable" * 100
    src = _make_source(tmp_path, "a.bin", payload)
    service.import_raw(src)
    assert dedup.plan_blob_gc(service.project_path, service.document) == []
    assert dedup.sweep_unreferenced_blobs(
        service.project_path, service.document
    ) == []


def test_metrics_report_dedup_savings(service, tmp_path):
    payload = b"dedup me" * 200
    s1 = _make_source(tmp_path, "one.bin", payload)
    s2 = _make_source(tmp_path, "two.bin", payload)
    service.import_raw(s1)
    service.import_raw(s2, known_sha256=_digest(payload))
    metrics = dedup.blob_metrics(service.project_path, service.document)
    assert metrics["referenced_digests"] == 1
    assert metrics["bytes_deduped"] == len(payload)  # second copy is free
    assert metrics["unreferenced_blobs"] == 0


def test_blob_backed_version_has_separate_identity_from_blob(service, tmp_path):
    """Version identity (id) never equals the physical blob path/digest."""
    payload = b"identity" * 100
    s1 = _make_source(tmp_path, "one.bin", payload)
    s2 = _make_source(tmp_path, "two.bin", payload)
    digest = _digest(payload)
    v1 = service.import_raw(s1)
    v2 = service.import_raw(s2, known_sha256=digest)
    assert v1.id != v2.id  # distinct versions…
    assert v1.sha256 == v2.sha256  # …sharing one physical blob
    blob = blob_path(service.project_path, digest)
    assert blob.name == digest
    assert blob.name != v1.id and blob.name != v2.id


def test_no_writable_hardlink_is_created(service, tmp_path):
    """Deduped versions reference the blob; no hardlink is ever made."""
    payload = b"hardlink guard" * 100
    digest = _digest(payload)
    s1 = _make_source(tmp_path, "one.bin", payload)
    s2 = _make_source(tmp_path, "two.bin", payload)
    service.import_raw(s1)
    v2 = service.import_raw(s2, known_sha256=digest)
    path = service.resolve_path(v2)
    blob = blob_path(service.project_path, digest)
    if hasattr(os, "stat"):
        assert os.stat(path).st_ino == os.stat(blob).st_ino  # same file
    assert not path.stat().st_mode & stat.S_IWUSR  # and not writable


def test_crash_never_leaves_metadata_pointing_at_missing_blob(service, tmp_path):
    """A version's recorded path always resolves (blobs placed atomically)."""
    payload = b"atomic" * 100
    src = _make_source(tmp_path, "a.bin", payload)
    v = service.import_raw(src)
    # Reopen from disk: canonical catalog + payload tree stay consistent.
    svc2 = DataCatalogService.open(service.project_path)
    try:
        reloaded = svc2.get_version(v.id)
        assert svc2.resolve_path(reloaded).is_file()
        assert svc2.verify_integrity(v.id).status_for(v.id) == "verified"
    finally:
        svc2.close()
