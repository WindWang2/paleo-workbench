"""Regression tests for the P3 batch of the 2026-08-20 audit.

* #882 an unprobeable (over-long) resource path must degrade that one row to
  MISSING instead of raising ``OSError`` out of the whole data-page refresh.
* #883 the asset-table auto-fit guard must engage at the 1k-row catalog size it
  was introduced for.
* #884 tag normalization must fold Unicode so one visual tag is one tag.
"""

from __future__ import annotations

import time

import pytest

from paleo_workbench.catalog.models import normalize_tag_name
from paleo_workbench.project.models import ResourceItem
from paleo_workbench.ui.pages.data_view_models import (
    IntegrityState,
    asset_view_from_resource,
)

LONG_NAME = "A" * 255 + ".dat"


def _resource(name: str, path: str, rid: str = "r1") -> ResourceItem:
    return ResourceItem(id=rid, name=name, path=path, type="well_head", format="dat")


# --------------------------------------------------------------------------- #
# #882 — unprobeable paths


def test_overlong_path_degrades_to_missing_instead_of_raising() -> None:
    """``Path.exists()`` raises ENAMETOOLONG; the view must absorb it."""
    view = asset_view_from_resource(_resource(LONG_NAME, "/tmp/" + LONG_NAME))
    assert view.integrity_state is IntegrityState.MISSING
    assert view.size_bytes is None
    assert view.name == LONG_NAME, "the name must still be reported for display"


def test_one_unprobeable_row_does_not_break_the_others() -> None:
    """A single bad row must not deny the rest of the catalog a refresh."""
    rows = [
        _resource("good.dat", "/tmp/good.dat", rid="ok1"),
        _resource(LONG_NAME, "/tmp/" + LONG_NAME, rid="bad"),
        _resource("also_good.dat", "/tmp/also_good.dat", rid="ok2"),
    ]
    views = [asset_view_from_resource(r) for r in rows]
    assert len(views) == 3
    assert [v.name for v in views] == ["good.dat", LONG_NAME, "also_good.dat"]


# --------------------------------------------------------------------------- #
# #883 — auto-fit guard threshold


@pytest.mark.parametrize("n_rows", [1000, 1250, 2000])
def test_asset_table_auto_fit_guard_engages_at_and_above_1k_rows(
    qtbot, n_rows: int
) -> None:
    """1k rows must take the guarded fast path, not per-cell content measurement.

    The guard's budget is in cells while the table is 8 columns wide, so a
    10k-cell budget did not engage until ~1250 rows — leaving the exact size the
    guard was written for on the slow path (~400ms versus ~46ms guarded, #883).

    Asserted structurally rather than by wall-clock: the fast path sets every
    column to a fixed width, so column widths prove which branch ran. A timing
    assertion here would be flaky under parallel/loaded CI and would not say
    *why* it was slow.
    """
    from paleo_workbench.ui.pages.data_asset_table import DataAssetTable

    table = DataAssetTable()
    qtbot.addWidget(table)
    items = [
        _resource(f"asset_{i:05d}.dat", f"/tmp/asset_{i:05d}.dat", rid=f"r{i}")
        for i in range(n_rows)
    ]

    start = time.perf_counter()
    table.update_assets(items, [], project_root=None)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    cells = table.model.rowCount() * table.model.columnCount()
    assert table.model.rowCount() == n_rows
    assert cells > 4_000, (
        f"{n_rows} rows is {cells} cells; this test must sit above the budget "
        "to exercise the guarded path"
    )

    header = table.table.horizontalHeader()
    widths = {header.sectionSize(col) for col in range(header.count())}
    assert widths == {120}, (
        f"the auto-fit guard did not engage for {n_rows} rows ({cells} cells): "
        f"expected every column at the fixed 120px fast-path width, got {widths} "
        f"(refresh took {elapsed_ms:.1f}ms) (#883)"
    )


def test_asset_table_still_content_fits_small_tables(qtbot) -> None:
    """Below the budget, content fitting is cheap and must be preserved."""
    from paleo_workbench.ui.pages.data_asset_table import DataAssetTable

    table = DataAssetTable()
    qtbot.addWidget(table)
    items = [
        _resource(f"asset_{i:03d}.dat", f"/tmp/asset_{i:03d}.dat", rid=f"r{i}")
        for i in range(50)
    ]
    table.update_assets(items, [], project_root=None)

    cells = table.model.rowCount() * table.model.columnCount()
    assert cells <= 4_000, "this test must stay below the budget"

    header = table.table.horizontalHeader()
    widths = {header.sectionSize(col) for col in range(header.count())}
    assert widths != {120}, (
        "small tables must still be content-fitted, not forced to a fixed width"
    )


# --------------------------------------------------------------------------- #
# #884 — tag normalization


def test_nfd_and_nfc_spellings_are_one_tag() -> None:
    """Canonically equivalent accents must not create two tags."""
    nfc = "caf\u00e9"  # precomposed é
    nfd = "cafe\u0301"  # e + combining acute
    assert nfc != nfd
    assert normalize_tag_name(nfc) == normalize_tag_name(nfd)


def test_fullwidth_and_ascii_latin_are_one_tag() -> None:
    """CJK IMEs emit fullwidth Latin that looks like ASCII; fold it."""
    fullwidth = "\uff43\uff41\uff46\uff45"  # ｃａｆｅ
    assert normalize_tag_name(fullwidth) == normalize_tag_name("cafe")


def test_existing_normalization_behaviour_is_preserved() -> None:
    """Case folding, whitespace collapse and CJK passthrough must not regress."""
    assert normalize_tag_name("RAW") == normalize_tag_name("raw")
    assert normalize_tag_name("  a   b  ") == "a b"
    assert normalize_tag_name("\u4e95\u4f4d\u6570\u636e") == "\u4e95\u4f4d\u6570\u636e"


def test_normalization_is_idempotent() -> None:
    """A normalized key must survive re-normalization unchanged."""
    for raw in ["caf\u00e9", "cafe\u0301", "\uff43\uff41\uff46\uff45", " Mixed  Case "]:
        once = normalize_tag_name(raw)
        assert normalize_tag_name(once) == once
