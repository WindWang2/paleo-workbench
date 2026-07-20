from __future__ import annotations

from PySide6.QtWidgets import QTextEdit


class TextPreviewWidget(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")

    def load_text(self, text: str) -> None:
        self.setPlainText(text)

    def apply_settings(self, settings) -> None:
        font = self.font()
        font.setPointSize(settings.font_size)
        self.setFont(font)
        self.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth
            if settings.wrap_text
            else QTextEdit.LineWrapMode.NoWrap
        )
