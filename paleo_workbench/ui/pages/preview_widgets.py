from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QPixmap
try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:  # pragma: no cover
    QPdfDocument = None

try:
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:  # pragma: no cover
    QPdfView = None

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class MessagePreviewWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)

    def set_message(self, text: str) -> None:
        self.setText(text)


class TextPreviewWidget(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")

    def load_text(self, text: str) -> None:
        self.setPlainText(text)


class TablePreviewWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

    def load_table(
        self,
        headers: tuple[str, ...],
        rows: tuple[tuple[str, ...], ...],
    ) -> None:
        self.clear()
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(list(headers))
        self.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column_index, value in enumerate(row):
                self.setItem(row_index, column_index, QTableWidgetItem(value))
        self.resizeColumnsToContents()


class SummaryTablePreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        self.summary_table = TablePreviewWidget()
        self.detail_table = TablePreviewWidget()
        layout.addWidget(self.summary_table)
        layout.addWidget(self.detail_table, 1)

    def load_summary(
        self,
        summary_rows: tuple[tuple[str, str], ...],
        detail_headers: tuple[str, ...],
        detail_rows: tuple[tuple[str, ...], ...],
        message: str = "",
    ) -> None:
        self.message_label.setText(message)
        self.summary_table.load_table(("属性", "值"), summary_rows)
        self.detail_table.load_table(detail_headers, detail_rows)


class ImagePreviewWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._path = ""
        self._revision: tuple[object, ...] | None = None
        self._pixmap: QPixmap | None = None

    def load(self, path: str, revision: tuple[object, ...] | None = None) -> None:
        if path != self._path or revision != self._revision or self._pixmap is None:
            self._path = path
            self._revision = revision
            self._pixmap = QPixmap(path)
        self.render_current()

    def render_current(self) -> None:
        self.clear()
        if self._pixmap is None or self._pixmap.isNull():
            self.setText("图片预览加载失败")
            return
        self.setPixmap(
            self._pixmap.scaled(
                max(self.width(), 240),
                max(self.height(), 180),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._path:
            self.render_current()


class PdfPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.document = QPdfDocument(self) if QPdfDocument is not None else None
        self.pdf_view = QPdfView(self) if QPdfView is not None and self.document is not None else None
        self.fallback_image = QLabel()
        self.fallback_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content_stack = QStackedWidget(self)
        self._page = 0
        self._path = ""
        self._revision: tuple[object, ...] | None = None
        self._load_failed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if self.pdf_view is not None:
            self.pdf_view.setDocument(self.document)
            self._content_stack.addWidget(self.pdf_view)
        self._content_stack.addWidget(self.fallback_image)
        self._content_stack.setCurrentWidget(self.pdf_view or self.fallback_image)
        layout.addWidget(self._content_stack, 1)

        controls = QHBoxLayout()
        self.prev_btn = QPushButton("上一页")
        self.prev_btn.clicked.connect(self.previous_page)
        self.page_label = QLabel("0 / 0")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_btn = QPushButton("下一页")
        self.next_btn.clicked.connect(self.next_page)
        controls.addWidget(self.prev_btn)
        controls.addWidget(self.page_label, 1)
        controls.addWidget(self.next_btn)
        layout.addLayout(controls)

        if self.document is None:
            self._show_fallback_message("PDF 预览不可用")
            self.page_label.setText("0 / 0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)

    def load(self, path: str, revision: tuple[object, ...] | None = None) -> None:
        if self.document is None:
            self._show_fallback_message("PDF 预览不可用")
            self.page_label.setText("0 / 0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        if path != self._path or revision != self._revision:
            self._path = path
            self._revision = revision
            self._page = 0
            self._load_failed = False
            error = self.document.load(path)
            if error != QPdfDocument.Error.None_ or self.document.pageCount() <= 0:
                self._load_failed = True
                self._show_fallback_message("PDF 预览加载失败")
                self.page_label.setText("0 / 0")
                self.prev_btn.setEnabled(False)
                self.next_btn.setEnabled(False)
                return
        if self._load_failed:
            self._show_fallback_message("PDF 预览加载失败")
            self.page_label.setText("0 / 0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        self._render_page()

    def next_page(self) -> None:
        if self.document is None or self._load_failed:
            return
        if self._page < self.document.pageCount() - 1:
            self._page += 1
            self._render_page()

    def previous_page(self) -> None:
        if self.document is None or self._load_failed:
            return
        if self._page > 0:
            self._page -= 1
            self._render_page()

    def _render_page(self) -> None:
        if self.document is None:
            self._show_fallback_message("PDF 预览不可用")
            self.page_label.setText("0 / 0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        page_count = self.document.pageCount()
        if page_count <= 0:
            self._load_failed = True
            self._show_fallback_message("PDF 预览加载失败")
            self.page_label.setText("0 / 0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        if self.pdf_view is not None:
            self._content_stack.setCurrentWidget(self.pdf_view)
            self.pdf_view.setPageMode(QPdfView.PageMode.SinglePage)
            navigator = self.pdf_view.pageNavigator()
            navigator.jump(self._page, QPointF(), navigator.currentZoom())
        else:
            image = self.document.render(
                self._page,
                QSize(max(self.width(), 420), max(self.height(), 560)),
            )
            if image.isNull():
                self._show_fallback_message("PDF 页面渲染失败")
            else:
                self._show_fallback_pixmap(QPixmap.fromImage(image))
        self.page_label.setText(f"{self._page + 1} / {page_count}")
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < page_count - 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._path and self.pdf_view is None and self.document is not None and self.document.pageCount() > 0:
            self._render_page()

    def _show_fallback_message(self, text: str) -> None:
        self.fallback_image.clear()
        self.fallback_image.setText(text)
        self._content_stack.setCurrentWidget(self.fallback_image)

    def _show_fallback_pixmap(self, pixmap: QPixmap) -> None:
        self.fallback_image.clear()
        self.fallback_image.setPixmap(pixmap)
        self._content_stack.setCurrentWidget(self.fallback_image)
