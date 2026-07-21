"""Tests for the SMI WellTops (.dat) parser."""
from __future__ import annotations

from pathlib import Path

from paleo_workbench.resources.well_tops_parser import parse_well_tops

SAMPLE = (
    "#WellTops File From SMI\r\n"
    "#WellName    Name         MD           X            Y            Z            TVD          Time(ms)    \r\n"
    "A1           X            850.000      5288.670     8219.940     -850.000     850.000      -99999.000  \r\n"
    "A1           C1           1164.000     5288.670     8219.940     -1164.000    1164.000     -99999.000  \r\n"
    "A10          D21          1482.000     10499.930    11460.655    -1430.278    1430.278     -99999.000  \r\n"
)


def test_parse_basic_rows(tmp_path: Path):
    path = tmp_path / "DC.dat"
    path.write_text(SAMPLE, encoding="utf-8")
    tops = parse_well_tops(path)
    assert len(tops) == 3
    assert tops[0].well_name == "A1"
    assert tops[0].top_name == "X"
    assert tops[0].md == 850.0
    assert tops[0].tvd == 850.0
    assert tops[2].well_name == "A10"
    assert tops[2].tvd == 1430.278


def test_parse_skips_garbage_rows(tmp_path: Path):
    path = tmp_path / "bad.dat"
    path.write_text(
        "# comment\n\nshort row\nA1 BAD_DEPTH notanumber 1 2 3 4 5\nA1 C1 1164.0 0 0 0 1164.0 0\n",
        encoding="utf-8",
    )
    tops = parse_well_tops(path)
    assert len(tops) == 1
    assert tops[0].top_name == "C1"


def test_parse_missing_tvd_yields_none(tmp_path: Path):
    path = tmp_path / "short.dat"
    path.write_text("A1 C1 1164.0\n", encoding="utf-8")
    tops = parse_well_tops(path)
    assert len(tops) == 1
    assert tops[0].tvd is None


def test_parse_empty_file(tmp_path: Path):
    path = tmp_path / "empty.dat"
    path.write_text("# only comments\n", encoding="utf-8")
    assert parse_well_tops(path) == []
