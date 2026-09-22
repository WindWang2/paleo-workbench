from dataclasses import replace

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QDialog

from paleo_workbench.ui.pages.preview_settings import (
    PreviewSettings,
    PreviewSettingsStore,
)
from paleo_workbench.ui.preview_settings_dialog import PreviewSettingsDialog


def _store(tmp_path):
    return PreviewSettingsStore(
        QSettings(
            str(tmp_path / "preview-dialog.ini"),
            QSettings.Format.IniFormat,
        )
    )


def test_preview_settings_dialog_is_modal_and_syncs_current_context(qtbot, tmp_path):
    dialog = PreviewSettingsDialog(store=_store(tmp_path))
    qtbot.addWidget(dialog)
    custom = replace(PreviewSettings.defaults(), font_size=17)

    dialog.set_settings(custom)
    dialog.set_preview_mode("pdf")

    assert dialog.isModal() is True
    assert dialog.windowTitle() == "预览设置"
    assert dialog.panel.settings() == custom
    assert dialog.panel.category_combo.currentData() == "pdf"


def test_dialog_apply_persists_emits_and_accepts(qtbot, tmp_path):
    store = _store(tmp_path)
    dialog = PreviewSettingsDialog(store=store)
    qtbot.addWidget(dialog)
    emitted: list[PreviewSettings] = []
    dialog.settings_applied.connect(emitted.append)
    dialog.show()
    dialog.panel.font_size_spin.setValue(19)

    dialog.panel.apply_btn.click()

    assert emitted[-1].font_size == 19
    assert store.load() == emitted[-1]
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_dialog_reset_applies_defaults_without_closing(qtbot, tmp_path):
    store = _store(tmp_path)
    store.save(replace(PreviewSettings.defaults(), font_size=18))
    dialog = PreviewSettingsDialog(store=store)
    qtbot.addWidget(dialog)
    emitted: list[PreviewSettings] = []
    dialog.settings_applied.connect(emitted.append)
    dialog.show()

    dialog.panel.reset_btn.click()

    assert emitted == [PreviewSettings.defaults()]
    assert dialog.isVisible() is True
    assert dialog.result() != QDialog.DialogCode.Accepted
