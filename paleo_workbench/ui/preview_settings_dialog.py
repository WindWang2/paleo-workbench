from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QDialog, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.preview_settings import (
    PreviewSettings,
    PreviewSettingsStore,
)
from paleo_workbench.ui.pages.preview_settings_panel import PreviewSettingsPanel


class PreviewSettingsDialog(QDialog):
    """Application-level modal container for the shared preview editor."""

    settings_applied = Signal(object)

    def __init__(
        self,
        parent=None,
        *,
        store: PreviewSettingsStore | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("PreviewSettingsDialog")
        self.setWindowTitle("预览设置")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.SPACE_4,
            tokens.SPACE_4,
            tokens.SPACE_4,
            tokens.SPACE_4,
        )
        self.panel = PreviewSettingsPanel(store=store)
        layout.addWidget(self.panel)

        self.panel.settings_applied.connect(self.settings_applied)
        self.panel.apply_btn.clicked.connect(self.accept)

    def set_settings(self, settings: PreviewSettings) -> None:
        self.panel.set_settings(settings)

    def set_preview_mode(self, mode: str) -> None:
        self.panel.set_preview_mode(mode)
