"""Scale smoke: lineage chain + summaries + metadata search at 1000+ versions.

Builds the document programmatically (no per-version file IO) so the numbers
isolate query cost: a 1000-deep chain, 300 extra governed assets, and the
per-revision summary cache. Bounds are generous (wall-clock smoke, not a
benchmark).
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from paleo_workbench.catalog import DataCatalogService, DataStage
from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataAsset,
    DataRun,
    DataVersion,
)


def _project_file(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture
def service(tmp_path):
    svc = DataCatalogService.open(_project_file(tmp_path))
    yield svc
    svc.close()


def _build_chain(service, depth: int) -> DataVersion:
    """A `depth`-long version chain RAW → DERIVED → … in the document."""
    document: CatalogDocument = service.document
    asset = DataAsset(id="asset_chain", name="chain-head", type="seismic")
    document.assets.append(asset)
    previous: DataVersion | None = None
    tail: DataVersion | None = None
    for i in range(depth):
        stage = DataStage.RAW if i == 0 else DataStage.DERIVED
        version = DataVersion(
            id=f"ver_chain_{i:05d}",
            asset_id=asset.id,
            version_number=i + 1,
            stage=stage,
            managed=False,  # no payload files in this synthetic document
            path="/synthetic/none",
            parent_version_ids=[previous.id] if previous is not None else [],
        )
        document.versions.append(version)
        asset.current_version_id = version.id
        previous = version
        tail = version
    assert tail is not None
    return tail


def test_lineage_chain_at_1000_depth_is_fast_and_correct(service):
    tail = _build_chain(service, 1000)
    service._invalidate_maps()

    start = time.perf_counter()
    chain = service.get_lineage_chain(tail.id)
    elapsed = time.perf_counter() - start
    assert chain.node_count == 1000
    assert not chain.truncated
    # O(V) walk over cached maps; generous CI bound.
    assert elapsed < 5.0, f"chain walk took {elapsed:.2f}s"


def test_lineage_summaries_scale_and_cache(service):
    tail = _build_chain(service, 1000)
    service._invalidate_maps()

    start = time.perf_counter()
    summaries = service.lineage_summaries()
    first = time.perf_counter() - start
    assert summaries[tail.id]["to_raw"] == 999
    assert first < 5.0, f"summaries build took {first:.2f}s"

    start = time.perf_counter()
    again = service.lineage_summaries()
    cached = time.perf_counter() - start
    assert again is summaries  # cached per revision
    assert cached < 0.05, f"cached lookup took {cached:.4f}s"


def test_metadata_search_over_1000_assets(service):
    document = service.document
    for i in range(1000):
        asset = DataAsset(
            id=f"asset_meta_{i:05d}",
            name=f"meta-{i}",
            type="well_log",
            metadata={"region": "塔里木" if i % 10 == 0 else "四川"},
        )
        document.assets.append(asset)
    service._invalidate_maps()
    service.rebuild_index()

    start = time.perf_counter()
    hits = service.search_assets(metadata={"region": "塔里木"})
    elapsed = time.perf_counter() - start
    assert len(hits) == 100
    assert elapsed < 5.0, f"indexed metadata search took {elapsed:.2f}s"

    service._index.reset()  # force the canonical scan branch
    start = time.perf_counter()
    hits_scan = service.search_assets(metadata={"region": "塔里木"})
    elapsed_scan = time.perf_counter() - start
    assert {a.id for a in hits_scan} == {a.id for a in hits}
    assert elapsed_scan < 5.0, f"scan fallback took {elapsed_scan:.2f}s"
