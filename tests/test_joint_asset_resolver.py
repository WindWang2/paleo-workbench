"""Hybrid joint asset resolver (#59)."""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.viz.joint_asset_resolver import resolve_joint_assets


def test_resolve_from_data_layout(tmp_path: Path):
    data = tmp_path / "data"
    (data / "地震体").mkdir(parents=True)
    (data / "井位").mkdir()
    segy = data / "地震体" / "cube.sgy"
    segy.write_bytes(b"x")
    wh = data / "井位" / "ExportWellHead.dat"
    wh.write_text("#\nA1 1 2 0 100 1 2 0\n")
    paths = resolve_joint_assets(None, data_root=data)
    assert paths.segy == segy
    assert paths.well_head == wh
    assert paths.source == "data"
    assert paths.has_minimum()


def test_project_resources_prefer_over_data(tmp_path: Path):
    data = tmp_path / "data"
    (data / "地震体").mkdir(parents=True)
    (data / "地震体" / "demo.sgy").write_bytes(b"d")
    proj_segy = tmp_path / "project_cube.sgy"
    proj_segy.write_bytes(b"p")
    project = ProjectDocument.new("t")
    project.resources.append(
        ResourceItem(name="cube", path=str(proj_segy), type="seismic", format="sgy")
    )
    paths = resolve_joint_assets(project, data_root=data)
    assert paths.segy == proj_segy
    assert paths.source in {"project", "mixed"}


def test_well_head_asset_identity_uses_project_resource_id(tmp_path: Path):
    well_head = tmp_path / "one" / "ExportWellHead.dat"
    well_head.parent.mkdir()
    well_head.write_text("A 1 2 3 4 5 6\n", encoding="utf-8")
    project = ProjectDocument.new("t")
    project.resources.append(
        ResourceItem(
            id="res:stable-wells",
            name="ExportWellHead.dat",
            path=str(well_head),
            type="well_head",
            format="dat",
        )
    )

    paths = resolve_joint_assets(project)

    assert paths.well_head == well_head
    assert paths.well_head_asset_id == "res:stable-wells"


def test_path_hints_override_when_files_exist(tmp_path: Path):
    from paleo_workbench.project.models import JointAnalysisState

    data = tmp_path / "data"
    (data / "地震体").mkdir(parents=True)
    demo = data / "地震体" / "demo.sgy"
    demo.write_bytes(b"d")
    hinted = tmp_path / "hinted.sgy"
    hinted.write_bytes(b"h")
    project = ProjectDocument.new("t")
    project.joint_analysis = JointAnalysisState(path_hints={"segy": str(hinted)})
    paths = resolve_joint_assets(project, data_root=data)
    assert paths.segy == hinted


def test_las_name_containing_td_stays_in_las_slot(tmp_path: Path):
    """#666: substring 'td' must not steal a LAS file (e.g. STD-1.las)."""
    las = tmp_path / "STD-1.las"
    las.write_text("~A\n", encoding="utf-8")
    project = ProjectDocument.new("t")
    project.resources.append(
        ResourceItem(name="STD-1.las", path=str(las), type="well_log", format="las")
    )
    paths = resolve_joint_assets(project)
    assert las in paths.las_files
    assert paths.td_dir is None


def test_las_under_wellhead_dir_is_not_well_head(tmp_path: Path):
    """#666: path containing 井位 must not reclassify a LAS as the well head."""
    las = tmp_path / "井位" / "A1.las"
    las.parent.mkdir()
    las.write_text("~A\n", encoding="utf-8")
    wh = tmp_path / "ExportWellHead.dat"
    wh.write_text("A 1 2 3 4 5 6\n", encoding="utf-8")
    project = ProjectDocument.new("t")
    project.resources.extend(
        [
            ResourceItem(name="A1.las", path=str(las), type="well_log", format="las"),
            ResourceItem(
                name="ExportWellHead.dat",
                path=str(wh),
                type="well_head",
                format="dat",
            ),
        ]
    )
    paths = resolve_joint_assets(project)
    assert paths.well_head == wh
    assert las in paths.las_files
