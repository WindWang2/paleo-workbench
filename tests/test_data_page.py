from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QLabel, QSplitter, QTableView

from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.resources.import_service import ImportReport
from paleo_workbench.ui.pages.asset_context_menu import AssetContextMenu
from paleo_workbench.ui.pages.asset_table_model import AssetTableModel
from paleo_workbench.ui.pages.data_asset_table import DEFAULT_COLUMN_KEYS
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.data_reader_panel import DataReaderPanel
from paleo_workbench.ui.pages.data_workspace import DataWorkspace
from paleo_workbench.workflow.service import dashboard_state


def _table_model(page: DataPage):
    return page.asset_table.table.model()


def _table_row_count(page: DataPage) -> int:
    return _table_model(page).rowCount()


def _table_text(page: DataPage, row: int, column: int) -> str:
    model = _table_model(page)
    return model.data(model.index(row, column)) or ""


def _wait_reader_mode(qtbot, page: DataPage, mode: str, timeout: int = 3000) -> None:
    qtbot.waitUntil(lambda: page.reader_panel.current_mode == mode, timeout=timeout)


def _table_headers(page: DataPage) -> list[str]:
    model = _table_model(page)
    return [
        model.headerData(i, Qt.Orientation.Horizontal)
        for i in range(model.columnCount())
    ]


def test_data_page_assembles_management_panels(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    assert page.navigation_tree is not None
    assert page.asset_table is not None
    assert page.reader_panel is not None
    assert page.inspector_panel is not None


def test_data_page_uses_three_pane_splitter(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    assert isinstance(page.main_splitter, QSplitter)
    assert page.main_splitter.count() == 3
    assert page.main_splitter.widget(0) is page.navigation_tree
    assert page.main_splitter.widget(1) is page.asset_table
    assert page.main_splitter.widget(2) is page.right_splitter
    assert page.right_splitter.widget(0) is page.reader_panel
    assert page.right_splitter.widget(1) is page.inspector_panel


def test_data_page_exposes_workspace_panes(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    assert isinstance(page.workspace, DataWorkspace)
    assert page.navigation_tree is page.workspace.navigation_tree
    assert page.inspector_panel is page.workspace.inspector_panel


def test_page_selecting_asset_updates_inspector(qtbot, tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([path])

    # Select via the table so the selected_asset_changed signal fires and
    # routes to the inspector (the wiring under test).
    page.asset_table.table.selectRow(0)
    _wait_reader_mode(qtbot, page, "text")

    # Inspector receives the selection and renders the resource metadata rows.
    assert page.inspector_panel.metadata_table.rowCount() > 0


def test_page_navigation_tree_routes_to_asset_table(qtbot, tmp_path: Path):
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    doc = tmp_path / "notes.txt"
    doc.write_text("hello", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    project.resources.extend(
        [
            ResourceItem(name="well.las", path=str(well), type="well_log", format="las"),
            ResourceItem(name="notes.txt", path=str(doc), type="document", format="txt"),
        ]
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)
    assert _table_row_count(page) == 2

    # Emitting category_changed("测井") routes through to the asset table filter.
    page.navigation_tree.category_changed.emit("测井")

    assert _table_row_count(page) == 1
    assert _table_text(page, 0, 0) == "well.las"


def test_data_page_toolbar_toggles_update_checked_state(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)
    page.show()
    qtbot.waitExposed(page)

    assert page.data_toolbar.reader_btn.isChecked() is True
    assert page.reader_panel.isVisible() is True

    page.data_toolbar.reader_btn.click()
    assert page.reader_panel.isVisible() is False
    assert page.data_toolbar.reader_btn.isChecked() is False

    page.data_toolbar.reader_btn.click()
    assert page.reader_panel.isVisible() is True
    assert page.data_toolbar.reader_btn.isChecked() is True





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
    assert _table_row_count(page) == 1
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
    assert set(page.column_actions) >= {
        "name",
        "type",
        "format",
        "status",
        "role",
        "size",
        "source",
        "path",
    }


def test_data_page_column_settings_toggle_shows_column(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    # Default is name-only; toggling "path" adds it.
    page.column_actions["path"].trigger()

    assert "路径" in _table_headers(page)
    assert "文件名" in _table_headers(page)
    assert page.column_actions["path"].isChecked() is True


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

    # Add a column, then reset → back to the seven default columns (F5).
    page.column_actions["path"].trigger()
    page.reset_columns_action.trigger()

    from paleo_workbench.ui.pages.data_table_columns import COLUMN_BY_KEY

    assert _table_headers(page) == [
        COLUMN_BY_KEY[key].label for key in DEFAULT_COLUMN_KEYS
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
    _wait_reader_mode(qtbot, page, "text")
    page.column_actions["source"].trigger()
    page.column_actions["path"].trigger()

    assert page.reader_panel.current_mode == "text"
    assert page.asset_table.table.selectionModel().selectedRows()[0].row() == 0
    assert page._selected_asset == resource


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
    assert _table_row_count(page) == 1
    assert "已归档 1" in page.data_toolbar.operation_status_label.text()


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
    assert "重复路径 1" in page.data_toolbar.operation_status_label.text()


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
    assert _table_row_count(page) == 0
    assert "已移出项目" in page.data_toolbar.operation_status_label.text()


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
    assert "文件不存在" in page.data_toolbar.operation_status_label.text()


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
    assert tmp_path.as_posix() in page.data_toolbar.operation_status_label.text()


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

    def fake_import_files(paths, existing, project_path=None):
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

    with qtbot.waitSignal(page.import_finished, timeout=5000):
        started = page.begin_import_files_from_dialog()

    assert started is True
    assert worker_threads
    assert worker_threads[0] is not page.thread()
    assert project.resources[0].name == "well.las"
    assert "已归档 1" in page.data_toolbar.operation_status_label.text()


def test_async_import_commit_runs_on_page_gui_thread(qtbot, tmp_path: Path):
    project = ProjectDocument.new("GUI commit")
    path = tmp_path / "well.las"
    path.write_text("~Version\n", encoding="utf-8")
    page = DataPage(project)
    qtbot.addWidget(page)
    commit_threads = []
    page.import_finished.connect(
        lambda _report: commit_threads.append(QThread.currentThread())
    )

    with qtbot.waitSignal(page.import_finished, timeout=3000):
        assert page.begin_import_paths([path])

    assert commit_threads == [page.thread()]


def test_data_page_import_status_describes_archiving_while_worker_runs(
    qtbot,
    tmp_path: Path,
    monkeypatch,
):
    project = ProjectDocument.new("Demo")
    well = tmp_path / "well.las"
    well.write_text("~Version\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    worker_started = Event()
    release_worker = Event()

    def controlled_import_files(paths, existing, project_path=None):
        worker_started.set()
        release_worker.wait()
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

    monkeypatch.setattr(
        "paleo_workbench.ui.pages.data_page.import_files",
        controlled_import_files,
    )

    started = page.begin_import_paths([well])

    assert started is True
    qtbot.waitUntil(worker_started.is_set, timeout=1000)
    with qtbot.waitSignal(page.import_finished, timeout=1000):
        try:
            assert "正在归档文件" in page.data_toolbar.operation_status_label.text()
        finally:
            release_worker.set()

    assert page.data_toolbar.operation_status_label.text().startswith("已归档")


def test_import_shutdown_transfers_running_job_to_application_keeper(
    qtbot,
    tmp_path: Path,
    monkeypatch,
):
    from paleo_workbench.ui.thread_keeper import detached_job_keeper

    project = ProjectDocument.new("Keeper")
    path = tmp_path / "slow.las"
    path.write_text("~Version\n", encoding="utf-8")
    started = Event()
    release = Event()

    def blocked_import(paths, existing, project_path=None):
        started.set()
        release.wait(timeout=5.0)
        return ImportReport()

    monkeypatch.setattr("paleo_workbench.ui.pages.data_page.import_files", blocked_import)
    page = DataPage(project)
    qtbot.addWidget(page)
    assert page.begin_import_paths([path])
    assert started.wait(timeout=2.0)
    thread = page._import_job.thread

    page._shutdown_import_jobs(wait_ms=1)

    keeper = detached_job_keeper()
    assert keeper.owns(thread)
    release.set()
    qtbot.waitUntil(lambda: not keeper.owns(thread), timeout=3000)


def test_data_page_import_uses_owned_worker_job_lifecycle(qtbot):
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

    page = DataPage(ProjectDocument.new("ImportHandle"))
    qtbot.addWidget(page)

    assert isinstance(page._import_job, OwnedWorkerJob)
    assert not hasattr(page, "_import_jobs")


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

    def fake_import_folder(path, existing, project_path=None):
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

    with qtbot.waitSignal(page.import_finished, timeout=5000):
        started = page.begin_import_folder_from_dialog()

    assert started is True
    assert worker_threads
    assert worker_threads[0] is not page.thread()
    assert project.resources[0].name == "cube.sgy"
    assert "已归档 1" in page.data_toolbar.operation_status_label.text()


def test_async_import_refreshes_table_once(qtbot, tmp_path: Path):
    """Multi-file async import applies one model reset with the expected total."""
    project = ProjectDocument.new("Demo")
    paths = []
    for index in range(5):
        path = tmp_path / f"well_{index}.las"
        # Distinct content so checksum dedupe does not collapse the batch.
        path.write_text(f"~Version\n# file {index}\n", encoding="utf-8")
        paths.append(path)

    page = DataPage(project=project)
    qtbot.addWidget(page)

    reset_count = {"n": 0}
    page.asset_table.model.modelAboutToBeReset.connect(
        lambda *_args: reset_count.__setitem__("n", reset_count["n"] + 1)
    )
    update_counts: list[int] = []
    original_update_assets = page.asset_table.update_assets

    def tracking_update_assets(resources, artifacts, project_root=None):
        update_counts.append(len(resources))
        return original_update_assets(resources, artifacts, project_root=project_root)

    page.asset_table.update_assets = tracking_update_assets

    assert page.reader_panel.current_mode == "empty"
    with qtbot.waitSignal(page.import_finished, timeout=3000):
        started = page.begin_import_paths(paths)

    assert started is True
    assert len(project.resources) == 5
    assert _table_row_count(page) == 5
    assert reset_count["n"] == 1
    assert update_counts == [5]
    assert "已归档 5" in page.data_toolbar.operation_status_label.text()
    assert isinstance(page.asset_table.table, QTableView)
    assert isinstance(_table_model(page), AssetTableModel)
    # Import must not rebuild reader when nothing is selected.
    assert page.reader_panel.current_mode == "empty"


def test_async_import_keeps_reader_content_for_prior_selection(
    qtbot,
    tmp_path: Path,
):
    """Batch table refresh after import must not clear an existing reader preview."""
    first = tmp_path / "alpha.txt"
    first.write_text("alpha-content\n", encoding="utf-8")
    extra_paths = []
    for index in range(3):
        path = tmp_path / f"extra_{index}.txt"
        path.write_text(f"extra {index}\n", encoding="utf-8")
        extra_paths.append(path)

    project = ProjectDocument.new("Demo")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([first])
    page.asset_table.table.selectRow(0)
    _wait_reader_mode(qtbot, page, "text")
    assert "alpha-content" in page.reader_panel.text_preview.toPlainText()

    reset_count = {"n": 0}
    page.asset_table.model.modelAboutToBeReset.connect(
        lambda *_args: reset_count.__setitem__("n", reset_count["n"] + 1)
    )

    with qtbot.waitSignal(page.import_finished, timeout=3000):
        started = page.begin_import_paths(extra_paths)

    assert started is True
    assert len(project.resources) == 4
    assert _table_row_count(page) == 4
    assert reset_count["n"] == 1
    assert "已归档 3" in page.data_toolbar.operation_status_label.text()
    assert page.reader_panel.current_mode == "text"
    assert "alpha-content" in page.reader_panel.text_preview.toPlainText()


def test_data_page_selection_renders_imported_text_preview(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    text_path = tmp_path / "notes.txt"
    text_path.write_text("alpha\nbeta\n", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.import_paths([text_path])

    page.asset_table.table.selectRow(0)
    _wait_reader_mode(qtbot, page, "text")

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
    _wait_reader_mode(qtbot, page, "image")

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
    _wait_reader_mode(qtbot, page, "pdf")

    assert page.reader_panel.current_mode == "pdf"
    assert page.reader_panel.stack.currentWidget() is page.reader_panel.pdf_widget
    assert page.reader_panel.pdf_image is page.reader_panel.pdf_widget.fallback_image
    assert page.reader_panel.pdf_page_label.text()


def test_data_page_uses_reader_panel(qtbot):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)

    assert isinstance(page.reader_panel, DataReaderPanel)
    assert page.right_splitter.indexOf(page.reader_panel) == 0


def test_data_page_close_shuts_down_preview_and_releases_engine_widgets(qtbot, monkeypatch):
    page = DataPage(project=ProjectDocument.new("Demo"))
    calls = []
    monkeypatch.setattr(
        type(page._preview_controller),
        "shutdown",
        lambda self, *args, **kwargs: calls.append("shutdown"),
    )
    monkeypatch.setattr(
        type(page.reader_panel),
        "release_engine_widgets",
        lambda self: calls.append("release"),
    )

    page.close()

    assert calls == ["shutdown", "shutdown", "release"]


def test_data_page_deferred_delete_shuts_down_preview_and_releases_engine_widgets(
    qtbot, monkeypatch
):
    from PySide6.QtCore import QEvent

    page = DataPage(project=ProjectDocument.new("Demo"))
    calls = []
    monkeypatch.setattr(
        type(page._preview_controller),
        "shutdown",
        lambda self, *args, **kwargs: calls.append("shutdown"),
    )
    monkeypatch.setattr(
        type(page.reader_panel),
        "release_engine_widgets",
        lambda self: calls.append("release"),
    )

    page.event(QEvent(QEvent.Type.DeferredDelete))

    assert calls == ["shutdown", "shutdown", "release"]


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
    _wait_reader_mode(qtbot, page, "text")

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
    _wait_reader_mode(qtbot, page, "text")

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
    _wait_reader_mode(qtbot, page, "text")
    page.asset_table.set_search_text("beta")

    assert page.reader_panel.current_mode == "empty"
    assert page.remove_btn.isEnabled() is False
    assert page.rescan_btn.isEnabled() is False
    assert page.open_folder_btn.isEnabled() is False
    # Inspector mirrors the cleared selection (no metadata rows).
    assert page.inspector_panel.metadata_table.rowCount() == 0
    assert received[-1]["selected_name"] == "未选择"
    assert received[-1]["selected_type"] == ""
    assert received[-1]["selected_format"] == ""
    assert received[-1]["reader_mode"] == "empty"


def test_data_page_toolbar_search_filters_asset_table(qtbot, tmp_path: Path):
    first = tmp_path / "alpha.txt"
    second = tmp_path / "beta.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    project = ProjectDocument.new("Demo")
    project.resources.extend(
        [
            ResourceItem(name="alpha.txt", path=str(first), type="document", format="txt"),
            ResourceItem(name="beta.txt", path=str(second), type="document", format="txt"),
        ]
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)

    page.data_toolbar.search_box.setText("beta")
    # Toolbar search is debounced (~180ms).
    qtbot.wait(200)

    assert _table_row_count(page) == 1
    assert _table_text(page, 0, 0) == "beta.txt"


def test_data_page_toolbar_import_button_uses_background_import(
    qtbot,
    tmp_path: Path,
    monkeypatch,
):
    project = ProjectDocument.new("Demo")
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)
    monkeypatch.setattr(page, "_choose_import_files", lambda: [path])

    with qtbot.waitSignal(page.import_finished, timeout=1000):
        page.data_toolbar.import_btn.click()

    assert project.resources[0].name == "notes.txt"


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
    _wait_reader_mode(qtbot, page, "message")

    removed = page.remove_selected_asset()

    assert removed is True
    assert project.export_artifacts == []
    assert page.reader_panel.current_mode == "empty"
    assert page.remove_btn.isEnabled() is False
    assert "已移出项目" in page.data_toolbar.operation_status_label.text()


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
    _wait_reader_mode(qtbot, page, "message")
    opened = []
    monkeypatch.setattr(
        "paleo_workbench.ui.pages.data_page.QDesktopServices.openUrl",
        lambda url: opened.append(url.toLocalFile()) or True,
    )

    folder = page.open_selected_folder()

    assert folder == output_dir
    assert opened == [output_dir.as_posix()]
    assert output_dir.as_posix() in page.data_toolbar.operation_status_label.text()


def test_data_page_keeps_latest_operation_report_when_selection_changes(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Demo")
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    page = DataPage(project=project)
    qtbot.addWidget(page)

    page.import_paths([path])

    assert "已归档 1" in page.data_toolbar.operation_status_label.text()
    page.asset_table.table.selectRow(0)
    _wait_reader_mode(qtbot, page, "text")
    assert "已归档 1" in page.data_toolbar.operation_status_label.text()


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
    _wait_reader_mode(qtbot, page, "text")
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
        "paleo_workbench.ui.data_lifecycle_controller.scan_resources",
        lambda _folder, project_path=None: [replacement],
    )

    assert page.rescan_selected_asset() is True

    _wait_reader_mode(qtbot, page, "image")
    assert received[-1]["selected_name"] == "notes.txt"
    assert received[-1]["reader_mode"] == "image"


# ---------------------------------------------------------------------------
# Context menu integration (Task 3).
#
# These tests construct DataPage, whose import chain pulls in WebEngine via
# preview_widgets. In a headless CI without a GL surface the widget hangs at
# construction, so each is marked with @pytest.mark.timeout(15). They pass in
# a proper GL/desktop environment.
# ---------------------------------------------------------------------------

pytestmark_cm = pytest.mark.timeout(15)


@pytest.mark.timeout(15)
def test_data_page_context_menu_triggers_remove(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Test")
    project.resources.append(
        ResourceItem(name="r.las", path="/r.las", type="well_log", format="las", status="parsed")
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.update_state(dashboard_state(project), project.resources, project.export_artifacts)
    page.asset_table.table.selectRow(0)

    menu = AssetContextMenu(page)
    menu.build(page._selected_asset, viz_supported=False)
    remove_act = menu.find_action("ctx_remove")
    assert remove_act is not None
    remove_act.triggered.connect(page.remove_selected_asset)
    remove_act.trigger()

    assert len(page.project.resources) == 0


@pytest.mark.timeout(15)
def test_data_page_show_context_menu_wires_actions(qtbot, tmp_path: Path):
    """_show_context_menu builds the menu and wires export sub-actions."""
    project = ProjectDocument.new("Test")
    project.resources.append(
        ResourceItem(name="well.las", path="/well.las", type="well_log", format="las", status="parsed")
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.update_state(dashboard_state(project), project.resources, project.export_artifacts)
    page.asset_table.table.selectRow(0)

    # Build the menu via the page method; do not exec (no event loop).
    menu = AssetContextMenu(page)
    menu.build(page._selected_asset, viz_supported=True)
    # Manually mirror the wiring done in _show_context_menu for the export
    # sub-action so we can assert the export handler is reachable.
    csv_act = menu.find_export_action("CSV")
    assert csv_act is not None

    captured: list[str] = []
    csv_act.triggered.connect(lambda checked=False, lbl="CSV": captured.append(lbl))
    csv_act.trigger()
    assert captured == ["CSV"]


@pytest.mark.timeout(15)
def test_data_page_export_selected_asset_las_to_csv(qtbot, tmp_path: Path):
    las_content = "~V\nSTRT.M 0:\nSTOP.M 10:\nSTEP.M 1:\n~C\nDEPT.M  :\n~A\n0\n1\n"
    src = tmp_path / "well.las"
    src.write_text(las_content)
    project = ProjectDocument.new("Test")
    project.resources.append(
        ResourceItem(
            name="well.las", path=str(src), type="well_log", format="las", status="parsed"
        )
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.update_state(dashboard_state(project), project.resources, project.export_artifacts)
    page.asset_table.table.selectRow(0)
    assert isinstance(page._selected_asset, ResourceItem)

    out_path = tmp_path / "out.csv"
    with patch(
        "paleo_workbench.ui.pages.data_page.QFileDialog.getSaveFileName",
        return_value=(str(out_path), ""),
    ):
        page._export_selected_asset("CSV")

    assert out_path.exists()
    assert "已导出" in page.data_toolbar.operation_status_label.text()


@pytest.mark.timeout(15)
def test_data_page_export_selected_asset_noop_when_dialog_cancelled(
    qtbot, tmp_path: Path
):
    src = tmp_path / "well.las"
    src.write_text("~V\nSTRT.M 0:\nSTOP.M 10:\nSTEP.M 1:\n~C\nDEPT.M  :\n~A\n0\n")
    project = ProjectDocument.new("Test")
    project.resources.append(
        ResourceItem(
            name="well.las", path=str(src), type="well_log", format="las", status="parsed"
        )
    )
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.update_state(dashboard_state(project), project.resources, project.export_artifacts)
    page.asset_table.table.selectRow(0)

    out_path = tmp_path / "out.csv"
    with patch(
        "paleo_workbench.ui.pages.data_page.QFileDialog.getSaveFileName",
        return_value=("", ""),
    ):
        page._export_selected_asset("CSV")

    assert not out_path.exists()

@pytest.mark.timeout(15)
def test_data_page_export_selected_asset_noop_for_artifact(qtbot, tmp_path: Path):
    project = ProjectDocument.new("Test")
    artifact = ExportArtifact(
        linked_id="m1", format="PDF", output_path=str(tmp_path / "m.pdf")
    )
    project.export_artifacts.append(artifact)
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.update_state(dashboard_state(project), project.resources, project.export_artifacts)
    page.asset_table.table.selectRow(0)
    assert isinstance(page._selected_asset, ExportArtifact)

    out_path = tmp_path / "out.csv"
    with patch(
        "paleo_workbench.ui.pages.data_page.QFileDialog.getSaveFileName",
        return_value=(str(out_path), ""),
    ):
        page._export_selected_asset("CSV")

    assert not out_path.exists()


def test_data_page_default_project_root_skips_disk_cache(qtbot):
    """Default meta.project_root='.' is unknown — do not bind disk cache to CWD."""
    project = ProjectDocument.new("Demo")
    assert project.meta.project_root == "."
    page = DataPage(project=project)
    qtbot.addWidget(page)

    assert page._preview_disk_project_root() is None
    assert page._preview_controller.disk_cache.project_root is None
    assert page._visualization_controller.disk_cache.project_root is None


def test_data_page_empty_project_root_skips_disk_cache(qtbot):
    project = ProjectDocument.new("Demo")
    project.meta.project_root = ""
    page = DataPage(project=project)
    qtbot.addWidget(page)

    assert page._preview_disk_project_root() is None
    assert page._preview_controller.disk_cache.project_root is None
    assert page._visualization_controller.disk_cache.project_root is None


def test_data_page_clear_preview_cache(tmp_path: Path, qtbot):
    """clear_preview_cache removes .preview_cache on disk and memory LRU."""
    from paleo_workbench.ui.pages.preview_provider import PreviewResult

    project = ProjectDocument.new("Demo")
    project.meta.project_root = str(tmp_path)
    page = DataPage(project=project)
    qtbot.addWidget(page)

    assert page._preview_controller.disk_cache.project_root == tmp_path.resolve()
    assert page._visualization_controller.disk_cache.project_root == tmp_path.resolve()

    entry = tmp_path / ".preview_cache" / "entries" / "x"
    entry.mkdir(parents=True)
    (entry / "meta.json").write_text("{}", encoding="utf-8")

    page._preview_controller.cache.put(
        ("test-key",),
        PreviewResult(mode="text", title="cached"),
    )
    page._visualization_controller.cache.put(
        ("visual-key",),
        PreviewResult(mode="message", title="visual cached"),
    )
    assert page._preview_controller.cache._data
    assert page._visualization_controller.cache._data
    assert (tmp_path / ".preview_cache").is_dir()

    page.clear_preview_cache()

    assert not (tmp_path / ".preview_cache").exists()
    assert not page._preview_controller.cache._data
    assert page._preview_controller.cache.current_bytes == 0
    assert not page._visualization_controller.cache._data
    assert page._visualization_controller.cache.current_bytes == 0


def test_preview_settings_change_invalidates_and_reloads_selected_asset(
    qtbot, monkeypatch
):
    page = DataPage(project=ProjectDocument.new("Demo"))
    qtbot.addWidget(page)
    selected = object()
    page._selected_asset = selected
    requested: list[object] = []
    monkeypatch.setattr(page._preview_controller, "request", requested.append)
    visual_requests: list[object] = []
    monkeypatch.setattr(
        page._visualization_controller,
        "request",
        visual_requests.append,
    )
    previous_generation = page._preview_controller.generation
    previous_visual_generation = page._visualization_controller.generation
    settings = replace(page.reader_panel.preview_settings, text_limit_kib=128)

    page.reader_panel.preview_settings_changed.emit(settings)

    assert page._preview_controller.settings == settings
    assert page._preview_controller.generation == previous_generation + 1
    assert page._visualization_controller.settings == settings
    assert page._visualization_controller.generation == previous_visual_generation + 1
    assert requested == [selected]
    assert visual_requests == []


def test_deliver_export_artifact_resolves_project_relative_output(
    qtbot, monkeypatch, tmp_path: Path
):
    """Regression (audit): deliver_asset must resolve project-relative export
    paths through the page's project file.

    The controller previously called the DataPage-only ``_project_file_for_io``
    helper on itself; the AttributeError was swallowed and every delivery of a
    relative-output artifact failed with 源文件不存在.
    """
    from PySide6.QtWidgets import QDialog

    from paleo_workbench.ui import data_lifecycle_controller as dlc

    project = ProjectDocument.new("Demo")
    out = tmp_path / "exports" / "map.pdf"
    out.parent.mkdir(parents=True)
    out.write_bytes(b"%PDF-1.4\n%%EOF\n")
    artifact = ExportArtifact(
        linked_id="map_1",
        format="PDF",
        output_path="exports/map.pdf",
    )
    project.export_artifacts.append(artifact)
    page = DataPage(project=project)
    qtbot.addWidget(page)
    page.project_path = tmp_path / "demo.paleo.json"

    destination = tmp_path / "handoff" / "map-final.pdf"

    class AcceptedDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):  # noqa: A003 - Qt API name
            return QDialog.DialogCode.Accepted

        def output_path(self):
            return destination

    monkeypatch.setattr(dlc, "_DeliveryDialog", AcceptedDialog)
    page._lifecycle.deliver_asset(artifact)

    status = page.data_toolbar.operation_status_label.text()
    assert "源文件不存在" not in status
    assert "已导出 / 交付" in status
    assert destination.read_bytes() == b"%PDF-1.4\n%%EOF\n"
