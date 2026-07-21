"""Tests for well-tops workflow helpers in stratigraphy_correlation."""
from __future__ import annotations

from pathlib import Path

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.workflow.stratigraphy_correlation import (
    load_well_tops,
    match_tops_to_wells,
    tops_to_intervals,
)

DAT = (
    "#WellTops File From SMI\n"
    "A1 C1 1164.0 0 0 0 1164.0 0\n"
    "A1 X 850.0 0 0 0 850.0 0\n"
    "A2 C1 1200.0 0 0 0 1200.0 0\n"
    "GHOST C1 1300.0 0 0 0 1300.0 0\n"
)


def _project_with_dat(tmp_path: Path) -> ProjectDocument:
    path = tmp_path / "DC.dat"
    path.write_text(DAT, encoding="utf-8")
    project = ProjectDocument.new("T")
    project.resources.append(
        ResourceItem(name="DC.dat", path=str(path), type="well_stratification", format="dat")
    )
    return project


def test_load_well_tops_groups_and_sorts(tmp_path: Path):
    project = _project_with_dat(tmp_path)
    tops, warnings = load_well_tops(project)
    assert warnings == []
    assert set(tops) == {"A1", "A2", "GHOST"}
    # Sorted by depth: X(850) before C1(1164)
    assert tops["A1"] == [("X", 850.0), ("C1", 1164.0)]


def test_load_well_tops_missing_file_warns():
    project = ProjectDocument.new("T")
    project.resources.append(
        ResourceItem(name="gone.dat", path="/no/such/gone.dat", type="well_stratification", format="dat")
    )
    tops, warnings = load_well_tops(project)
    assert tops == {}
    assert len(warnings) == 1


def test_match_tops_to_wells_exact_and_case_insensitive():
    tops_by_well = {"A1": [("X", 850.0)], "a2": [("C1", 1200.0)], "GHOST": [("C1", 1.0)]}
    matched, unmatched = match_tops_to_wells(tops_by_well, ["A1", "A2"])
    assert set(matched) == {"A1", "A2"}
    assert matched["A2"] == [("C1", 1200.0)]
    assert unmatched == ["GHOST"]


def test_tops_to_intervals_spans_and_last_thickness():
    intervals = tops_to_intervals([("X", 850.0), ("C1", 1164.0), ("D1", 1482.0)])
    assert [(iv.top, iv.bottom, iv.name) for iv in intervals] == [
        (850.0, 1164.0, "X"),
        (1164.0, 1482.0, "C1"),
        (1482.0, 1800.0, "D1"),  # last reuses previous thickness (318.0)
    ]


def test_tops_to_intervals_single_top_default_thickness():
    intervals = tops_to_intervals([("X", 850.0)])
    assert [(iv.top, iv.bottom, iv.name) for iv in intervals] == [(850.0, 860.0, "X")]
