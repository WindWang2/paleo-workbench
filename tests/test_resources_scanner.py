from pathlib import Path

from paleo_workbench.resources.scanner import scan_resources


def test_scan_resources_recurses_and_records_metadata(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    well = data_dir / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    seismic = data_dir / "cube.sgy"
    seismic.write_bytes(b"segy")

    resources = scan_resources(data_dir)

    names = {resource.name for resource in resources}
    assert names == {"well.las", "cube.sgy"}
    well_resource = next(resource for resource in resources if resource.name == "well.las")
    assert well_resource.type == "well_log"
    assert well_resource.parsed_summary["size_bytes"] == len("~Version\n")
    assert well_resource.checksum is not None


def test_scan_resources_relativizes_project_paths(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    well = data_dir / "well.las"
    well.write_text("~Version\n", encoding="utf-8")

    resources = scan_resources(data_dir, project_path=project_path)

    assert resources[0].path == "data/well.las"
    assert resources[0].external is False
