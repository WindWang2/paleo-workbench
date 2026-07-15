from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
)

from geoviz import PreparedPreview

from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.geoviz_preview_host import GeoVizPreviewHost
from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult
from paleo_workbench.ui.pages.preview_widgets import (
    GeoTiffPreviewWidget,
    ImagePreviewWidget,
    JsonTreePreviewWidget,
    MediaPreviewWidget,
    MessagePreviewWidget,
    PdfPreviewWidget,
    RichTextPreviewWidget,
    SummaryTablePreviewWidget,
    TablePreviewWidget,
    TextPreviewWidget,
    WebDocumentPreviewWidget,
)


class DataReaderPanel(QFrame):
    reader_mode_changed = Signal(str)

    def __init__(self, provider: PreviewProvider | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("DataReaderPanel")
        self.setMinimumWidth(320)
        self.provider = provider or LocalVisualizationProvider()
        self.current_mode = "empty"
        self._current_result = PreviewResult(mode="empty", title="请选择数据项")
        self.setStyleSheet(
            f"QFrame#DataReaderPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3)
        layout.setSpacing(tokens.SPACE_2)

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

        provider_engine = getattr(self.provider, "engine", None)
        self.geoviz_host = GeoVizPreviewHost(provider_engine)
        self.stack.addWidget(self.geoviz_host)

        self.empty_label = self._message_widget("从列表中选择一个数据、成果或文件")
        self.empty_label.setObjectName("EmptyStateLabel")
        self.stack.addWidget(self.empty_label)

        self.message_label = self._message_widget("")
        self.message_label.setObjectName("EmptyStateLabel")
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

        self.rich_text_preview = RichTextPreviewWidget()
        self.stack.addWidget(self.rich_text_preview)

        # WebDocumentPreviewWidget is lazily constructed on first web_document
        # render to avoid forcing WebEngine subprocess init in __init__.
        self.web_document_preview: WebDocumentPreviewWidget | None = None

        self.json_tree_preview = JsonTreePreviewWidget()
        self.stack.addWidget(self.json_tree_preview)

        self.geotiff_preview = GeoTiffPreviewWidget()
        self.stack.addWidget(self.geotiff_preview)

        self.media_preview = MediaPreviewWidget()
        self.stack.addWidget(self.media_preview)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(f"color: {tokens.WARNING}; font-size: 12px;")
        layout.addWidget(self.warning_label)

        self.stack.setCurrentWidget(self.empty_label)

    def show_loading(self, asset: ResourceItem | ExportArtifact | None = None) -> None:
        clear_warning = self._safe_clear_geoviz()
        title = "加载中…"
        if isinstance(asset, ResourceItem):
            title = f"加载中… {asset.name}"
        elif isinstance(asset, ExportArtifact):
            title = f"加载中… {Path(asset.output_path).name}"
        self.title_label.setText(title)
        self.meta_label.setText("")
        self.warning_label.setText(clear_warning)
        self.message_label.set_message("正在生成预览…")
        self.stack.setCurrentWidget(self.message_label)
        self.current_mode = "loading"
        self.reader_mode_changed.emit("loading")

    def update_asset(self, asset: ResourceItem | ExportArtifact | None) -> None:
        # Sync path for direct panel tests; DataPage uses PreviewRequestController.
        self.render(self.provider.preview(asset))

    def render(self, result: PreviewResult) -> None:
        if result.mode == "geoviz" and isinstance(result.engine_preview, PreparedPreview):
            try:
                self.geoviz_host.render(result.engine_preview)
            except Exception as error:
                result = self._geoviz_failure_result(result, error)
                target = self._load_target_widget(result)
                self._commit_result(result, target)
                return
            self._commit_result(result, self.geoviz_host)
            return

        clear_warning = self._safe_clear_geoviz()
        if result.mode == "geoviz":
            result = replace(
                result,
                mode="message",
                message=result.message or "预览不可用",
                engine_preview=None,
                estimated_bytes=0,
            )
        if clear_warning:
            result = replace(
                result,
                warning=self._merge_warning(result.warning, clear_warning),
            )

        target = self._load_target_widget(result)
        self._commit_result(result, target)

    def _load_target_widget(self, result: PreviewResult):
        if result.mode == "empty":
            return self.empty_label

        if result.mode == "message":
            self.message_label.set_message(result.message)
            return self.message_label

        if result.mode == "text":
            self.text_preview.load_text(result.text)
            return self.text_preview

        if result.mode == "table":
            self.table_preview.load_table(result.table_headers, result.table_rows)
            return self.table_preview

        if result.mode == "well_log":
            self.well_log_preview.load_summary(
                result.summary_rows,
                result.table_headers,
                result.table_rows,
                result.message,
            )
            return self.well_log_preview

        if result.mode == "seismic":
            self.seismic_preview.load_summary(
                result.summary_rows,
                result.table_headers,
                result.table_rows,
                result.message,
            )
            return self.seismic_preview

        if result.mode == "image":
            self.image_preview_widget.load(
                result.path,
                result.revision,
                image_bytes=result.image_bytes,
            )
            return self.image_preview_widget

        if result.mode == "pdf":
            self.pdf_preview_widget.load(
                result.path,
                result.revision,
                pdf_bytes=result.pdf_bytes,
            )
            return self.pdf_preview_widget

        if result.mode == "rich_text":
            self.rich_text_preview.load_html(result.rich_html)
            return self.rich_text_preview

        if result.mode == "web_document":
            if self.web_document_preview is None:
                self.web_document_preview = WebDocumentPreviewWidget()
                self.stack.addWidget(self.web_document_preview)
            self.web_document_preview.load_document(result.path, result.rich_html)
            return self.web_document_preview

        if result.mode == "json_tree":
            self.json_tree_preview.load_payload(result.json_payload, result.json_truncated)
            return self.json_tree_preview

        if result.mode == "geotiff":
            self.geotiff_preview.load(
                result.path,
                result.revision,
                result.image_bytes,
                result.geo_metadata,
            )
            return self.geotiff_preview

        if result.mode == "media":
            # QMediaPlayer is UI-thread-only: the provider only returns the path;
            # setSource happens here on the UI thread.
            self.media_preview.set_media_path(result.media_path)
            return self.media_preview

        self.message_label.set_message(result.message or "预览不可用")
        return self.message_label

    def _commit_result(self, result: PreviewResult, target) -> None:
        self._current_result = result
        self.title_label.setText(result.title)
        self.meta_label.setText(self._meta_text(result))
        self.warning_label.setText(result.warning)
        self.stack.setCurrentWidget(target)
        self.current_mode = result.mode
        self.reader_mode_changed.emit(result.mode)

    def _safe_clear_geoviz(self) -> str:
        try:
            self.geoviz_host.clear()
        except Exception as error:
            return self._error_text(error)
        return ""

    def _geoviz_failure_result(
        self,
        result: PreviewResult,
        error: Exception,
    ) -> PreviewResult:
        return replace(
            result,
            mode="message",
            message=result.message or "预览不可用",
            warning=self._merge_warning(result.warning, self._error_text(error)),
            engine_preview=None,
            estimated_bytes=0,
        )

    @staticmethod
    def _merge_warning(existing: str, added: str) -> str:
        return " · ".join(part for part in (existing, added) if part)

    @staticmethod
    def _error_text(error: Exception) -> str:
        return str(error) or error.__class__.__name__

    def next_pdf_page(self) -> None:
        self.pdf_preview_widget.next_page()

    def previous_pdf_page(self) -> None:
        self.pdf_preview_widget.previous_page()

    def release_engine_widgets(self) -> None:
        try:
            self.geoviz_host.release_all()
        except Exception as error:
            result = self._geoviz_failure_result(self._current_result, error)
            self.message_label.set_message(result.message)
            self._commit_result(result, self.message_label)

    def _message_widget(self, text: str) -> MessagePreviewWidget:
        label = MessagePreviewWidget()
        label.set_message(text)
        return label

    def _meta_text(self, result: PreviewResult) -> str:
        parts = [part for part in [result.type_label, result.format, result.status, result.path] if part]
        return " · ".join(parts)
