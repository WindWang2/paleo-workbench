from pathlib import Path

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage


def test_data_page_assembles_management_panels(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    assert page.catalog_panel is not None
    assert page.asset_table is not None
    assert page.detail_panel is not None
    assert page.action_panel is not None


def test_data_page_update_state_delegates(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)
    state = {
        "resource_readiness": {
            "available_counts": {"well_log": 5, "seismic": 2, "horizon": 1},
            "missing_types": [],
            "ready": True,
        }
    }
    resources = [
        ResourceItem(
            name="test.xlsx",
            path="/tmp/test.xlsx",
            type="well_log",
            format="xlsx",
        ),
    ]
    page.update_state(state, resources)
    assert page.asset_table.table.rowCount() == 1
    assert "5" in page.summary_bar.type_labels["well_log"].text()


def test_data_page_has_action_buttons(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)
    assert page.import_btn is not None
    assert page.import_folder_btn is not None
    assert page.rescan_btn is not None
    assert page.remove_btn is not None
    assert page.import_btn.text() == "导入文件"
    assert page.import_folder_btn.text() == "导入目录"


def test_action_panel_exports_buttons(qtbot):
    from paleo_workbench.ui.pages.action_panel import ActionPanel

    panel = ActionPanel()
    qtbot.addWidget(panel)
    assert panel.objectName() == "ActionPanel"
    assert panel.import_btn.text() == "导入文件"
    assert panel.import_folder_btn.text() == "导入目录"
    assert panel.rescan_btn.text() == "重新扫描"
    assert panel.remove_btn.text() == "移出项目"


def test_data_page_object_name(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)
    assert page.objectName() == "DataPage"


def test_data_page_import_paths_updates_project_and_table(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)

    report = page.import_paths([well])

    assert report.added_count == 1
    assert len(project.resources) == 1
    assert page.asset_table.table.rowCount() == 1


def test_data_page_import_paths_skips_duplicate(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([well])

    report = page.import_paths([well])

    assert report.added_count == 0
    assert report.skipped_count == 1
    assert len(project.resources) == 1


def test_data_page_import_files_dialog_uses_selected_paths(
    qtbot,
    tmp_path: Path,
    monkeypatch,
):
    project = ProjectDocument.new("Demo")
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    monkeypatch.setattr(page, "_choose_import_files", lambda: [well])

    report = page.import_files_from_dialog()

    assert report.added_count == 1
    assert project.resources[0].name == "well.las"


def test_data_page_import_folder_dialog_uses_selected_folder(
    qtbot,
    tmp_path: Path,
    monkeypatch,
):
    project = ProjectDocument.new("Demo")
    folder = tmp_path / "folder"
    folder.mkdir()
    (folder / "cube.sgy").write_bytes(b"cube")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    monkeypatch.setattr(page, "_choose_import_folder", lambda: folder)

    report = page.import_folder_from_dialog()

    assert report.added_count == 1
    assert project.resources[0].name == "cube.sgy"
