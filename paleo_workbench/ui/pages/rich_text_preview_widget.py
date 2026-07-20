from __future__ import annotations

from PySide6.QtWidgets import QTextBrowser, QTextEdit


class RichTextPreviewWidget(QTextBrowser):
    """Read-only rich-text renderer for Markdown/HTML.

    External network resources are blocked; local file:// images (relative to
    the document) are allowed so embedded figures render.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(False)
        self.setReadOnly(True)

    def loadResource(self, resource_type, url):
        # Block non-file URLs (network). Allow file:// for local images.
        if url.scheme() not in ("", "file"):
            return None
        return super().loadResource(resource_type, url)

    def load_html(self, html: str) -> None:
        self.setHtml(html)

    def apply_settings(self, settings) -> None:
        font = self.font()
        font.setPointSize(settings.font_size)
        self.setFont(font)
        self.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth
            if settings.wrap_text
            else QTextEdit.LineWrapMode.NoWrap
        )
