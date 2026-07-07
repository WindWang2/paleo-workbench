from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QSplitter

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel


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
    assert page.content_splitter.indexOf(page.catalog_panel) == 0
    assert page.content_splitter.indexOf(page.asset_table) == 1
    assert page.content_splitter.indexOf(page.reader_panel) == 2
    assert page.reader_panel.minimumWidth() == 320


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
    assert page.reader_panel.pdf_image.pixmap() is not None
    assert not page.reader_panel.pdf_image.pixmap().isNull()


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
