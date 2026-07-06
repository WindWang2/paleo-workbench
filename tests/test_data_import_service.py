from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.import_service import import_files, import_folder


def test_import_files_adds_new_resources(tmp_path: Path):
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")

    report = import_files([well], existing=[])

    assert report.added_count == 1
    assert report.skipped_count == 0
    assert report.added[0].name == "well.las"
    assert report.added[0].type == "well_log"


def test_import_files_skips_duplicate_path(tmp_path: Path):
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    existing = [
        ResourceItem(
            name="well.las",
            path=well.resolve().as_posix(),
            type="well_log",
            format="las",
            checksum="existing",
        )
    ]

    report = import_files([well], existing=existing)

    assert report.added == []
    assert report.skipped_path == [well]
    assert report.skipped_count == 1


def test_import_files_skips_duplicate_checksum(tmp_path: Path):
    first = tmp_path / "first.las"
    second = tmp_path / "second.las"
    first.write_text("same", encoding="utf-8")
    second.write_text("same", encoding="utf-8")
    first_report = import_files([first], existing=[])

    second_report = import_files([second], existing=first_report.added)

    assert second_report.added == []
    assert second_report.skipped_checksum == [second]


def test_import_files_dedupes_relative_project_paths(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    well = tmp_path / "data" / "well.las"
    well.parent.mkdir()
    well.write_text("~Version\n", encoding="utf-8")
    existing = [
        ResourceItem(
            name="well.las",
            path="data/well.las",
            type="well_log",
            format="las",
            checksum="different",
        )
    ]

    report = import_files([well], existing=existing, project_path=project_path)

    assert report.added == []
    assert report.skipped_path == [Path("data/well.las")]


def test_import_folder_uses_recursive_scanner(tmp_path: Path):
    root = tmp_path / "folder"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (nested / "cube.sgy").write_bytes(b"cube")

    report = import_folder(root, existing=[])

    assert report.added_count == 1
    assert report.added[0].type == "seismic"
