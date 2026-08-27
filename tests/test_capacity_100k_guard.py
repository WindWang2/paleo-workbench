"""10万-scale capacity guard for the data-management refresh path (#1065).

Locks the incremental view-reuse budgets (#1063) and the no-growth memory
contract (#1062) into CI so capacity cannot silently regress. Budgets carry
generous headroom over local measurements (2026-08-27, 100k ResourceItems):

    initial set_assets ......... 2.8s   local   -> budget 20s
    no-change re-apply ......... 0.15s  local   -> budget  2s   (was 4.5-8.9s full rebuild)
    partial update (500 rows) .. 0.58s  local   -> budget  3s
    FilterIndex no-change ...... 0.12s  local   -> budget  2s   (was 3.8s full rebuild)
    RSS growth over refreshes .. +32MB one-time -> budget 120MB (CI noise margin)
"""

from __future__ import annotations

import resource
from pathlib import Path

import pytest

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.asset_table_model import AssetTableModel
from paleo_workbench.ui.pages.data_table_columns import DEFAULT_COLUMN_KEYS
from paleo_workbench.ui.pages.filter_index import FilterIndex

N_ASSETS = 100_000

_STATM = Path("/proc/self/statm")
_CAN_MEASURE_RSS = _STATM.is_file()


def _assets(count: int = N_ASSETS) -> list[ResourceItem]:
    return [
        ResourceItem(
            id=f"res_{i:06d}",
            name=f"well-{i:06d}",
            path=f"wells/well_{i:06d}.las",
            type="well_log",
            format="las",
            tags=[f"tag{i % 9}"],
        )
        for i in range(count)
    ]


def _current_rss_mb() -> float:
    return int(_STATM.read_text().split()[1]) * 4096 / 1048576.0


def _peak_rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0


def test_refresh_path_budgets_at_100k(qtbot) -> None:
    assets = _assets()
    model = AssetTableModel()
    model.set_column_keys(list(DEFAULT_COLUMN_KEYS))

    # First install legitimately builds every view — generous budget.
    import time

    t0 = time.perf_counter()
    model.set_assets(assets)
    initial = time.perf_counter() - t0
    assert initial < 20.0, f"initial set_assets took {initial:.1f}s at {N_ASSETS} assets (budget 20s)"

    # The capacity contract: an unchanged refresh must be cheap (#1063).
    t0 = time.perf_counter()
    model.set_assets(list(assets))
    unchanged = time.perf_counter() - t0
    assert unchanged < 2.0, f"no-change re-apply took {unchanged:.2f}s (budget 2s; full rebuild cost 4.5-8.9s)"

    # A small mixed delta stays near the no-change cost.
    mutated = list(assets)
    for idx in range(0, 1000, 2):
        i = int(mutated[idx].id.split("_")[1])
        mutated[idx] = ResourceItem(
            id=f"res_{i:06d}", name=f"well-{i:06d}-upd",
            path=f"wells/well_{i:06d}.las", type="well_log", format="las",
        )
    t0 = time.perf_counter()
    model.set_assets(mutated)
    partial = time.perf_counter() - t0
    assert partial < 3.0, f"partial update took {partial:.2f}s (budget 3s)"
    assert model.rowCount() == N_ASSETS

    # The host-side index shares the same reuse contract.
    index = FilterIndex()
    t0 = time.perf_counter()
    index.rebuild(mutated)
    index_initial = time.perf_counter() - t0
    assert index_initial < 25.0, f"initial FilterIndex.rebuild took {index_initial:.1f}s (budget 25s)"
    t0 = time.perf_counter()
    index.rebuild(list(mutated))
    index_reuse = time.perf_counter() - t0
    assert index_reuse < 2.0, f"no-change FilterIndex.rebuild took {index_reuse:.2f}s (budget 2s; full rebuild cost 3.8s)"


@pytest.mark.skipif(not _CAN_MEASURE_RSS, reason="/proc/self/statm unavailable (non-Linux)")
def test_repeated_refreshes_do_not_grow_memory(qtbot) -> None:
    assets = _assets()
    model = AssetTableModel()
    model.set_column_keys(list(DEFAULT_COLUMN_KEYS))
    model.set_assets(assets)

    import gc

    gc.collect()
    base = _current_rss_mb()
    for round_ in range(1, 4):
        mutated = list(assets)
        for idx in range(round_ * 50, round_ * 50 + 150):
            i = int(mutated[idx].id.split("_")[1])
            mutated[idx] = ResourceItem(
                id=f"res_{i:06d}", name=f"well-{i:06d}-r{round_}",
                path=f"wells/well_{i:06d}.las", type="well_log", format="las",
            )
        model.set_assets(mutated)
    gc.collect()
    growth = _current_rss_mb() - base
    assert growth < 120.0, (
        f"RSS grew {growth:.0f}MB over 3 refreshes (budget 120MB) — view reuse is leaking"
    )
    # Peak must stay in the same order as the working set, not double it.
    assert _peak_rss_mb() < _current_rss_mb() + 250.0, (
        "transient refresh peak far exceeds the working set — double residency is back"
    )
