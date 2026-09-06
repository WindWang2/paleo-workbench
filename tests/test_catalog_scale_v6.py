"""V6 scale gates (CI-size; §13) — see benchmarks/catalog_scale_v6.py for
the full 100k/500k tiers (numbers recorded in 08-scale-benchmarks.md).

The budgets below are generous CI bounds on shared machines; they pin the
SHAPE (lazy open is not linear in assets; queries are page-shaped), not
microbenchmark optima.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from paleo_workbench.catalog.service import (
    CatalogStaleWriteError,
    DataCatalogService,
)

N = 1500


def _make_project(tmp_path: Path) -> Path:
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    return project_path


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("v6scale")
    project = _make_project(tmp)
    service = DataCatalogService.open(project)
    incoming = tmp / "incoming"
    incoming.mkdir(exist_ok=True)
    try:
        with service.batch_save():
            for i in range(N):
                src = incoming / f"s{i}.las"
                src.write_bytes(f"{i}".encode())
                service.import_raw(src)
    finally:
        service.close()
    return project


def _budget_ms(fn, budget: float) -> float:
    t0 = time.perf_counter()
    fn()
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert elapsed < budget, f"{elapsed:.1f} ms exceeded {budget} ms budget"
    return elapsed


def test_lazy_open_budget(seeded):
    lazy = _budget_ms(
        lambda: DataCatalogService.open(seeded, lazy=True, sweep_temp=False),
        500.0,
    )
    service = DataCatalogService.open(seeded, lazy=True, sweep_temp=False)
    try:
        assert service.is_warm is False
        _budget_ms(lambda: service.search_assets_page(limit=500), 150.0)
        _budget_ms(
            lambda: service.search_assets_page(limit=500, offset=N // 2), 200.0
        )
        first = service.search_assets_page(limit=1)[0]
        _budget_ms(lambda: service.get_asset(first["id"]), 10.0)
        assert not service.is_warm  # queries never forced materialization
    finally:
        service.close()


def test_query_usable_during_background_warmup(seeded):
    """Background warmup must not block page queries (#1212 honest loading)."""
    import threading

    service = DataCatalogService.open(seeded, lazy=True, sweep_temp=False)
    try:
        warmer = threading.Thread(target=service.warm_document)
        warmer.start()
        # Queries complete while warmup runs (or instantly after on fast
        # machines); they must be CORRECT either way.
        total = service.count_assets()
        assert total == N
        page = service.search_assets_page(limit=10)
        assert len(page) == 10
        warmer.join(timeout=60)
        assert service.is_warm is True
        assert service.count_assets() == N
    finally:
        service.close()


def test_mutation_and_conflict_at_scale(seeded):
    service = DataCatalogService.open(seeded, lazy=True, sweep_temp=False)
    try:
        first = service.list_assets()[0]
        _budget_ms(lambda: service.add_tag("v6", asset_id=first.id), 100.0)
        service.close()

        # Concurrent-write conflict at scale still refuses (CAS).
        a = DataCatalogService.open(seeded)
        b = DataCatalogService.open(seeded)
        try:
            a.add_tag("from-a", asset_id=first.id)
            b._index.revision = lambda: b._flushed_revision  # window sim
            import pytest as _pytest

            with _pytest.raises(CatalogStaleWriteError):
                b.add_tag("from-b", asset_id=first.id)
        finally:
            a.close()
            b.close()
    finally:
        if service._index.db_path:
            service.close()
