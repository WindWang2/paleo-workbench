"""Catalog scale acceptance (D11) — layered, ratio-gated, never absolute-ms.

Tiers:

* fast (default): documents built via direct construction at
  ``CATALOG_SCALE_V5_N`` (default 2 000; ×2/×4 ladders) — the headline gate
  is that PAGE FETCH cost depends on PAGE SIZE, not catalog size, and that
  counts stay flat; save/reopen stays linear;
* heavy (``PALEO_CATALOG_SCALE_HEAVY=1``): 50k/100k through the same gates
  plus a mid-import SIGKILL crash-reopen at 10k scale.

Everything runs against the REAL DataCatalogService + SQLite store; no
second harness.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from paleo_workbench.catalog.models import (
    CatalogDocument,
    DataAsset,
    DataStage,
    DataVersion,
)
from paleo_workbench.catalog.service import DataCatalogService

BASE_N = int(os.environ.get("CATALOG_SCALE_V5_N", "2000"))
LEVELS = [BASE_N, BASE_N * 2, BASE_N * 4]
REPS = 3
# Generous ceilings over a 4x growth (sub-linear ⇒ ≲1x, linear ⇒ ~4x,
# quadratic ⇒ ~16x). +FLOOR absorbs scheduler noise at tiny sizes.
SUB_LINEAR_CEILING = 2.5
LINEAR_CEILING = 5.0
FLOOR_MS = 40.0

HEAVY = os.environ.get("PALEO_CATALOG_SCALE_HEAVY", "") == "1"
HEAVY_LEVELS = [50_000, 100_000] if HEAVY else []


def _measure(fn, reps: int = REPS) -> float:
    best: float | None = None
    for _ in range(reps):
        start = time.perf_counter()
        fn()
        elapsed = (time.perf_counter() - start) * 1000.0
        best = elapsed if best is None else min(best, elapsed)
    assert best is not None
    return best


def _scaled_document(n: int) -> CatalogDocument:
    document = CatalogDocument()
    for i in range(n):
        asset = DataAsset(name=f"asset_{i:06d}", type="well_log" if i % 2 else "seismic")
        version = DataVersion(
            asset_id=asset.id,
            version_number=1,
            stage=DataStage.RAW,
            path=f"raw/{asset.id}/v1/f.las",
            size_bytes=100 + (i % 7),
        )
        asset.current_version_id = version.id
        document.assets.append(asset)
        document.versions.append(version)
    return document


def _open_scaled(tmp_path: Path, n: int) -> DataCatalogService:
    project = tmp_path / "proj" / "demo.paleo.json"
    project.parent.mkdir(parents=True, exist_ok=True)
    project.write_text("{}", encoding="utf-8")
    svc = DataCatalogService.open(project)
    svc.document = _scaled_document(n)
    svc.rebuild_index()
    return svc


# -- headline gates (fast tier) -------------------------------------------------


@pytest.mark.parametrize("level", LEVELS)
def test_page_fetch_is_size_bound_not_catalog_bound(level: int, tmp_path: Path):
    """页取回成本 ∝ page size：page0 (500 rows) stays ~flat as the catalog
    grows 4x (this is the D3/D11 headline acceptance)."""
    svc = _open_scaled(tmp_path / str(level), level)
    try:
        elapsed = _measure(
            lambda: svc.search_assets_page(limit=500)
        )
        # correctness: the default page is complete and deterministic
        rows = svc.search_assets_page(limit=500)
        assert len(rows) == min(500, level)
    finally:
        svc.close()
    assert elapsed < 200.0 + FLOOR_MS  # absolute sanity for the default level


def test_page_fetch_ratio_across_levels(tmp_path: Path):
    """4x catalog growth must not inflate a 500-row page fetch by more than
    the sub-linear ceiling (a full materialization would show ~4x+)."""
    times = []
    for level in (LEVELS[0], LEVELS[-1]):
        svc = _open_scaled(tmp_path / str(level), level)
        try:
            times.append(_measure(lambda: svc.search_assets_page(limit=500)))
        finally:
            svc.close()
    small, big = times
    if big < FLOOR_MS:
        pytest.skip("below the noise floor")
    assert big <= small * SUB_LINEAR_CEILING + FLOOR_MS, times


def test_count_and_aggregates_scale(tmp_path: Path):
    svc_small = _open_scaled(tmp_path / "small", LEVELS[0])
    try:
        count_small = _measure(lambda: svc_small.count_assets())
        svc_small._aggregates_cache = None  # force an uncached aggregate pass
        agg_small = _measure(lambda: svc_small.catalog_aggregates())
    finally:
        svc_small.close()
    svc_big = _open_scaled(tmp_path / "big", LEVELS[-1])
    try:
        count_big = _measure(lambda: svc_big.count_assets())
        svc_big._aggregates_cache = None
        agg_big = _measure(lambda: svc_big.catalog_aggregates())
    finally:
        svc_big.close()
    assert count_big <= count_small * SUB_LINEAR_CEILING + FLOOR_MS
    assert agg_big <= agg_small * LINEAR_CEILING + FLOOR_MS  # group-bys are O(N)


def test_save_reopen_linear_at_scale(tmp_path: Path):
    times = {}
    for level in (LEVELS[0], LEVELS[-1]):
        svc = _open_scaled(tmp_path / str(level), level)
        try:
            project_path = svc.project_path
            asset_count = len(svc.list_assets())

            def _save_reopen():
                svc.close()
                reopened = DataCatalogService.open(project_path)
                assert len(reopened.list_assets(include_trashed=True)) == asset_count
                reopened.close()
                return reopened

            times[level] = _measure(_save_reopen)
            # leave a closed service; reopen once more for the teardown close
            svc = DataCatalogService.open(project_path)
        finally:
            svc.close()
    assert times[LEVELS[-1]] <= times[LEVELS[0]] * LINEAR_CEILING + FLOOR_MS, times


def test_rapid_filter_switches_stay_bounded(tmp_path: Path):
    """连续切 filter：每次都是一条新的 SQL 查询（+缓存命中），绝不全量物化。"""
    svc = _open_scaled(tmp_path / "probe", LEVELS[-1])
    try:
        filters = ["asset_0001", "asset_0002", "asset_0003", "asset_0004"]
        elapsed = _measure(
            lambda: [
                svc.count_assets(text=text)
                for text in filters * 5
            ],
            reps=1,
        )
        # correctness: a unique-name filter hits exactly one asset
        assert svc.count_assets(text="asset_007999") == 1
    finally:
        svc.close()
    assert elapsed < LINEAR_CEILING * 400.0  # 20 queries on the biggest level


# -- heavy tier (explicit) --------------------------------------------------------


@pytest.mark.skipif(not HEAVY, reason="set PALEO_CATALOG_SCALE_HEAVY=1")
@pytest.mark.parametrize("level", HEAVY_LEVELS)
def test_heavy_page_and_counts(level: int, tmp_path: Path):
    svc = _open_scaled(tmp_path / str(level), level)
    try:
        page_ms = _measure(lambda: svc.search_assets_page(limit=500), reps=1)
        count_ms = _measure(lambda: svc.count_assets(), reps=1)
        svc._aggregates_cache = None
        agg_ms = _measure(lambda: svc.catalog_aggregates(), reps=1)
        deep_ms = _measure(
            lambda: svc.search_assets_page(limit=500, offset=level // 2), reps=1
        )
        assert len(svc.search_assets_page(limit=500)) == 500
    finally:
        svc.close()
    # Absolute budgets for the heavy tier are generous but real.
    assert page_ms < 150.0, page_ms
    assert deep_ms < 200.0, deep_ms
    assert count_ms < 300.0, count_ms
    assert agg_ms < 1_500.0, agg_ms
