from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import (
    QFrame,
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

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult


class DataReaderPanel(QFrame):
    reader_mode_changed = Signal(str)

    def __init__(self, provider: PreviewProvider | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("DataReaderPanel")
        self.setMinimumWidth(320)
        self.provider = provider or PreviewProvider()
        self.current_mode = "empty"
        self._current_result = PreviewResult(mode="empty", title="请选择数据项")
        self._image_path = ""
        self._image_revision: tuple[object, ...] | None = None
        self._image_pixmap: QPixmap | None = None
        self._pdf_document: QPdfDocument | None = None
        self._pdf_page = 0
        self._pdf_path = ""
        self._pdf_revision: tuple[object, ...] | None = None
        self.setStyleSheet(
            f"QFrame#DataReaderPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.title_label = QLabel("请选择数据项")
        self.title_label.setObjectName("DataReaderTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(f"color: {tokens.TEXT_PRIMARY}; font-weight: 600;")
        layout.addWidget(self.title_label)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("DataReaderMeta")
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(self.meta_label)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.empty_label = self._message_widget("从列表中选择一个数据、成果或文件")
        self.stack.addWidget(self.empty_label)

        self.message_label = self._message_widget("")
        self.stack.addWidget(self.message_label)

        self.text_preview = QTextEdit()
        self.text_preview.setReadOnly(True)
        self.text_preview.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.text_preview.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        self.stack.addWidget(self.text_preview)

        self.table_preview = QTableWidget()
        self.table_preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stack.addWidget(self.table_preview)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.image_label)

        self.pdf_widget = QWidget()
        pdf_layout = QVBoxLayout(self.pdf_widget)
        pdf_layout.setContentsMargins(0, 0, 0, 0)
        self.pdf_image = QLabel()
        self.pdf_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pdf_layout.addWidget(self.pdf_image, 1)
        pdf_controls = QHBoxLayout()
        self.pdf_prev_btn = QPushButton("上一页")
        self.pdf_prev_btn.clicked.connect(self.previous_pdf_page)
        self.pdf_page_label = QLabel("0 / 0")
        self.pdf_page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pdf_next_btn = QPushButton("下一页")
        self.pdf_next_btn.clicked.connect(self.next_pdf_page)
        pdf_controls.addWidget(self.pdf_prev_btn)
        pdf_controls.addWidget(self.pdf_page_label, 1)
        pdf_controls.addWidget(self.pdf_next_btn)
        pdf_layout.addLayout(pdf_controls)
        self.stack.addWidget(self.pdf_widget)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(f"color: {tokens.WARNING}; font-size: 12px;")
        layout.addWidget(self.warning_label)

        self.stack.setCurrentWidget(self.empty_label)

    def update_asset(self, asset: ResourceItem | ExportArtifact | None) -> None:
        self.render(self.provider.preview(asset))

    def render(self, result: PreviewResult) -> None:
        self._current_result = result
        self.current_mode = result.mode
        self.reader_mode_changed.emit(result.mode)
        self.title_label.setText(result.title)
        self.meta_label.setText(self._meta_text(result))
        self.warning_label.setText(result.warning)

        if result.mode == "empty":
            self.stack.setCurrentWidget(self.empty_label)
            return

        if result.mode == "message":
            self.message_label.setText(result.message)
            self.stack.setCurrentWidget(self.message_label)
            return

        if result.mode == "text":
            self.text_preview.setPlainText(result.text)
            self.stack.setCurrentWidget(self.text_preview)
            return

        if result.mode == "table":
            self._render_table(result)
            self.stack.setCurrentWidget(self.table_preview)
            return

        if result.mode == "image":
            self._render_image(result.path, result.revision)
            self.stack.setCurrentWidget(self.image_label)
            return

        if result.mode == "pdf":
            self._load_pdf(result.path, result.revision)
            self.stack.setCurrentWidget(self.pdf_widget)
            return

        self.message_label.setText(result.message or "预览不可用")
        self.stack.setCurrentWidget(self.message_label)

    def next_pdf_page(self) -> None:
        if self._pdf_document is not None and self._pdf_page < self._pdf_document.pageCount() - 1:
            self._pdf_page += 1
            self._render_pdf_page()

    def previous_pdf_page(self) -> None:
        if self._pdf_document is not None and self._pdf_page > 0:
            self._pdf_page -= 1
            self._render_pdf_page()

    def _message_widget(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        return label

    def _meta_text(self, result: PreviewResult) -> str:
        parts = [part for part in [result.type_label, result.format, result.status, result.path] if part]
        return " · ".join(parts)

    def _render_table(self, result: PreviewResult) -> None:
        headers = [header for header in result.table_headers]
        self.table_preview.clear()
        self.table_preview.setColumnCount(len(headers))
        self.table_preview.setHorizontalHeaderLabels(headers)
        self.table_preview.setRowCount(len(result.table_rows))
        for row_index, row in enumerate(result.table_rows):
            for column_index, value in enumerate(row):
                self.table_preview.setItem(row_index, column_index, QTableWidgetItem(value))
        self.table_preview.resizeColumnsToContents()

    def _render_image(self, path: str, revision: tuple[object, ...] | None = None) -> None:
        self.image_label.clear()
        if (
            path != self._image_path
            or revision != self._image_revision
            or self._image_pixmap is None
        ):
            self._image_path = path
            self._image_revision = revision
            self._image_pixmap = QPixmap(path)
        if self._image_pixmap is None or self._image_pixmap.isNull():
            self.image_label.setText("图片预览加载失败")
            return
        self.image_label.setPixmap(
            self._image_pixmap.scaled(
                max(self.width() - 48, 240),
                max(self.height() - 160, 180),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def _load_pdf(self, path: str, revision: tuple[object, ...] | None = None) -> None:
        if self._pdf_document is None:
            self._pdf_document = QPdfDocument(self)
        if path != self._pdf_path or revision != self._pdf_revision:
            self._pdf_path = path
            self._pdf_revision = revision
            self._pdf_page = 0
            self.pdf_image.clear()
            error = self._pdf_document.load(path)
            if error != QPdfDocument.Error.None_ or self._pdf_document.pageCount() <= 0:
                self.pdf_image.setText("PDF 预览加载失败")
                self.pdf_page_label.setText("0 / 0")
                self.pdf_prev_btn.setEnabled(False)
                self.pdf_next_btn.setEnabled(False)
                return
        self.pdf_image.clear()
        self._render_pdf_page()

    def _render_pdf_page(self) -> None:
        if self._pdf_document is None:
            return
        image = self._pdf_document.render(
            self._pdf_page,
            QSize(max(self.width() - 48, 420), max(self.height() - 160, 560)),
        )
        if image.isNull():
            self.pdf_image.setText("PDF 页面渲染失败")
        else:
            self.pdf_image.setPixmap(QPixmap.fromImage(image))
        page_count = self._pdf_document.pageCount()
        self.pdf_page_label.setText(f"{self._pdf_page + 1} / {page_count}")
        self.pdf_prev_btn.setEnabled(self._pdf_page > 0)
        self.pdf_next_btn.setEnabled(self._pdf_page < page_count - 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.current_mode == "image" and self._current_result.path:
            self._render_image(self._current_result.path, self._current_result.revision)
        elif self.current_mode == "pdf" and self._pdf_document is not None:
            self._render_pdf_page()
