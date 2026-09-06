"""Transactional revision CAS for the canonical catalog store (#1220).

The #411 stale-write guard used to be check-then-act: the revision was read
in a separate statement BEFORE the write transaction opened, so a foreign
commit landing in that window was silently overwritten (both writers stamped
the same revision). These tests pin the transactional contract:

- the compare happens INSIDE a BEGIN IMMEDIATE transaction — a foreign
  commit between the pre-check and the commit aborts with
  ``CatalogStaleWriteError`` and the foreign rows survive;
- ``rebuild_index`` and the unscoped reconcile path are guarded too (a stale
  full-diff used to DELETE the other process's rows);
- a REAL second process committing is detected (WAL cross-process), not just
  two services in one process.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import (
    CatalogStaleWriteError,
    DataCatalogService,
)


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


def _lie_about_precheck(service: DataCatalogService):
    """Make the service's cheap pre-check read a stale revision.

    Simulates exactly the #1220 window: another process committed AFTER this
    session's baseline read but BEFORE the write transaction opens. The
    transactional CAS in ``apply_changes`` must still catch it.
    """
    service._index.revision = lambda: service._flushed_revision  # type: ignore[method-assign]


def test_cas_aborts_foreign_commit_inside_window(tmp_path):
    project = _make_project(tmp_path)
    a = DataCatalogService.open(project)
    b = DataCatalogService.open(project)
    try:
        a.import_raw(_make_source(tmp_path, "a.las", b"a-bytes"))
        baseline = a.index_revision()

        _lie_about_precheck(b)
        with pytest.raises(CatalogStaleWriteError):
            b.import_raw(_make_source(tmp_path, "b.las", b"b-bytes"))

        # The foreign commit survived untouched; B's payload was not
        # registered anywhere.
        assert a.index_revision() == baseline
        fresh = DataCatalogService.open(project)
        try:
            assert len(fresh.document.versions) == 1
            assert fresh.document.versions[0].sha256 is not None
        finally:
            fresh.close()
    finally:
        a.close()
        b.close()


def test_unscoped_reconcile_cannot_delete_foreign_rows(tmp_path):
    """The O(N) reconcile fallback must refuse rather than diff-and-DELETE
    another process's committed rows. Driven through the unscoped ``_save``
    (reconcile=True) that rebase_artifact_paths uses when paths change."""
    project = _make_project(tmp_path)
    a = DataCatalogService.open(project)
    b = DataCatalogService.open(project)
    try:
        a.import_raw(_make_source(tmp_path, "a.las", b"a-bytes"))
        _lie_about_precheck(b)
        with pytest.raises(CatalogStaleWriteError):
            b._save()  # unscoped: full reconcile against B's stale document
        fresh = DataCatalogService.open(project)
        try:
            assert len(fresh.document.assets) == 1
        finally:
            fresh.close()
    finally:
        a.close()
        b.close()


def test_rebuild_index_guarded_against_foreign_revision(tmp_path):
    project = _make_project(tmp_path)
    a = DataCatalogService.open(project)
    b = DataCatalogService.open(project)
    try:
        a.import_raw(_make_source(tmp_path, "a.las", b"a-bytes"))
        # No lying needed: rebuild's own pre-check sees the advanced store.
        with pytest.raises(CatalogStaleWriteError):
            b.rebuild_index()
        # With a matching baseline the rebuild works and keeps content.
        a.rebuild_index()
        assert a.count_assets() == 1
    finally:
        a.close()
        b.close()


_CHILD_SCRIPT = """
import sys
from pathlib import Path
from paleo_workbench.catalog.service import DataCatalogService

project = Path(sys.argv[1])
source = Path(sys.argv[2])
service = DataCatalogService.open(project)
version = service.import_raw(source)
service.close()
print(version.id)
"""


def test_real_second_process_commit_is_refused(tmp_path):
    """A genuine other OS process commits; this session's next write refuses
    (WAL cross-process visibility of the committed revision)."""
    project = _make_project(tmp_path)
    parent = DataCatalogService.open(project)
    try:
        before = parent.index_revision()
        source = _make_source(tmp_path, "child.las", b"child-bytes")
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                _CHILD_SCRIPT,
                str(project),
                str(source),
            ],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[1]),
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        child_version_id = result.stdout.strip().splitlines()[-1]

        # The foreign commit is visible and durable.
        after = parent.index_revision()
        assert after is not None and after > (before or 0)

        with pytest.raises(CatalogStaleWriteError):
            parent.import_raw(_make_source(tmp_path, "parent.las", b"p-bytes"))

        # The child's row survived the refused parent write.
        fresh = DataCatalogService.open(project)
        try:
            assert fresh.get_version(child_version_id) is not None
        finally:
            fresh.close()
    finally:
        parent.close()


def test_failed_cas_leaves_store_transactionally_unchanged(tmp_path):
    project = _make_project(tmp_path)
    a = DataCatalogService.open(project)
    b = DataCatalogService.open(project)
    try:
        a.import_raw(_make_source(tmp_path, "a.las", b"a-bytes"))
        _lie_about_precheck(b)
        # B mutates several entity kinds, then the CAS aborts the single
        # flush transaction: NOTHING from B may be partially committed.
        with pytest.raises(CatalogStaleWriteError):
            with b.batch_save():
                b.import_raw(_make_source(tmp_path, "b1.las", b"b1"))
                b.import_raw(_make_source(tmp_path, "b2.las", b"b2"))
        fresh = DataCatalogService.open(project)
        try:
            names = [v.source_uri for v in fresh.document.versions]
            assert all("b1" not in (n or "") and "b2" not in (n or "") for n in names)
            assert len(fresh.document.versions) == 1
        finally:
            fresh.close()
    finally:
        a.close()
        b.close()
