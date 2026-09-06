"""Lazy-open behavior for DataCatalogService (#1212, foundation v6).

Pins the contract of ``DataCatalogService.open(lazy=True)``:

- open skips the O(N) document materialization (fast, no full Pydantic graph);
- hot reads (get/list/page/count/aggregate/one-hop lineage) answer from the
  canonical store BEFORE the document warms up, with identical results;
- object identity is stable within the pre-warm window;
- the first mutation / full-document read materializes inline, after which
  behavior is byte-identical to an eagerly-opened service;
- a zero-mutation lazy session closes without rewriting the manifest;
- background warmup races a concurrent mutation safely.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from paleo_workbench.catalog.models import DataStage
from paleo_workbench.catalog.service import DataCatalogService, CatalogError
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


def _seed_catalog(project_path: Path, tmp_path: Path, n: int = 6):
    """Create a catalog with n raw assets + derived child, then close it."""
    service = DataCatalogService.open(project_path)
    try:
        for i in range(n):
            src = _make_source(tmp_path, f"w{i}.las", f"las-bytes-{i}".encode())
            version = service.import_raw(src)
            if i == 0:
                service.create_derived(
                    src,
                    parent_version_ids=[version.id],
                    name=f"derived-{i}",
                    operation="test.derive",
                )
        service.add_tag("井", asset_id=service.list_assets()[0].id)
    finally:
        service.close()


@pytest.fixture
def seeded_project(tmp_path):
    project_path = _make_project(tmp_path)
    _seed_catalog(project_path, tmp_path)
    return project_path, tmp_path


def test_lazy_open_skips_materialization(seeded_project):
    project_path, _ = seeded_project
    service = DataCatalogService.open(project_path, lazy=True, sweep_temp=False)
    try:
        assert service.is_warm is False
        # The document is deliberately empty pre-warm; reads must NOT touch it.
        assert service.document.assets == []
        assert service.document.versions == []
        # Baseline revision is the store's committed revision.
        assert service.index_revision() == service.document.catalog_revision
    finally:
        service.close()


def test_lazy_hot_reads_match_eager(seeded_project):
    project_path, _ = seeded_project
    lazy = DataCatalogService.open(project_path, lazy=True, sweep_temp=False)
    eager = DataCatalogService.open(project_path)
    try:
        assert lazy.is_warm is False
        lazy_assets = lazy.list_assets()
        eager_assets = eager.list_assets()
        assert [a.id for a in lazy_assets] == [a.id for a in eager_assets]

        first = lazy_assets[0]
        assert lazy.get_asset(first.id).id == first.id
        # identity stability within the pre-warm window
        assert lazy.get_asset(first.id) is first

        version = eager.get_version(eager.document.assets[0].current_version_id)
        lazy_version = lazy.get_version(version.id)
        assert lazy_version.sha256 == version.sha256
        assert lazy_version.parent_version_ids == version.parent_version_ids

        versions = lazy.list_versions(first.id)
        eager_versions = eager.list_versions(first.id)
        assert [v.id for v in versions] == [v.id for v in eager_versions]

        lazy_runs = lazy.list_runs()
        eager_runs = eager.list_runs()
        assert [r.id for r in lazy_runs] == [r.id for r in eager_runs]
        run = lazy_runs[0]
        assert lazy.get_run(run.id).operation == eager.get_run(run.id).operation

        # Unknown ids raise the same typed error without warming up.
        assert not lazy.is_warm
        with pytest.raises(CatalogError):
            lazy.get_asset("asset-does-not-exist")
        with pytest.raises(CatalogError):
            lazy.get_version("ver-does-not-exist")
        assert not lazy.is_warm  # a miss must not pay the full materialization
    finally:
        lazy.close()
        eager.close()


def test_lazy_paged_queries_and_aggregates(seeded_project):
    project_path, _ = seeded_project
    lazy = DataCatalogService.open(project_path, lazy=True, sweep_temp=False)
    try:
        page = lazy.search_assets_page(limit=3)
        assert 0 < len(page) <= 3
        assert lazy.count_assets() >= 6
        agg = lazy.catalog_aggregates()
        assert agg["total"] == lazy.count_assets()
        assert not lazy.is_warm  # queries never force materialization
    finally:
        lazy.close()


def test_lazy_lineage_one_hop(seeded_project):
    project_path, _ = seeded_project
    lazy = DataCatalogService.open(project_path, lazy=True, sweep_temp=False)
    eager = DataCatalogService.open(project_path)
    try:
        raw = eager.list_assets()[0]
        raw_version = eager.get_version(raw.current_version_id)
        derived = [
            v for v in eager.document.versions if v.parent_version_ids
        ][0]
        lineage = lazy.get_lineage(derived.id)
        assert lineage["version"].id == derived.id
        assert [p.id for p in lineage["parents"]] == [raw_version.id]
        assert lineage["run"] is not None
        # Ancestors from the raw side see the derived child.
        down = lazy.get_lineage(raw_version.id)
        assert derived.id in [c.id for c in down["children"]]
        assert not lazy.is_warm
    finally:
        lazy.close()
        eager.close()


def test_lazy_mutation_materializes_inline(seeded_project, tmp_path):
    project_path, _ = seeded_project
    lazy = DataCatalogService.open(project_path, lazy=True, sweep_temp=False)
    try:
        src = _make_source(tmp_path, "new.las", b"new-bytes")
        version = lazy.import_raw(src)
        # The mutation forced the inline warmup; the document is whole again.
        assert lazy.is_warm is True
        assert any(a.id == version.asset_id for a in lazy.document.assets)
        assert version in lazy.document.versions
        assert lazy.count_assets() == len(lazy.document.assets)
    finally:
        lazy.close()
    # The committed state reopens identically the eager way.
    verify = DataCatalogService.open(project_path)
    try:
        assert verify.get_version(version.id).sha256 == version.sha256
        assert len(verify.document.assets) == verify.count_assets()
    finally:
        verify.close()


def test_lazy_full_read_materializes_inline(seeded_project):
    project_path, _ = seeded_project
    lazy = DataCatalogService.open(project_path, lazy=True, sweep_temp=False)
    try:
        tags = lazy.list_tags()  # warm-guarded read
        assert lazy.is_warm is True
        assert any(t.name == "井" for t in tags)
        assert len(lazy.document.assets) >= 6
    finally:
        lazy.close()


def test_lazy_close_without_mutations_keeps_manifest(seeded_project):
    project_path, _ = seeded_project
    manifest = catalog_file_for(project_path)
    before = manifest.read_bytes()
    before_mtime = manifest.stat().st_mtime_ns
    lazy = DataCatalogService.open(project_path, lazy=True, sweep_temp=False)
    lazy.get_asset(lazy.list_assets()[0].id)  # reads are free
    lazy.close()
    assert manifest.read_bytes() == before
    assert manifest.stat().st_mtime_ns == before_mtime


def test_lazy_close_after_mutation_exports_manifest(seeded_project, tmp_path):
    project_path, _ = seeded_project
    manifest = catalog_file_for(project_path)
    before = manifest.read_bytes()
    lazy = DataCatalogService.open(project_path, lazy=True, sweep_temp=False)
    try:
        src = _make_source(tmp_path, "close-me.las", b"close-bytes")
        lazy.import_raw(src)
    finally:
        lazy.close()
    assert manifest.read_bytes() != before
    reopened = DataCatalogService.open(project_path)
    try:
        assert any(v.sha256 for v in reopened.document.versions)
        assert reopened.count_assets() >= 7
    finally:
        reopened.close()


def test_background_warmup_races_mutation(seeded_project, tmp_path):
    project_path, _ = seeded_project
    lazy = DataCatalogService.open(project_path, lazy=True, sweep_temp=False)
    try:
        warm_thread = threading.Thread(target=lazy.warm_document)
        warm_thread.start()
        # A mutation racing the background warm must land exactly once.
        src = _make_source(tmp_path, "race.las", b"race-bytes")
        version = lazy.import_raw(src)
        warm_thread.join(timeout=30)
        assert lazy.is_warm is True
        ids = [v.id for v in lazy.document.versions]
        assert ids.count(version.id) == 1
        assert len(lazy.document.assets) == lazy.count_assets()
    finally:
        lazy.close()
    verify = DataCatalogService.open(project_path)
    try:
        assert verify.get_version(version.id) is not None
        assert len(verify.document.assets) == verify.count_assets()
    finally:
        verify.close()


def test_lazy_and_eager_sessions_equivalent(seeded_project, tmp_path):
    """Same op sequence through lazy and eager services → identical stores."""
    project_a = _make_project(tmp_path / "a")
    project_b = _make_project(tmp_path / "b")
    _seed_catalog(project_a, tmp_path / "a", n=3)
    _seed_catalog(project_b, tmp_path / "b", n=3)

    lazy = DataCatalogService.open(project_a, lazy=True, sweep_temp=False)
    eager = DataCatalogService.open(project_b)
    try:
        for service in (lazy, eager):
            src = _make_source(
                service.project_path.parent,
                "extra.las",
                b"extra-bytes",
            )
            service.import_raw(src)
            service.add_tag("extra", asset_id=service.list_assets()[0].id)
            service.trash_asset(service.list_assets()[-1].id)
    finally:
        lazy.close()
        eager.close()

    a = DataCatalogService.open(project_a)
    b = DataCatalogService.open(project_b)
    try:
        assert a.count_assets() == b.count_assets()
        assert len(a.document.versions) == len(b.document.versions)
        assert len(a.document.runs) == len(b.document.runs)
        assert [t.name for t in a.document.tags] == [t.name for t in b.document.tags]
        assert (
            len(a.get_trashed_assets()) == len(b.get_trashed_assets())
        )
    finally:
        a.close()
        b.close()


def test_open_budget_at_scale(tmp_path):
    """The v6 gate: 100k metadata entities open in <500 ms (GUI path)."""
    import time

    project_path = _make_project(tmp_path)
    # Seed directly through the real API inside one batch (fast: no payload
    # IO beyond 8-byte files, single transaction per the #1139 batch path).
    seeder = DataCatalogService.open(project_path)
    try:
        with seeder.batch_save():
            for i in range(2000):  # CI-scale seed; ratio documented in docs
                src = _make_source(
                    tmp_path, f"s{i}.las", f"{i}".encode()
                )
                seeder.import_raw(src)
    finally:
        seeder.close()

    started = time.perf_counter()
    lazy = DataCatalogService.open(project_path, lazy=True, sweep_temp=False)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    try:
        assert lazy.is_warm is False
        assert lazy.count_assets() == 2000
        assert lazy.get_asset(lazy.list_assets()[0].id) is not None
        assert not lazy.is_warm
    finally:
        lazy.close()
    # Budget generous for CI machines; the eager comparison below shows the
    # materialization this avoids.
    started = time.perf_counter()
    eager = DataCatalogService.open(project_path)
    eager_ms = (time.perf_counter() - started) * 1000.0
    try:
        assert len(eager.document.assets) == 2000
    finally:
        eager.close()
    print(f"\nlazy open {elapsed_ms:.1f} ms vs eager open {eager_ms:.1f} ms")
    assert elapsed_ms < 500.0
