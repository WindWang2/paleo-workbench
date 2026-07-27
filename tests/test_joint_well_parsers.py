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

    first_load = parse_well_heads(source)
    original_ids = [well.id for well in first_load]

    source.write_text(
        "\n".join(
            [
                "RENAMED 101 201 11 1001 111 211",
                "DUP 102 202 12 1002 112 212",
            ]
        ),
        encoding="utf-8",
    )
    reloaded = parse_well_heads(source)
    reordered = [
        replace(reloaded[1], name="DISPLAY B"),
        replace(reloaded[0], name="DISPLAY A"),
    ]

    assert original_ids[0] is not None
    assert original_ids[1] is not None
    assert original_ids[0] != original_ids[1]
    assert [well.id for well in reloaded] == original_ids
    assert [well.id for well in reordered] == original_ids[::-1]
