from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
)

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult
from paleo_workbench.ui.pages.preview_widgets import (
    ImagePreviewWidget,
    MessagePreviewWidget,
    PdfPreviewWidget,
    SummaryTablePreviewWidget,
    TablePreviewWidget,
    TextPreviewWidget,
)


class DataReaderPanel(QFrame):
    reader_mode_changed = Signal(str)

    def __init__(self, provider: PreviewProvider | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("DataReaderPanel")
        self.setMinimumWidth(320)
        self.provider = provider or PreviewProvider()
        self.current_mode = "empty"
        self._current_result = PreviewResult(mode="empty", title="请选择数据项")
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

        self.text_preview = TextPreviewWidget()
        self.stack.addWidget(self.text_preview)

        self.table_preview = TablePreviewWidget()
        self.stack.addWidget(self.table_preview)

        self.well_log_preview = SummaryTablePreviewWidget()
        self.stack.addWidget(self.well_log_preview)

        self.seismic_preview = SummaryTablePreviewWidget()
        self.stack.addWidget(self.seismic_preview)

        self.image_preview_widget = ImagePreviewWidget()
        self.image_label = self.image_preview_widget
        self.stack.addWidget(self.image_label)

        self.pdf_preview_widget = PdfPreviewWidget()
        self.pdf_widget = self.pdf_preview_widget
        self.pdf_image = self.pdf_preview_widget.fallback_image
        self.pdf_prev_btn = self.pdf_preview_widget.prev_btn
        self.pdf_next_btn = self.pdf_preview_widget.next_btn
        self.pdf_page_label = self.pdf_preview_widget.page_label
        self.stack.addWidget(self.pdf_widget)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(f"color: {tokens.WARNING}; font-size: 12px;")
        layout.addWidget(self.warning_label)

        self.stack.setCurrentWidget(self.empty_label)

    def show_loading(self, asset: ResourceItem | ExportArtifact | None = None) -> None:
        self.current_mode = "loading"
        self.reader_mode_changed.emit("loading")
        title = "加载中…"
        if isinstance(asset, ResourceItem):
            title = f"加载中… {asset.name}"
        elif isinstance(asset, ExportArtifact):
            title = f"加载中… {Path(asset.output_path).name}"
        self.title_label.setText(title)
        self.meta_label.setText("")
        self.warning_label.setText("")
        self.message_label.set_message("正在生成预览…")
        self.stack.setCurrentWidget(self.message_label)

    def update_asset(self, asset: ResourceItem | ExportArtifact | None) -> None:
        # Sync path for direct panel tests; DataPage uses PreviewRequestController.
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
            self.message_label.set_message(result.message)
            self.stack.setCurrentWidget(self.message_label)
            return

        if result.mode == "text":
            self.text_preview.load_text(result.text)
            self.stack.setCurrentWidget(self.text_preview)
            return

        if result.mode == "table":
            self.table_preview.load_table(result.table_headers, result.table_rows)
            self.stack.setCurrentWidget(self.table_preview)
            return

        if result.mode == "well_log":
            self.well_log_preview.load_summary(
                result.summary_rows,
                result.table_headers,
                result.table_rows,
                result.message,
            )
            self.stack.setCurrentWidget(self.well_log_preview)
            return

        if result.mode == "seismic":
            self.seismic_preview.load_summary(
                result.summary_rows,
                result.table_headers,
                result.table_rows,
                result.message,
            )
            self.stack.setCurrentWidget(self.seismic_preview)
            return

        if result.mode == "image":
            self.image_preview_widget.load(
                result.path,
                result.revision,
                image_bytes=result.image_bytes,
            )
            self.stack.setCurrentWidget(self.image_preview_widget)
            return

        if result.mode == "pdf":
            self.pdf_preview_widget.load(
                result.path,
                result.revision,
                pdf_bytes=result.pdf_bytes,
            )
            self.stack.setCurrentWidget(self.pdf_preview_widget)
            return

        self.message_label.set_message(result.message or "预览不可用")
        self.stack.setCurrentWidget(self.message_label)

    def next_pdf_page(self) -> None:
        self.pdf_preview_widget.next_page()

    def previous_pdf_page(self) -> None:
        self.pdf_preview_widget.previous_page()

    def _message_widget(self, text: str) -> MessagePreviewWidget:
        label = MessagePreviewWidget()
        label.set_message(text)
        label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        return label

    def _meta_text(self, result: PreviewResult) -> str:
        parts = [part for part in [result.type_label, result.format, result.status, result.path] if part]
        return " · ".join(parts)
