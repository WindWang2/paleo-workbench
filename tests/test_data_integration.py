from dataclasses import replace

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.preview_provider import PreviewResult
from paleo_workbench.ui.pages.preview_settings import PreviewSettingsStore
from paleo_workbench.ui.preview_settings_dialog import PreviewSettingsDialog


def _preview_store(tmp_path):
    return PreviewSettingsStore(
        QSettings(
            str(tmp_path / "window-preview-settings.ini"),
            QSettings.Format.IniFormat,
        )
    )


def test_app_shell_page_one_is_data_page(qtbot):
    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(1)
    assert isinstance(page, DataPage)


def test_data_page_receives_resources_and_artifacts(qtbot):
    project = ProjectDocument.new("Test")
    project.resources.append(
        ResourceItem(
            name="well.las",
            path="/tmp/well.las",
            type="well_log",
            format="las",
        )
    )
    project.export_artifacts.append(
        ExportArtifact(
            linked_id="map_1",
            format="PDF",
            output_path="/tmp/map.pdf",
        )
    )
    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.page_stack.widget(1)
    assert page.asset_table.table.model().rowCount() == 2


def test_tools_preview_settings_action_opens_dialog_with_current_mode(
    qtbot, monkeypatch, tmp_path
):
    opened: list[PreviewSettingsDialog] = []
    monkeypatch.setattr(
        PreviewSettingsDialog,
        "exec",
        lambda dialog: opened.append(dialog) or QDialog.DialogCode.Rejected,
    )
    window = PaleoWorkbenchWindow(preview_settings_store=_preview_store(tmp_path))
    qtbot.addWidget(window)
    window.app_shell.data_page.reader_panel.render(
        PreviewResult(mode="pdf", title="report.pdf")
    )

    window.app_shell.menu_bar.preview_settings_action.trigger()

    assert opened == [window._preview_settings_dialog]
    assert opened[0].panel.category_combo.currentData() == "pdf"


def test_preview_dialog_applies_to_current_data_page_after_shell_rebuild(
    qtbot, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        PreviewSettingsDialog,
        "exec",
        lambda _dialog: QDialog.DialogCode.Rejected,
    )
    window = PaleoWorkbenchWindow(preview_settings_store=_preview_store(tmp_path))
    qtbot.addWidget(window)
    window.app_shell.menu_bar.preview_settings_action.trigger()
    dialog = window._preview_settings_dialog
    old_reader = window.app_shell.data_page.reader_panel

    window.new_project("Replacement")
    current_reader = window.app_shell.data_page.reader_panel
    updated = replace(current_reader.preview_settings, font_size=21)
    dialog.set_settings(updated)
    dialog.panel.apply_btn.click()

    assert current_reader.preview_settings == updated
    assert current_reader.text_preview.font().pointSize() == 21
    assert window.app_shell.data_page._preview_controller.settings == updated
    assert window.app_shell.data_page._visualization_controller.settings == updated
    assert old_reader is not current_reader
