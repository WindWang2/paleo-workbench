from __future__ import annotations

from PySide6.QtWidgets import QTextEdit

from paleo_workbench.ui import tokens


class TextPreviewWidget(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        # 等宽字体族统一走 FONT_FAMILY_MONO token（主题无关，静态即可）。
        self.setStyleSheet(f"font-family: {tokens.FONT_FAMILY_MONO};")

    def load_text(self, text: str) -> None:
        self.setPlainText(text)

    def apply_settings(self, settings) -> None:
        font = self.font()
        font.setPointSize(settings.font_size)
        self.setFont(font)
        self.setStyleSheet(
            f"font-family: {tokens.FONT_FAMILY_MONO}; font-size: {settings.font_size}pt;"
        )
        self.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth
            if settings.wrap_text
            else QTextEdit.LineWrapMode.NoWrap
        )
