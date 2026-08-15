"""Stable source identity for imported joint wells."""

from __future__ import annotations

from dataclasses import replace

import pytest

from paleo_workbench.viz.joint_well_identity import (
    WellIdentityAmbiguityError,
    WellIdentityRegistry,
)
from paleo_workbench.viz.joint_well_parsers import parse_well_heads


def _parse(source, registry):
    result = parse_well_heads(source, identity_registry=registry)
    return result.wells, result.identity_registry


def test_imported_well_ids_survive_data_edits_and_in_memory_reordering(tmp_path):
    source = tmp_path / "ExportWellHead.dat"
    source.write_text(
        "\n".join(
            [
                "DUP 100 200 10 1000 110 210",
                "DUP 100 200 10 1000 110 210",
            ]
        ),
        encoding="utf-8",
    )

    registry = WellIdentityRegistry(asset_id="res:wells", entries={})
    first_load, registry = _parse(source, registry)
    original_ids = [well.id for well in first_load]

    reordered = [
        replace(
            first_load[1],
            name="DISPLAY B",
            x=102,
            y=202,
            total_depth_m=1002,
        ),
        replace(
            first_load[0],
            name="DISPLAY A",
            x=101,
            y=201,
            total_depth_m=1001,
        ),
    ]

    assert original_ids[0] is not None
    assert original_ids[1] is not None
    assert original_ids[0] != original_ids[1]
    assert [well.id for well in reordered] == original_ids[::-1]


def test_identity_map_survives_source_insert_remove_reorder_and_geometry_edit(
    tmp_path,
):
    source = tmp_path / "ExportWellHead.dat"
    registry = WellIdentityRegistry(asset_id="res:wells", entries={})
    source.write_text(
        "A 1 2 3 4 5 6\nB 11 12 13 14 15 16\n",
        encoding="utf-8",
    )
    first, registry = _parse(source, registry)
    ids = {well.name: well.id for well in first}

    source.write_text(
        "NEW 21 22 23 24 25 26\nB 111 112 113 114 115 116\n"
        "A 101 102 103 104 105 106\n",
        encoding="utf-8",
    )
    inserted, registry = _parse(source, registry)

    assert {well.name: well.id for well in inserted} == {
        "NEW": inserted[0].id,
        "B": ids["B"],
        "A": ids["A"],
    }
    assert inserted[0].id not in ids.values()

    source.write_text(
        "A 101 102 103 104 105 106\nB 111 112 113 114 115 116\n",
        encoding="utf-8",
    )
    removed, registry = _parse(source, registry)

    assert {well.name: well.id for well in removed} == ids
    assert len(registry.entries) == 2


def test_identity_map_keeps_existing_well_when_same_name_well_is_added(
    tmp_path,
):
    source = tmp_path / "ExportWellHead.dat"
    registry = WellIdentityRegistry(asset_id="res:wells", entries={})
    source.write_text("A 1 2 3 4 5 6\n", encoding="utf-8")
    original, registry = _parse(source, registry)
    original_id = original[0].id

    source.write_text(
        "A 1 2 3 4 5 6\nA 11 12 13 14 15 16\n",
        encoding="utf-8",
    )
    expanded, registry = _parse(source, registry)
    source.write_text(
        "A 11 12 13 14 15 16\nA 1 2 3 4 5 6\n",
        encoding="utf-8",
    )
    reordered, registry = _parse(source, registry)

    assert expanded[0].id == original_id
    assert expanded[1].id != original_id
    assert [well.id for well in reordered] == [
        expanded[1].id,
        expanded[0].id,
    ]


def test_identity_registry_migrates_source_rename_by_geometry(tmp_path):
    source = tmp_path / "ExportWellHead.dat"
    registry = WellIdentityRegistry(asset_id="res:wells", entries={})
    source.write_text("A 1 2 3 4 5 6\n", encoding="utf-8")
    original, registry = _parse(source, registry)

    source.write_text("RENAMED 1 2 3 4 5 6\n", encoding="utf-8")
    renamed, registry = _parse(source, registry)

    assert renamed[0].id == original[0].id


def test_identity_registry_rejects_ambiguous_duplicate_corrections(tmp_path):
    source = tmp_path / "ExportWellHead.dat"
    registry = WellIdentityRegistry(asset_id="res:wells", entries={})
    source.write_text(
        "A 1 2 3 4 5 6\nA 11 12 13 14 15 16\n",
        encoding="utf-8",
    )
    _, registry = _parse(source, registry)

    source.write_text(
        "A 101 102 103 104 105 106\nA 111 112 113 114 115 116\n",
        encoding="utf-8",
    )

    with pytest.raises(WellIdentityAmbiguityError):
        _parse(source, registry)


def test_identity_registry_rejects_cross_name_geometry_ambiguity(tmp_path):
    source = tmp_path / "ExportWellHead.dat"
    registry = WellIdentityRegistry(asset_id="res:wells", entries={})
    source.write_text(
        "A 1 2 3 4 5 6\nB 11 12 13 14 15 16\n",
        encoding="utf-8",
    )
    _, registry = _parse(source, registry)

    source.write_text(
        "A 11 12 13 14 15 16\n",
        encoding="utf-8",
    )

    with pytest.raises(WellIdentityAmbiguityError):
        _parse(source, registry)


# ---------------------------------------------------------------------------
# #430 — TD comment lines must not hijack the well name, and load_td_tables
# must surface duplicate keys instead of silently overwriting them.
# ---------------------------------------------------------------------------

import warnings

from paleo_workbench.viz.joint_well_parsers import load_td_tables, parse_td_table

_TD_ROWS = "0 1000.0 1000.0 1500.0\n1000 1100.0 1100.0 1600.0\n"


def _write_td(tmp_path, stem, header):
    p = tmp_path / f"{stem}.dat"
    p.write_text(f"{header}\n{_TD_ROWS}", encoding="utf-8")
    return p


def test_430_unnamed_well_comment_falls_back_to_stem(tmp_path):
    tbl = parse_td_table(_write_td(tmp_path, "w1", "# Well :"))
    assert tbl is not None
    assert tbl.well_name == "w1"


def test_430_label_comment_does_not_hijack_well_name(tmp_path):
    tbl = parse_td_table(_write_td(tmp_path, "w1", "# Well label: check"))
    assert tbl is not None
    assert tbl.well_name == "w1"


def test_430_named_well_comment_still_wins(tmp_path):
    tbl = parse_td_table(_write_td(tmp_path, "w1", "# Well : W1"))
    assert tbl is not None
    assert tbl.well_name == "W1"


def test_430_duplicate_key_warns_and_keeps_first_table(tmp_path):
    # File A parses to well name "B" (its stem is "A"); file B has stem "B".
    # The key "B" is claimed by both — the old code silently overwrote it.
    _write_td(tmp_path, "A", "# Well : B")
    p_b = tmp_path / "B.dat"
    p_b.write_text("# Well : B2\n0 1000.0 1000.0 2000.0\n1000 1100.0 1100.0 2100.0\n", encoding="utf-8")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        tables = load_td_tables(tmp_path)
    assert any("冲突" in str(w.message) for w in caught)
    # Key "B" maps to the first sorted file (A.dat, well "B"), not B.dat.
    assert tables["B"].well_name == "B"
    assert tables["B"].md_m[0] == 1500.0
    # Both tables remain reachable through their unique keys.
    assert tables["A"].well_name == "B"
    assert tables["B2"].well_name == "B2"
    assert tables["B2"].md_m[0] == 2000.0
