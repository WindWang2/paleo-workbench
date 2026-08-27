"""Differential-equivalence harness for AssetTableModel (#1061, parent #1060).

Invariant under test: applying successive asset-list generations to ONE model
(the incremental entry point) yields exactly the same observable state as
rebuilding a fresh model from the final list — row counts, row→asset mapping,
per-cell display text, filter projection and sort order.

Until the incremental path exists (#1063) both sides execute the same full
rebuild, so these tests double as a self-check that the harness reports no
false positives. Once #1063 lands, the same assertions become its acceptance
net: any divergence between incremental application and full rebuild fails
here.
"""

from __future__ import annotations

import random

import pytest

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.asset_table_model import AssetTableModel
from paleo_workbench.ui.pages.data_table_columns import DEFAULT_COLUMN_KEYS

# Column keys exercising every display formatting branch cheaply.
_COMPARED_COLUMNS = [
    key for key in DEFAULT_COLUMN_KEYS
    if key in {"name", "type", "stage", "version", "tags", "modified", "lineage", "integrity"}
]


def _resource(i: int, **overrides) -> ResourceItem:
    payload = dict(
        id=f"res_{i:05d}",
        name=f"井-{i:05d}",
        path=f"wells/well_{i:05d}.las",
        type="well_log",
        format="las",
        tags=[f"tag_{i % 7}"],
    )
    payload.update(overrides)
    return ResourceItem(**payload)


def _initial_assets(rng: random.Random, count: int) -> list[ResourceItem]:
    return [_resource(i) for i in range(count)]


def _next_generation(
    rng: random.Random, assets: list[ResourceItem]
) -> list[ResourceItem]:
    """One refresh cycle: mutate a slice, add, remove, reorder.

    Updated rows are NEW objects carrying an existing id (content change);
    untouched rows keep the very same object so identity-based reuse has a
    fast path to cover.
    """
    next_assets = list(assets)
    # 1. Content changes on ~15% of rows (new object, same id, new name).
    for idx in rng.sample(range(len(next_assets)), k=max(1, len(next_assets) // 7)):
        old = next_assets[idx]
        next_assets[idx] = _resource(int(old.id.split("_")[1]), name=f"井-改-{old.id}")
    # 2. Add a few brand-new assets.
    max_id = max((int(a.id.split("_")[1]) for a in next_assets), default=0)
    next_assets.extend(_resource(max_id + k + 1) for k in range(rng.randint(1, 5)))
    # 3. Remove a few (never more than half).
    for _ in range(rng.randint(0, 4)):
        if len(next_assets) > 8:
            next_assets.pop(rng.randrange(len(next_assets)))
    # 4. Reorder (refreshes commonly observe shuffled lists).
    rng.shuffle(next_assets)
    return next_assets


def _state_snapshot(model: AssetTableModel) -> dict:
    """Full observable state: row→asset-id order plus every compared cell."""
    rows = []
    for row in range(model.rowCount()):
        asset = model.asset_at(row)
        view = model.view_at(row)
        cells = {}
        for col, key in enumerate(_COMPARED_COLUMNS):
            cells[key] = model.data(model.index(row, col))
        rows.append((getattr(asset, "id", None), getattr(view, "id", None), cells))
    return {"row_count": model.rowCount(), "rows": rows}


def _drive_terminal_ops(model: AssetTableModel, assets: list) -> None:
    """Apply the same explicit user operations to both models.

    A deterministic filter (ids whose last digit is even) followed by a sort
    on the first compared column normalizes any internal ordering policy, so
    the comparison isolates content-and-mapping equivalence.
    """
    keep = [i for i, a in enumerate(assets) if int(a.id.split("_")[1]) % 2 == 0]
    model.set_filtered_rows(keep)
    model.sort(0)  # name column, ascending


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 7])
def test_incremental_application_equivalent_to_full_rebuild(qtbot, seed) -> None:
    rng = random.Random(seed)
    generations = [_initial_assets(rng, rng.randint(24, 96))]
    for _ in range(4):
        generations.append(_next_generation(rng, generations[-1]))

    incremental = AssetTableModel()
    incremental.set_column_keys(list(_COMPARED_COLUMNS))
    for gen in generations:
        incremental.set_assets(gen)

    fresh = AssetTableModel()
    fresh.set_column_keys(list(_COMPARED_COLUMNS))
    fresh.set_assets(generations[-1])

    _drive_terminal_ops(incremental, generations[-1])
    _drive_terminal_ops(fresh, generations[-1])

    assert _state_snapshot(incremental) == _state_snapshot(fresh)


@pytest.mark.parametrize("seed", [11, 12])
def test_no_change_reapplication_is_stable(qtbot, seed) -> None:
    """Re-applying the identical list (same objects) changes nothing."""
    rng = random.Random(seed)
    assets = _initial_assets(rng, 40)
    model = AssetTableModel()
    model.set_column_keys(list(_COMPARED_COLUMNS))
    model.set_assets(assets)
    _drive_terminal_ops(model, assets)
    before = _state_snapshot(model)

    for _ in range(3):
        model.set_assets(list(assets))  # same objects, fresh list instance
    _drive_terminal_ops(model, assets)

    assert _state_snapshot(model) == before


def test_empty_and_single_asset_generations(qtbot) -> None:
    """Degenerate generations: empty list, then one asset, back to empty."""
    rng = random.Random(99)
    model = AssetTableModel()
    model.set_column_keys(list(_COMPARED_COLUMNS))
    model.set_assets([])
    assert model.rowCount() == 0

    lone = [_initial_assets(rng, 1)[0]]
    model.set_assets(lone)
    assert model.rowCount() == 1
    assert model.asset_at(0).id == lone[0].id

    model.set_assets([])
    assert model.rowCount() == 0
    assert model.asset_at(0) is None


# -- interaction-state continuity (#1064) -----------------------------------


def _visible_names(model: AssetTableModel) -> list[str]:
    return [model.view_at(r).name for r in range(model.rowCount())]


def test_user_sort_survives_incremental_refresh(qtbot) -> None:
    """After a refresh the visible order stays sorted by the user's last
    sort — no re-click on the header needed (#1064)."""
    rng = random.Random(5)
    model = AssetTableModel()
    model.set_column_keys(list(_COMPARED_COLUMNS))
    assets = _initial_assets(rng, 50)
    rng.shuffle(assets)
    model.set_assets(assets)
    model.sort(0)  # name, ascending
    assert _visible_names(model) == sorted(_visible_names(model))

    next_gen = _next_generation(rng, assets)
    model.set_assets(next_gen)
    names = _visible_names(model)
    assert names == sorted(names), "refresh must keep the user's sort order"
    assert model.last_sort is not None, "sort memory must survive the refresh"


def test_filter_change_keeps_last_sort(qtbot) -> None:
    """A filter change re-projects rows without losing the sort order."""
    rng = random.Random(6)
    model = AssetTableModel()
    model.set_column_keys(list(_COMPARED_COLUMNS))
    assets = _initial_assets(rng, 40)
    model.set_assets(assets)
    model.sort(0)
    keep = [i for i, a in enumerate(assets) if int(a.id.split("_")[1]) % 3 == 0]
    model.set_filtered_rows(keep)
    names = _visible_names(model)
    assert names == sorted(names)
    assert model.rowCount() == len(keep)


def test_view_objects_are_reused_for_identical_assets(qtbot) -> None:
    """The incremental path recycles AssetView instances, not just results."""
    rng = random.Random(7)
    model = AssetTableModel()
    model.set_column_keys(list(_COMPARED_COLUMNS))
    assets = _initial_assets(rng, 30)
    model.set_assets(assets)
    views_before = {a.id: model.view_at(i) for i, a in enumerate(assets)}

    model.set_assets(list(assets))  # same objects, new list instance
    views_after = {a.id: model.view_at(i) for i, a in enumerate(assets)}
    assert views_after == views_before, "identical objects must keep their views"

    # A replaced object (same id, new instance) must get a fresh view.
    replaced = list(assets)
    replaced[0] = _resource(int(assets[0].id.split("_")[1]), name="井-替换")
    model.set_assets(replaced)
    fresh_id = replaced[0].id
    assert model.view_at(0) is not views_before[fresh_id] or model.asset_at(0) is not assets[0]
    new_view = next(
        model.view_at(i) for i in range(model.rowCount()) if model.asset_at(i) is replaced[0]
    )
    assert new_view is not views_before[fresh_id]
