from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel

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


def test_data_page_selection_renders_imported_text_preview(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    text_path = tmp_path / "notes.txt"
    text_path.write_text("alpha\nbeta\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([text_path])

    page.asset_table.table.selectRow(0)

    labels = "\n".join(
        label.text() for label in page.detail_panel.findChildren(QLabel)
    )
    assert "alpha" in labels
    assert "beta" in labels


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

    pixmap_labels = [
        label for label in page.detail_panel.findChildren(QLabel)
        if label.pixmap() is not None and not label.pixmap().isNull()
    ]
    assert pixmap_labels


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

    pixmap_labels = [
        label for label in page.detail_panel.findChildren(QLabel)
        if label.objectName() == "DataPreviewPdf"
        and label.pixmap() is not None
        and not label.pixmap().isNull()
    ]
    assert pixmap_labels
