from pathlib import Path

from paleo_workbench.project.models import ResourceItem
from paleo_workbench.resources.import_service import import_files, import_folder


def test_import_files_adds_new_resources(tmp_path: Path):
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8", newline="")

    report = import_files([well], existing=[])

    assert report.added_count == 1
    assert report.skipped_count == 0
    assert report.added[0].name == "well.las"
    assert report.added[0].type == "well_log"


def test_import_files_skips_duplicate_path(tmp_path: Path):
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8", newline="")
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


def test_import_files_never_opens_file_or_calculates_checksum(
    tmp_path: Path, monkeypatch
):
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8", newline="")

    def fail_open(*_args, **_kwargs):
        raise AssertionError("import must not open file content")

    monkeypatch.setattr(Path, "open", fail_open)
    report = import_files([well], existing=[])

    assert report.added_count == 1
    assert report.added[0].checksum is None
    # Import enriches summary with size/mtime/labels without deep-parsing LAS.
    assert report.added[0].parsed_summary.get("size_bytes") == len(b"~Version\n")
    assert "type_label" in report.added[0].parsed_summary


def test_import_files_processes_only_requested_paths(tmp_path: Path, monkeypatch):
    selected = tmp_path / "selected.las"
    unselected = tmp_path / "unselected.sgy"
    selected.write_text("~Version\n", encoding="utf-8")
    unselected.write_bytes(b"cube")

    def fail_rglob(*_args, **_kwargs):
        raise AssertionError("single-file import must not enumerate a directory")

    monkeypatch.setattr(Path, "rglob", fail_rglob)

    report = import_files([selected], existing=[])

    assert [resource.name for resource in report.added] == ["selected.las"]


def test_import_files_keeps_same_content_at_distinct_paths(tmp_path: Path):
    first = tmp_path / "first.las"
    second = tmp_path / "second.las"
    first.write_text("same", encoding="utf-8")
    second.write_text("same", encoding="utf-8")

    first_report = import_files([first], existing=[])
    second_report = import_files([second], existing=first_report.added)

    assert second_report.added_count == 1
    assert second_report.skipped_checksum == []


def test_import_files_dedupes_relative_project_paths(tmp_path: Path):
    project_path = tmp_path / "demo.paleo.json"
    well = tmp_path / "data" / "well.las"
    well.parent.mkdir()
    well.write_text("~Version\n", encoding="utf-8", newline="")
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


def test_import_folder_collects_recursively_by_initial_classification(tmp_path: Path):
    root = tmp_path / "folder"
    nested = root / "nested"
    nested.mkdir(parents=True)
    (nested / "cube.sgy").write_bytes(b"cube")
    horizon = nested / "层位" / "marker.dat"
    horizon.parent.mkdir()
    horizon.write_bytes(b"marker")

    report = import_folder(root, existing=[])
    by_name = {item.name: item for item in report.added}

    assert report.added_count == 2
    assert by_name["cube.sgy"].type == "seismic"
    assert by_name["marker.dat"].type == "horizon"
