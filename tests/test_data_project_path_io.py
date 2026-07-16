"""T-DATA-02: DataPage import/export/rescan honor project_path."""

from __future__ import annotations

from pathlib import Path

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.resources.import_service import import_files
from paleo_workbench.ui.pages.data_page import DataPage


def test_import_with_project_path_relativizes_in_project_tree(tmp_path: Path):
    project_file = tmp_path / "demo.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    data_dir = tmp_path / "wells"
    data_dir.mkdir()
    las = data_dir / "a.las"
    las.write_text("~V\n~W\n~C\nDEPT.M:\n~A\n0\n1\n", encoding="utf-8")

    report = import_files([las], [], project_path=project_file)
    assert report.added_count == 1
    # Path stored relative to project dir.
    assert not Path(report.added[0].path).is_absolute()
    assert report.added[0].path.startswith("wells/")
    assert report.added[0].external is False


def test_data_page_set_project_path_and_resolve(qtbot, tmp_path: Path):
    project_file = tmp_path / "p.paleo.json"
    project_file.write_text("{}", encoding="utf-8")
    las = tmp_path / "w.las"
    las.write_text("~V\n", encoding="utf-8")

    page = DataPage(ProjectDocument.new("T"))
    qtbot.addWidget(page)
    page.set_project_path(project_file)
    assert page.project_path == project_file

    res = ResourceItem(
        name="w.las",
        path="w.las",
        type="well_log",
        format="las",
    )
    resolved = page._resolve_resource_path(res)
    assert resolved.resolve() == las.resolve()


def test_data_page_clear_project_path_on_unsaved(qtbot):
    page = DataPage(ProjectDocument.new("T"))
    qtbot.addWidget(page)
    page.set_project_path(".")
    assert page.project_path is None
    page.set_project_path(None)
    assert page.project_path is None
