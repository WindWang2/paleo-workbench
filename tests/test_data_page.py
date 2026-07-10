from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QSplitter

from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.resources.import_service import ImportReport
from paleo_workbench.ui.pages.data_asset_table import DEFAULT_COLUMN_KEYS
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.data_workspace import DataWorkspace


def _table_headers(page: DataPage) -> list[str]:
    return [
        page.asset_table.table.horizontalHeaderItem(i).text()
        for i in range(page.asset_table.table.columnCount())
    ]


def test_data_page_assembles_management_panels(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    assert page.catalog_panel is not None
    assert page.asset_table is not None
    assert page.reader_panel is not None
    assert page.action_panel is not None


def test_data_page_uses_resizable_content_splitter(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    assert isinstance(page.content_splitter, QSplitter)
    assert page.content_splitter.indexOf(page.asset_table) == 0
    assert page.content_splitter.indexOf(page.reader_panel) == 1
    assert page.content_splitter.indexOf(page.catalog_panel) == -1
    assert page.content_splitter.indexOf(page.action_panel) == -1
    assert page.reader_panel.minimumWidth() == 320


def test_data_page_uses_workspace_toolbar_and_floating_panels(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    assert isinstance(page.workspace, DataWorkspace)
    assert page.catalog_panel is page.workspace.catalog_panel
    assert page.action_panel is page.workspace.action_panel
    assert page.content_splitter.indexOf(page.asset_table) == 0
    assert page.content_splitter.indexOf(page.reader_panel) == 1
    assert page.content_splitter.indexOf(page.catalog_panel) == -1
    assert page.content_splitter.indexOf(page.action_panel) == -1


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


def test_data_page_has_column_settings_menu(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    assert page.column_settings_btn.text() == "列设置"
    assert page.column_settings_menu is not None
    assert set(page.column_actions) == {
        "name",
        "type",
        "format",
        "status",
        "role",
        "size",
        "source",
        "path",
    }


def test_data_page_column_settings_toggle_hides_column(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    page.column_actions["path"].trigger()

    assert "路径" not in _table_headers(page)
    assert "文件名" in _table_headers(page)
    assert page.column_actions["path"].isChecked() is False


def test_data_page_required_name_column_action_disabled(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    assert page.column_actions["name"].isEnabled() is False
    assert page.column_actions["name"].isChecked() is True
    page.column_actions["name"].trigger()
    assert _table_headers(page)[0] == "文件名"


def test_data_page_reset_columns_action_restores_defaults(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    page.column_actions["path"].trigger()
    page.reset_columns_action.trigger()

    assert _table_headers(page) == [
        "文件名",
        "类型",
        "格式",
        "状态",
        "角色",
        "大小",
        "来源",
        "路径",
    ]
    assert page.asset_table.visible_column_keys() == DEFAULT_COLUMN_KEYS


def test_data_page_column_change_preserves_selection_and_reader(qtbot, tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("alpha", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    project.resources.append(resource)
    page = DataPage(project=project)
    qtbot.addWidget(page)

    page._set_selected_asset(resource)
    page.column_actions["source"].trigger()
    page.column_actions["path"].trigger()

    assert page.reader_panel.current_mode == "text"
    assert page.asset_table.table.selectionModel().selectedRows()[0].row() == 0
    assert page._selected_asset == resource


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
    assert "新增 1" in page.action_panel.status_label.text()


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
    assert "重复 1" in page.action_panel.status_label.text()


def test_data_page_remove_selected_resource_unregisters_only(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([well])
    page.asset_table.table.selectRow(0)

    removed = page.remove_selected_asset()

    assert removed is True
    assert project.resources == []
    assert well.exists()
    assert page.asset_table.table.rowCount() == 0
    assert "已移出项目" in page.action_panel.status_label.text()


def test_data_page_rescan_selected_resource_marks_missing(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([well])
    page.asset_table.table.selectRow(0)
    well.unlink()

    rescanned = page.rescan_selected_asset()

    assert rescanned is True
    assert project.resources[0].status == "missing"
    assert "文件不存在" in page.action_panel.status_label.text()


def test_data_page_open_selected_folder_reports_path(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([well])
    page.asset_table.table.selectRow(0)

    folder = page.open_selected_folder()

    assert folder == tmp_path
    assert tmp_path.as_posix() in page.action_panel.status_label.text()


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


def test_data_page_starts_file_import_in_worker_thread(
    qtbot,
    tmp_path: Path,
    monkeypatch,
):
    project = ProjectDocument.new("Demo")
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    worker_threads = []

    def fake_import_files(paths, existing):
        worker_threads.append(QThread.currentThread())
        return ImportReport(
            added=[
                ResourceItem(
                    name=paths[0].name,
                    path=paths[0].as_posix(),
                    type="well_log",
                    format="las",
                )
            ]
        )

    monkeypatch.setattr(page, "_choose_import_files", lambda: [well])
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.data_page.import_files",
        fake_import_files,
    )

    with qtbot.waitSignal(page.import_finished, timeout=1000):
        started = page.begin_import_files_from_dialog()

    assert started is True
    assert worker_threads
    assert worker_threads[0] is not page.thread()
    assert project.resources[0].name == "well.las"
    assert "新增 1" in page.action_panel.status_label.text()


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


def test_data_page_starts_folder_import_in_worker_thread(
    qtbot,
    tmp_path: Path,
    monkeypatch,
):
    project = ProjectDocument.new("Demo")
    folder = tmp_path / "folder"
    folder.mkdir()
    cube = folder / "cube.sgy"
    cube.write_bytes(b"cube")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    worker_threads = []

    def fake_import_folder(path, existing):
        worker_threads.append(QThread.currentThread())
        return ImportReport(
            added=[
                ResourceItem(
                    name=cube.name,
                    path=cube.as_posix(),
                    type="seismic",
                    format="sgy",
                )
            ]
        )

    monkeypatch.setattr(page, "_choose_import_folder", lambda: folder)
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.data_page.import_folder",
        fake_import_folder,
    )

    with qtbot.waitSignal(page.import_finished, timeout=1000):
        started = page.begin_import_folder_from_dialog()

    assert started is True
    assert worker_threads
    assert worker_threads[0] is not page.thread()
    assert project.resources[0].name == "cube.sgy"
    assert "新增 1" in page.action_panel.status_label.text()


def test_data_page_selection_renders_imported_text_preview(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    text_path = tmp_path / "notes.txt"
    text_path.write_text("alpha\nbeta\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([text_path])

    page.asset_table.table.selectRow(0)

    assert page.reader_panel.current_mode == "text"
    assert "alpha" in page.reader_panel.text_preview.toPlainText()
    assert "beta" in page.reader_panel.text_preview.toPlainText()


def test_data_page_selection_renders_imported_image_preview(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    image_path = tmp_path / "map.png"
    image = QImage(8, 8, QImage.Format.Format_RGB32)
    image.fill(0x336699)
    image.save(image_path.as_posix())
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([image_path])

    page.asset_table.table.selectRow(0)

    assert page.reader_panel.current_mode == "image"
    assert page.reader_panel.image_label.pixmap() is not None
    assert not page.reader_panel.image_label.pixmap().isNull()


def test_data_page_selection_renders_imported_pdf_preview(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(
        b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT /F1 12 Tf 72 120 Td (Hello PDF) Tj ET
endstream
endobj
xref
0 5
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000202 00000 n
trailer
<< /Root 1 0 R /Size 5 >>
startxref
296
%%EOF
"""
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([pdf_path])

    page.asset_table.table.selectRow(0)

    assert page.reader_panel.current_mode == "pdf"
    assert page.reader_panel.stack.currentWidget() is page.reader_panel.pdf_widget
    assert page.reader_panel.pdf_image is page.reader_panel.pdf_widget.fallback_image
    assert page.reader_panel.pdf_page_label.text()


def test_data_page_uses_reader_panel(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    assert isinstance(page.reader_panel, DataReaderPanel)
    assert page.content_splitter.indexOf(page.reader_panel) >= 0


def test_data_page_selection_updates_reader_and_context_signal(qtbot, tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    project.resources.append(resource)
    page = DataPage(project=project)
    qtbot.addWidget(page)
    received = []
    page.data_context_changed.connect(received.append)

    page._set_selected_asset(resource)

    assert page.reader_panel.current_mode == "text"
    assert received[-1]["selected_name"] == "notes.txt"
    assert received[-1]["reader_mode"] == "text"


def test_data_page_remove_refreshes_reader_and_action_state(qtbot, tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    project.resources.append(resource)
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page._set_selected_asset(resource)

    assert page.remove_selected_asset() is True

    assert project.resources == []
    assert page.reader_panel.current_mode == "empty"
    assert page.remove_btn.isEnabled() is False


def test_data_page_filtering_hidden_selection_clears_reader_action_state_and_context(
    qtbot,
    tmp_path: Path,
):
    first = tmp_path / "alpha.txt"
    second = tmp_path / "beta.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    alpha = ResourceItem(
        name="alpha.txt",
        path=str(first),
        type="document",
        format="txt",
    )
    beta = ResourceItem(
        name="beta.txt",
        path=str(second),
        type="document",
        format="txt",
    )
    project.resources.extend([alpha, beta])
    page = DataPage(project=project)
    qtbot.addWidget(page)
    received = []
    page.data_context_changed.connect(received.append)

    page._set_selected_asset(alpha)
    page.asset_table.set_search_text("beta")

    assert page.reader_panel.current_mode == "empty"
    assert page.remove_btn.isEnabled() is False
    assert page.rescan_btn.isEnabled() is False
    assert page.action_panel.selection_status_label.text() == "等待选择"
    assert received[-1]["selected_name"] == "未选择"
    assert received[-1]["selected_type"] == ""
    assert received[-1]["selected_format"] == ""
    assert received[-1]["reader_mode"] == "empty"


def test_data_page_can_remove_selected_export_artifact(qtbot):
    project = ProjectDocument.new("Demo")
    artifact = ExportArtifact(
        linked_id="map_1",
        format="PDF",
        output_path="/tmp/map.pdf",
    )
    project.export_artifacts.append(artifact)
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page._set_selected_asset(artifact)

    removed = page.remove_selected_asset()

    assert removed is True
    assert project.export_artifacts == []
    assert page.reader_panel.current_mode == "empty"
    assert page.remove_btn.isEnabled() is False
    assert "已移出项目" in page.action_panel.operation_status_label.text()


def test_data_page_can_open_selected_export_artifact_folder(qtbot, monkeypatch, tmp_path: Path):
    output_dir = tmp_path / "exports"
    output_dir.mkdir()
    output_path = output_dir / "map.pdf"
    output_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    project = ProjectDocument.new("Demo")
    artifact = ExportArtifact(
        linked_id="map_1",
        format="PDF",
        output_path=str(output_path),
    )
    project.export_artifacts.append(artifact)
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page._set_selected_asset(artifact)
    opened = []
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.data_page.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    folder = page.open_selected_folder()

    assert folder == output_dir
    assert opened == [output_dir.as_posix()]
    assert output_dir.as_posix() in page.action_panel.operation_status_label.text()


def test_data_page_keeps_latest_operation_report_when_selection_changes(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)

    page.import_paths([path])

    assert "新增 1" in page.action_panel.operation_status_label.text()
    page.asset_table.table.selectRow(0)
    assert "新增 1" in page.action_panel.operation_status_label.text()


def test_data_page_rescan_emits_updated_context_after_reader_mode_changes(
    qtbot,
    monkeypatch,
    tmp_path: Path,
):
    path = tmp_path / "notes.txt"
    path.write_text("alpha", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    resource = ResourceItem(
        name="notes.txt",
        path=str(path),
        type="document",
        format="txt",
    )
    project.resources.append(resource)
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page._set_selected_asset(resource)
    received = []
    page.data_context_changed.connect(received.append)

    replacement = ResourceItem(
        id=resource.id,
        name="notes.txt",
        path=str(path),
        type="image_reference",
        format="png",
        status="indexed",
    )
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.data_page.scan_resources",
        lambda _folder: [replacement],
    )

    assert page.rescan_selected_asset() is True

    assert received[-1]["selected_name"] == "notes.txt"
    assert received[-1]["reader_mode"] == "image"
