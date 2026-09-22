"""Catalog mutation scale budgets (Issue #1027).

Locks the SQLite-canonical write path to O(Δ) semantics at 20k assets:
single-row mutations must stay two orders of magnitude below a full-store
rewrite, batches of 1000 must amortize, and the JSON manifest must never be
touched by a mutation. Absolute budgets carry generous headroom over local
measurements; the SCALING assertions (mutation vs rebuild ratio) are the
real regression guard.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import DataCatalogService
from paleo_workbench.catalog.store import catalog_file_for

# `slow` as well: the fsync-heavy budgets need the nightly's 300s per-test
# timeout — the fast gate's 45s ceiling turned them into repeated
# runner-load timeouts (2026-08-29, twice on this branch, once on main).
pytestmark = [pytest.mark.capacity, pytest.mark.slow]

N_ASSETS = 20_000


def _seed_service(tmp_path: Path, n: int = N_ASSETS) -> DataCatalogService:
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("{}", encoding="utf-8")
    incoming = tmp_path / "incoming"
    incoming.mkdir(exist_ok=True)
    service = DataCatalogService.open(project)
    with service.batch_save():
        for i in range(n):
            src = incoming / f"w{i}.las"
            src.write_bytes(b"x" * 8)
            service.import_raw(src, name=f"well-{i:05d}", type="raw")
    # Materialize the manifest so the no-rewrite assertions have a baseline.
    service.export_manifest()
    return service


def _timed(fn):
    start = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - start


def test_single_tag_update_budget_and_scaling(tmp_path: Path):
    service = _seed_service(tmp_path)
    asset = service.document.assets[0]
    manifest_before = catalog_file_for(service.project_path).read_bytes()

    _, rebuild_s = _timed(lambda: service._index.reconcile(service.document))
    for i in range(5):
        service.add_tag(f"qc-{i}", asset_id=asset.id)
    _, mutate_s = _timed(lambda: service.add_tag("qc-final", asset_id=asset.id))

    # Absolute budget: generous CI headroom (local ~2ms).
    assert mutate_s < 0.10, f"single tag update took {mutate_s:.3f}s at {N_ASSETS}"
    # Algorithmic guard: a single-row write must not approach a full-store
    # reconcile (the O(N) JSON-rewrite equivalent of the pre-#1027 world).
    assert mutate_s < rebuild_s / 10, (
        f"single mutation {mutate_s:.3f}s vs full reconcile {rebuild_s:.3f}s"
    )
    # The manifest is never rewritten by mutations.
    assert catalog_file_for(service.project_path).read_bytes() == manifest_before
    service.close()


def test_single_metadata_update_budget(tmp_path: Path):
    service = _seed_service(tmp_path)
    asset = service.document.assets[1]

    _, mutate_s = _timed(
        lambda: service.update_asset_metadata(asset.id, {"quality": f"q{asset.id}"})
    )
    assert mutate_s < 0.10, f"metadata update took {mutate_s:.3f}s at {N_ASSETS}"

    reopened = DataCatalogService.open(service.project_path)
    assert reopened.get_asset(asset.id).metadata["quality"] == f"q{asset.id}"
    reopened.close()
    service.close()


def test_batch_of_1000_updates_budget(tmp_path: Path):
    service = _seed_service(tmp_path, n=5_000)
    targets = [a.id for a in service.document.assets[:1000]]

    def batch():
        with service.batch_save():
            for i, asset_id in enumerate(targets):
                service.update_asset_metadata(asset_id, {"batch": i})

    _, batch_s = _timed(batch)
    # Local ~0.4s; budget 2s for CI headroom.
    assert batch_s < 2.0, f"1000-row batch took {batch_s:.3f}s"

    reopened = DataCatalogService.open(service.project_path)
    assert reopened.get_asset(targets[999]).metadata["batch"] == 999
    reopened.close()
    service.close()


def test_mutation_does_not_deep_copy_document(tmp_path: Path):
    """No full-graph Pydantic copy on any mutation path (#1027)."""
    from paleo_workbench.catalog.models import CatalogDocument

    service = _seed_service(tmp_path, n=2_000)
    deep_calls: list[int] = []
    real_copy = CatalogDocument.model_copy

    def spy(self, **kwargs):
        if kwargs.get("deep"):
            deep_calls.append(len(self.assets))
        return real_copy(self, **kwargs)

    CatalogDocument.model_copy = spy  # type: ignore[method-assign]
    try:
        asset = service.document.assets[0]
        service.add_tag("x", asset_id=asset.id)
        service.update_asset_metadata(asset.id, {"k": 1})
        with service.batch_save():
            for a in service.document.assets[:50]:
                service.update_asset_metadata(a.id, {"batch": True})
    finally:
        CatalogDocument.model_copy = real_copy  # type: ignore[method-assign]

    assert deep_calls == [], "mutation path performed a full-graph deep copy"
    service.close()
