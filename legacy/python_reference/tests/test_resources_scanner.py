from pathlib import Path

from paleo_workbench.resources.scanner import scan_resources


def test_resources_layer_imports_no_ui_modules():
    """#1055: paleo_workbench.resources must stay importable headless.

    A fresh subprocess import of the resources package (and every preview
    parser module) must not pull paleo_workbench.ui — the domain layer owns
    PreviewSettings; the UI layer imports it from here, never the reverse.
    """
    import subprocess
    import sys

    code = (
        "import sys\n"
        "import paleo_workbench.resources\n"
        "import paleo_workbench.resources.preview_parsers\n"
        "from paleo_workbench.resources import data_asset_registry\n"
        "leaked = sorted(\n"
        "    name for name in sys.modules\n"
        "    if name.startswith('paleo_workbench.ui')\n"
        ")\n"
        "assert not leaked, f'resources layer pulled UI modules: {leaked}'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_resources_source_has_no_ui_imports():
    """Static guard: no paleo_workbench.ui import in resources source text."""
    resources_dir = Path("paleo_workbench/resources")
    offenders = [
        str(path)
        for path in resources_dir.rglob("*.py")
        if "paleo_workbench.ui" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_scan_resources_recurses_and_records_metadata(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    well = data_dir / "well.las"
    well.write_bytes(b"~Version\n")
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
    well.write_bytes(b"~Version\n")

    resources = scan_resources(data_dir, project_path=project_path)

    assert resources[0].path == "data/well.las"
    assert resources[0].external is False
