"""Missing Source / Relink closed loop (D9) — fail-closed identity proofs.

Pins:

* :meth:`DataCatalogService.find_missing_sources` reports gone payloads as
  derived state (nothing written to the store) and marks external RAW as
  the relinkable class;
* relink succeeds only against RECORDED facts — sha256 first, then the
  size+mtime_ns fingerprint written at link/relink time;
* a same-basename stranger with different content is REFUSED (the #1140
  trap), a size-only legacy match is refused, and managed versions are
  never relinkable;
* every success appends an auditable ``relink_history`` entry and survives
  reopen; a FAILED save rolls the version back to the exact prior state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog.models import CatalogError, DataStage
from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.sources import (
    CatalogRelinkIdentityError,
    EXTERNAL_STAT_KEY,
    RELINK_HISTORY_KEY,
)


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_make_project(tmp_path))
    yield svc
    svc.close()


def _external(tmp_path: Path, name: str = "GR1.las", payload: bytes = b"las-bytes-1"):
    src = tmp_path / "outside" / name
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(payload)
    return src


def test_link_external_records_identity_fingerprint(service, tmp_path):
    src = _external(tmp_path)
    version = service.link_external(src)
    fingerprint = version.metadata[EXTERNAL_STAT_KEY]
    assert fingerprint["size"] == src.stat().st_size
    assert fingerprint["mtime_ns"] == src.stat().st_mtime_ns


def test_missing_scan_reports_and_stays_derived(service, tmp_path):
    src = _external(tmp_path)
    version = service.link_external(src)
    managed = service.import_raw(
        source_path=_external(tmp_path, name="m.las", payload=b"m")
    )
    revision_before = service.document.catalog_revision

    report = service.find_missing_sources()
    assert report.scanned >= 2
    assert [e.version_id for e in report.entries] == []
    assert service.document.catalog_revision == revision_before  # scan writes nothing

    src.unlink()  # the external file "moves away"
    report = service.find_missing_sources()
    ids = [e.version_id for e in report.entries]
    assert ids == [version.id]
    entry = report.entries[0]
    assert entry.relinkable and entry.stage == DataStage.RAW
    assert not entry.managed
    # restore for the fixture teardown
    src.write_bytes(b"las-bytes-1")


def test_relink_by_stat_fingerprint(service, tmp_path):
    src = _external(tmp_path)
    version = service.link_external(src)
    moved = tmp_path / "relocated" / "GR1.las"
    moved.parent.mkdir(parents=True, exist_ok=True)
    src.replace(moved)  # same file: size + mtime_ns survive a rename

    relinked = service.relink_external_source(version.id, moved)
    assert relinked.path == moved.resolve().as_posix()
    assert relinked.metadata[EXTERNAL_STAT_KEY]["size"] == moved.stat().st_size
    history = relinked.metadata[RELINK_HISTORY_KEY]
    assert history[-1]["proof"] == "stat_fingerprint"
    assert history[-1]["old_path"] == src.resolve().as_posix()
    # resolve_path now serves the new location; the scan is clean.
    assert service.resolve_path(relinked) == moved.resolve()
    assert service.find_missing_sources().entries == []


def test_relink_rejects_basename_stranger(service, tmp_path):
    src = _external(tmp_path)
    version = service.link_external(src)
    src.unlink()
    stranger = tmp_path / "relocated" / "GR1.las"
    stranger.parent.mkdir(parents=True, exist_ok=True)
    stranger.write_bytes(b"totally-different-content")
    with pytest.raises(CatalogRelinkIdentityError):
        service.relink_external_source(version.id, stranger)
    # The refused relink left the recorded state untouched.
    assert version.path == src.resolve().as_posix()
    assert RELINK_HISTORY_KEY not in version.metadata


def test_relink_rejects_size_only_legacy_link(service, tmp_path):
    src = _external(tmp_path)
    version = service.link_external(src)
    # Simulate a legacy link: no fingerprint, no digest — only the size.
    version.metadata.pop(EXTERNAL_STAT_KEY)
    src.unlink()
    same_size = tmp_path / "relocated" / "GR1.las"
    same_size.parent.mkdir(parents=True, exist_ok=True)
    same_size.write_bytes(b"las-bytes-1")  # same bytes, unknown provenance
    with pytest.raises(CatalogRelinkIdentityError):
        service.relink_external_source(version.id, same_size)


def test_relink_by_sha256_beats_changed_mtime(service, tmp_path):
    src = _external(tmp_path)
    version = service.link_external(src)
    # Simulate a link with a recorded digest but a stale fingerprint.
    from paleo_workbench.catalog.checksum import sha256_file

    version.sha256 = sha256_file(src)
    version.metadata[EXTERNAL_STAT_KEY] = {"size": 1, "mtime_ns": 1}
    moved = tmp_path / "relocated" / "GR1.las"
    moved.parent.mkdir(parents=True, exist_ok=True)
    src.replace(moved)

    relinked = service.relink_external_source(version.id, moved)
    assert relinked.metadata[RELINK_HISTORY_KEY][-1]["proof"] == "sha256"


def test_relink_refuses_managed_and_trashed(service, tmp_path):
    managed = service.import_raw(
        source_path=_external(tmp_path, name="m.las", payload=b"m")
    )
    with pytest.raises(CatalogRelinkIdentityError):
        service.relink_external_source(managed.id, _external(tmp_path))
    external = service.link_external(_external(tmp_path, name="e.las"))
    service.trash_asset(external.asset_id)
    with pytest.raises(CatalogError):
        service.relink_external_source(external.id, _external(tmp_path))


def test_relink_rolls_back_on_failed_save(service, tmp_path, monkeypatch):
    src = _external(tmp_path)
    version = service.link_external(src)
    moved = tmp_path / "relocated" / "GR1.las"
    moved.parent.mkdir(parents=True, exist_ok=True)
    src.replace(moved)
    before = (version.path, version.source_uri, version.size_bytes, dict(version.metadata))

    real_save = type(service)._flush_canonical_locked

    def boom(_service, _dirty, **_kw):
        raise OSError("disk full")

    monkeypatch.setattr(type(service), "_flush_canonical_locked", boom)
    with pytest.raises(OSError):
        service.relink_external_source(version.id, moved)
    monkeypatch.setattr(type(service), "_flush_canonical_locked", real_save)

    assert (version.path, version.source_uri, version.size_bytes) == before[:3]
    assert version.metadata == before[3]


def test_relink_history_survives_reopen(service, tmp_path):
    src = _external(tmp_path)
    version = service.link_external(src)
    moved = tmp_path / "relocated" / "GR1.las"
    moved.parent.mkdir(parents=True, exist_ok=True)
    src.replace(moved)
    service.relink_external_source(version.id, moved)
    project_path = service.project_path
    service.close()

    reopened = DataCatalogService.open(project_path)
    try:
        version = reopened.get_version(version.id)
        assert version.path == moved.resolve().as_posix()
        assert version.metadata[RELINK_HISTORY_KEY][-1]["proof"] == "stat_fingerprint"
    finally:
        reopened.close()
