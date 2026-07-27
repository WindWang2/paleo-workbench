"""Stable source identity for imported joint wells."""

from __future__ import annotations

from dataclasses import replace

from paleo_workbench.viz.joint_well_parsers import parse_well_heads


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

    identity_map: dict[str, str] = {}
    first_load = parse_well_heads(source, identity_map=identity_map)
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
    identity_map: dict[str, str] = {}
    source.write_text(
        "A 1 2 3 4 5 6\nB 11 12 13 14 15 16\n",
        encoding="utf-8",
    )
    first = parse_well_heads(source, identity_map=identity_map)
    ids = {well.name: well.id for well in first}

    source.write_text(
        "NEW 21 22 23 24 25 26\nB 111 112 113 114 115 116\n"
        "A 101 102 103 104 105 106\n",
        encoding="utf-8",
    )
    inserted = parse_well_heads(source, identity_map=identity_map)

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
    removed = parse_well_heads(source, identity_map=identity_map)

    assert {well.name: well.id for well in removed} == ids
    assert len(identity_map) == 2


def test_identity_map_keeps_existing_well_when_same_name_well_is_added(
    tmp_path,
):
    source = tmp_path / "ExportWellHead.dat"
    identity_map: dict[str, str] = {}
    source.write_text("A 1 2 3 4 5 6\n", encoding="utf-8")
    original_id = parse_well_heads(
        source, identity_map=identity_map
    )[0].id

    source.write_text(
        "A 1 2 3 4 5 6\nA 11 12 13 14 15 16\n",
        encoding="utf-8",
    )
    expanded = parse_well_heads(source, identity_map=identity_map)
    source.write_text(
        "A 11 12 13 14 15 16\nA 1 2 3 4 5 6\n",
        encoding="utf-8",
    )
    reordered = parse_well_heads(source, identity_map=identity_map)

    assert expanded[0].id == original_id
    assert expanded[1].id != original_id
    assert [well.id for well in reordered] == [
        expanded[1].id,
        expanded[0].id,
    ]
