"""Issue #1139 — batch_save revision/store consistency + O(1) import dedup.

During ``batch_save`` the old ``_save`` bumped ``document.catalog_revision``
immediately while the SQLite write was deferred to the batch exit, so every
``index_revision() == document.catalog_revision`` freshness check failed
mid-batch and each ``register_input`` degraded to an O(N) linear scan
(O(M×N) for an M-file import). The fix: (a) the revision advances exactly
once at the batch transaction commit; (b) the adapter's dedup lookups go
through a maintained in-memory identity index validated against the live
document, with the linear scan demoted to a self-healing fallback.

Also covers #1138: the adapter's legacy-bridge and produced-asset saves pass
explicit DirtySets instead of scope-less full reconciles.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from paleo_workbench.catalog import CoreCatalogAdapter, DataCatalogService
from paleo_workbench.catalog.db import DirtySet


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


@pytest.fixture
def catalog(service: DataCatalogService) -> CoreCatalogAdapter:
    return CoreCatalogAdapter(service)


# --------------------------------------------------------- revision consistency


def test_batch_holds_revision_until_commit(service: DataCatalogService, tmp_path):
    """Inside the batch the document revision matches the store's view."""
    src = _make_source(tmp_path, "a.las", b"a")
    service.import_raw(src)
    before = service.document.catalog_revision
    assert service.index_revision() == before

    with service.batch_save():
        service.import_raw(_make_source(tmp_path, "b.las", b"b"))
        service.import_raw(_make_source(tmp_path, "c.las", b"c"))
        # Mid-batch: the store has not advanced, and neither may the
        # document's revision — that equality is what freshness checks rely
        # on (#1139).
        assert service.document.catalog_revision == before
        assert service.index_revision() == before

    # Batch commit advanced the revision exactly once and the store agrees.
    assert service.document.catalog_revision == before + 1
    assert service.index_revision() == service.document.catalog_revision
    assert len(service.document.assets) == 3


def test_batch_flush_failure_rolls_revision_back(service, tmp_path, monkeypatch):
    """A failed batch commit leaves revision AND memory at the store's state."""
    src = _make_source(tmp_path, "a.las", b"a")
    service.import_raw(src)
    before = service.document.catalog_revision

    def _boom(_self, _dirty, *, reconcile=False):
        raise RuntimeError("flush failed")

    monkeypatch.setattr(DataCatalogService, "_flush_canonical_locked", _boom)
    with pytest.raises(RuntimeError):
        with service.batch_save():
            service.import_raw(_make_source(tmp_path, "b.las", b"b"))
    monkeypatch.undo()

    assert service.document.catalog_revision == before
    assert service.index_revision() == before
    assert len(service.document.assets) == 1


def test_reopen_after_batch_sees_all_rows(service, tmp_path):
    """The single batch transaction must contain every accumulated row."""
    with service.batch_save():
        for i in range(5):
            service.import_raw(_make_source(tmp_path, f"f{i}.las", f"d{i}".encode()))
    service.close()
    reopened = DataCatalogService.open(service.project_path)
    try:
        assert len(reopened.document.assets) == 5
        assert reopened.index_revision() == reopened.document.catalog_revision
    finally:
        reopened.close()


# ------------------------------------------------------------- O(1) dedup index


def test_batch_dedup_uses_index_not_linear_scan(
    catalog: CoreCatalogAdapter, service: DataCatalogService, tmp_path, monkeypatch
):
    """Re-registering the SAME file inside a batch must not scan the document.

    Registers N=4 files (the first is re-registered three more times); the
    linear scan fallback is counted via monkeypatch — with the in-memory
    identity index it runs at most once (the very first, empty-catalog
    lookup), never per repeat.
    """
    scans = []
    real_scan = CoreCatalogAdapter._scan_managed_raw

    def counting_scan(self, source_uri, checksum):
        scans.append(source_uri)
        return real_scan(self, source_uri, checksum)

    monkeypatch.setattr(CoreCatalogAdapter, "_scan_managed_raw", counting_scan)

    src = _make_source(tmp_path, "same.las", b"same-bytes")
    with catalog.batch_save():
        for _ in range(4):
            ref = catalog.register_input(
                name="same.las", path=str(src), checksum=None
            )
    assert len(scans) <= 1, f"dedup fell back to linear scans: {scans}"
    # Idempotence held: ONE version, four identical refs.
    assert len(service.document.versions) == 1
    assert ref.version_id == service.document.versions[0].id


def test_dedup_index_survives_trash_and_reimport(
    catalog: CoreCatalogAdapter, service: DataCatalogService, tmp_path
):
    """Trash invalidates a dedup candidate; re-import registers fresh; the
    index self-heals instead of returning the trashed version."""
    src = _make_source(tmp_path, "t.las", b"t-bytes")
    first = catalog.register_input(name="t.las", path=str(src), checksum=None)
    service.trash_version(first.version_id)

    second = catalog.register_input(name="t.las", path=str(src), checksum=None)
    assert second.version_id != first.version_id
    assert not service.get_version(second.version_id).trashed
    # And the healed index resolves the new version without a scan.
    third = catalog.register_input(name="t.las", path=str(src), checksum=None)
    assert third.version_id == second.version_id


def test_external_dedup_index_hit(
    catalog: CoreCatalogAdapter, service: DataCatalogService, tmp_path, monkeypatch
):
    """External links dedup O(1) by resolved path; trashed links are skipped."""
    ext = _make_source(tmp_path, "ext.csv", b"csv")
    first = catalog.register_input(
        name="ext.csv", path=str(ext), checksum=None, external=True
    )
    scans = []
    real_scan = CoreCatalogAdapter._scan_external_by_path

    def counting_scan(self, resolved):
        scans.append(resolved)
        return real_scan(self, resolved)

    monkeypatch.setattr(CoreCatalogAdapter, "_scan_external_by_path", counting_scan)
    second = catalog.register_input(
        name="ext.csv", path=str(ext), checksum=None, external=True
    )
    assert second.version_id == first.version_id
    assert scans == []

    # Trashed external links must not dedup (re-link registers fresh).
    service.trash_version(first.version_id)
    third = catalog.register_input(
        name="ext.csv", path=str(ext), checksum=None, external=True
    )
    assert third.version_id != first.version_id


# ------------------------------------------------------- #1138 dirty-set saves


def test_bridge_legacy_id_uses_incremental_save(
    catalog: CoreCatalogAdapter, service: DataCatalogService, tmp_path, monkeypatch
):
    """The idempotent-hit bridge write is a DirtySet write, not a reconcile."""
    src = _make_source(tmp_path, "bridge.las", b"bridge")
    ref = catalog.register_input(name="bridge.las", path=str(src), checksum=None)

    reconciles = []
    real_reconcile = type(service._index).reconcile

    def counting_reconcile(self, document):
        reconciles.append(document.catalog_revision)
        return real_reconcile(self, document)

    monkeypatch.setattr(type(service._index), "reconcile", counting_reconcile)

    version = service.get_version(ref.version_id)
    catalog._bridge_legacy_id(version, "res_bridge_legacy")
    assert reconciles == [], "legacy bridge must not trigger a full reconcile"
    asset = service.get_asset(version.asset_id)
    assert asset.legacy_resource_id == "res_bridge_legacy"
    # The bridge persisted: a reopen resolves the legacy resource id.
    service.close()
    reopened = DataCatalogService.open(service.project_path)
    try:
        assert reopened._asset_by_legacy_id("res_bridge_legacy") is not None
    finally:
        reopened.close()


def test_register_output_new_asset_uses_incremental_save(
    catalog: CoreCatalogAdapter, service: DataCatalogService, tmp_path, monkeypatch
):
    """The produced-asset commit writes asset+version+run rows via DirtySet."""
    src = _make_source(tmp_path, "in.las", b"in")
    inp = catalog.register_input(name="in.las", path=str(src), checksum=None)
    run = catalog.begin_run(operation="op", input_version_ids=[inp.version_id])

    reconciles = []
    real_reconcile = type(service._index).reconcile

    def counting_reconcile(self, document):
        reconciles.append(document.catalog_revision)
        return real_reconcile(self, document)

    monkeypatch.setattr(type(service._index), "reconcile", counting_reconcile)
    out_src = _make_source(tmp_path, "out.npz", b"out")
    out = catalog.register_output(
        run_id=run.run_id, name="out.npz", path=str(out_src), checksum=None
    )
    assert reconciles == [], "produced-asset commit must not full-reconcile"

    # attach_lineage is the same #1138 class: one version's lineage row.
    catalog.attach_lineage(
        source_version_id=inp.version_id, target_version_id=out.version_id
    )
    assert reconciles == []

    service.close()
    reopened = DataCatalogService.open(service.project_path)
    try:
        version = reopened.get_version(out.version_id)
        assert version.run_id == run.run_id
        assert reopened.get_asset(version.asset_id).current_version_id == version.id
        assert reopened.get_run(run.run_id).output_version_ids == [version.id]
        assert inp.version_id in version.parent_version_ids
    finally:
        reopened.close()


def test_dirtyset_merge_reflects_all_batch_rows(service: DataCatalogService, tmp_path):
    """Rows accumulated across DIFFERENT mutators in one batch all commit."""
    with service.batch_save():
        v = service.import_raw(_make_source(tmp_path, "x.las", b"x"))
        service.add_tag("batch-tag", version_id=v.id)
        service.register_run("op", input_version_ids=[v.id])
    service.close()
    reopened = DataCatalogService.open(service.project_path)
    try:
        version = reopened.get_version(v.id)
        tag_ids = reopened.document.version_tags.get(v.id, [])
        assert len(tag_ids) == 1
        tag = next(
            t for t in reopened.document.tags if t.id == tag_ids[0]
        )
        assert tag.name == "batch-tag"
        assert len(reopened.document.runs) == 1
    finally:
        reopened.close()


def test_reads_during_batch_see_in_batch_writes(service, tmp_path):
    """Search and tag lookups mid-batch reflect the batch's own writes (the
    SQLite rows have not committed yet, so these must use the document)."""
    with service.batch_save():
        v = service.import_raw(_make_source(tmp_path, "needle.las", b"n"))
        service.add_tag("mid-batch-tag", version_id=v.id)
        found = service.search_assets(text="needle")
        assert [a.id for a in found] == [v.asset_id]
        tagged = service.find_versions_by_tag("mid-batch-tag")
        assert tagged == [v.id]
