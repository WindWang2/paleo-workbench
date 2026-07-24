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
