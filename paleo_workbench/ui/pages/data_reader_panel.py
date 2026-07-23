from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
)


from paleo_workbench.project.models import ExportArtifact, ResourceItem
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.lazy_visualization_tabs import LazyVisualizationTabs
from paleo_workbench.ui.pages.preview_provider import PreviewProvider, PreviewResult
from paleo_workbench.ui.pages.preview_settings import PreviewSettingsStore
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
    SeismicSlicePreviewWidget,
)


class DataReaderPanel(QFrame):
    reader_mode_changed = Signal(str)
    preview_settings_changed = Signal(object)
    visualization_requested = Signal()

    def __init__(
        self,
        provider: PreviewProvider | None = None,
        parent=None,
        *,
        settings_store: PreviewSettingsStore | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("DataReaderPanel")
        self.setMinimumWidth(320)
        # Default to LocalVisualizationProvider (contract + geoviz previews), but
        # import it lazily so cold DataPage startup does not pay the geoviz cost
        # when a custom lightweight provider is injected by tests.
        self._settings_store = settings_store or PreviewSettingsStore()
        self.preview_settings = self._settings_store.load()
        if provider is None:
            # Deferred: pulls in geoviz engine stack; keep startup cost lazy.
            from paleo_workbench.ui.pages.geoviz_preview_provider import (
                LocalVisualizationProvider,
            )

            provider = LocalVisualizationProvider(settings=self.preview_settings)
        self.provider = provider.with_settings(self.preview_settings)
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

        # Host stays uncreated until the visualization tab has produced a
        # PreparedPreview on the UI thread.
        self._geoviz_host = None
        self.lazy_visualization_tabs = LazyVisualizationTabs(
            getattr(self.provider, "engine", None)
        )
        self.lazy_visualization_tabs.visualization_requested.connect(
            self.visualization_requested
        )
        self.stack.addWidget(self.lazy_visualization_tabs)

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

        self.seismic_preview = SeismicSlicePreviewWidget()
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
        self.apply_preview_settings(self.preview_settings)

        # Dispatch table for _load_target_widget: each handler loads the result
        # into its widget and returns the widget. Unknown modes fall through to
        # _render_message (the message_label fallback).
        self._mode_handlers: dict[str, callable] = {
            "empty": self._render_empty,
            "message": self._render_message,
            "text": self._render_text,
            "table": self._render_table,
            "well_log": self._render_well_log,
            "seismic": self._render_seismic,
            "image": self._render_image,
            "pdf": self._render_pdf,
            "rich_text": self._render_rich_text,
            "web_document": self._render_web_document,
            "json_tree": self._render_json_tree,
            "geotiff": self._render_geotiff,
            "media": self._render_media,
        }

    def show_loading(self, asset: ResourceItem | ExportArtifact | None = None) -> None:
        self._stop_media_if_needed()
        clear_warning = self._safe_clear_geoviz()
        self.lazy_visualization_tabs.reset()
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
        self.render(self.provider.preview_summary(asset))

    @property
    def geoviz_host(self):
        """Lazily create the GeoViz preview host (defers heavy geoviz import)."""
        if self._geoviz_host is None:
            # Deferred: pulls in geoviz engine stack; keep startup cost lazy.
            from paleo_workbench.ui.pages.geoviz_preview_provider import (
                LocalVisualizationProvider,
            )

            if not hasattr(self.provider, "engine"):
                self.provider = LocalVisualizationProvider(
                    settings=self.preview_settings
                )
            provider_engine = getattr(self.provider, "engine", None)
            self.lazy_visualization_tabs.set_engine(provider_engine)
            self._geoviz_host = self.lazy_visualization_tabs.host
        return self._geoviz_host

    @staticmethod
    def _is_prepared_preview(preview) -> bool:
        if preview is None:
            return False
        try:
            from geoviz import PreparedPreview
        except ImportError:  # pragma: no cover
            return False
        return isinstance(preview, PreparedPreview)

    def render(self, result: PreviewResult) -> None:
        if result.mode != "media":
            self._stop_media_if_needed()
        if result.visualization_available and result.mode != "geoviz" and result.mode != "seismic":
            clear_warning = self._safe_clear_geoviz()
            if clear_warning:
                result = replace(
                    result,
                    warning=self._merge_warning(result.warning, clear_warning),
                )
            self.lazy_visualization_tabs.load_summary(result)
            self._commit_result(result, self.lazy_visualization_tabs)
            return
        # Only PreparedPreview payloads enter the engine path; raw dicts/objects
        # fall through to clear + message (same contract as pre-lazy-load).
        if result.mode == "geoviz" and self._is_prepared_preview(result.engine_preview):
            try:
                self.lazy_visualization_tabs.load_summary(result)
                # Keep the owner-side reference even when host.render() raises;
                # cleanup and subsequent diagnostics must not try to recreate it.
                self.geoviz_host
                self.lazy_visualization_tabs.show_preview(result.engine_preview)
            except Exception as error:
                result = self._geoviz_failure_result(result, error)
                target = self._load_target_widget(result)
                self._commit_result(result, target)
                return
            self._commit_result(result, self.lazy_visualization_tabs)
            return

        clear_warning = self._safe_clear_geoviz()
        self.lazy_visualization_tabs.reset()
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

    def show_visualization_loading(self) -> None:
        self.lazy_visualization_tabs.show_loading()

    def show_visualization_error(
        self,
        message: str,
        *,
        retryable: bool = True,
    ) -> None:
        self.lazy_visualization_tabs.show_error(message, retryable=retryable)

    def render_visualization(self, result: PreviewResult) -> None:
        if result.mode != "geoviz" or not self._is_prepared_preview(
            result.engine_preview
        ):
            self.show_visualization_error(
                result.message or "可视化预览不可用",
                retryable=result.retryable,
            )
            if result.warning:
                self.warning_label.setText(
                    self._merge_warning(self.warning_label.text(), result.warning)
                )
            return
        try:
            self.geoviz_host
            self.lazy_visualization_tabs.show_preview(
                result.engine_preview,
                activate=False,
            )
        except Exception as error:
            self.show_visualization_error(self._error_text(error))
            return
        if result.warning:
            self.warning_label.setText(
                self._merge_warning(self.warning_label.text(), result.warning)
            )

    def _stop_media_if_needed(self) -> None:
        stop = getattr(self.media_preview, "stop", None)
        if callable(stop):
            stop()

    def _load_target_widget(self, result: PreviewResult):
        handler = self._mode_handlers.get(result.mode)
        if handler is None:
            self.message_label.set_message(result.message or "预览不可用")
            return self.message_label
        return handler(result)

    def _render_empty(self, result: PreviewResult):
        return self.empty_label

    def _render_message(self, result: PreviewResult):
        self.message_label.set_message(result.message)
        return self.message_label

    def _render_text(self, result: PreviewResult):
        self.text_preview.load_text(result.text)
        return self.text_preview

    def _render_table(self, result: PreviewResult):
        self.table_preview.load_table(result.table_headers, result.table_rows)
        return self.table_preview

    def _render_well_log(self, result: PreviewResult):
        self.well_log_preview.load_summary(
            result.summary_rows,
            result.table_headers,
            result.table_rows,
            result.message,
            data_headers=getattr(result, "data_headers", ()),
            data_rows=getattr(result, "data_rows", ()),
        )
        return self.well_log_preview

    def _render_seismic(self, result: PreviewResult):
        self.seismic_preview.load_seismic(
            result.path,
            result.revision,
            getattr(result, "seismic_volume", None),
            result.message,
        )
        return self.seismic_preview

    def _render_image(self, result: PreviewResult):
        self.image_preview_widget.load(
            result.path,
            result.revision,
            image_bytes=result.image_bytes,
        )
        return self.image_preview_widget

    def _render_pdf(self, result: PreviewResult):
        self.pdf_preview_widget.load(
            result.path,
            result.revision,
            pdf_bytes=result.pdf_bytes,
        )
        return self.pdf_preview_widget

    def _render_rich_text(self, result: PreviewResult):
        self.rich_text_preview.load_html(result.rich_html)
        return self.rich_text_preview

    def _render_web_document(self, result: PreviewResult):
        if self.web_document_preview is None:
            self.web_document_preview = WebDocumentPreviewWidget()
            apply_settings = getattr(
                self.web_document_preview,
                "apply_settings",
                None,
            )
            if callable(apply_settings):
                apply_settings(self.preview_settings)
            self.stack.addWidget(self.web_document_preview)
        self.web_document_preview.load_document(result.path, result.rich_html)
        return self.web_document_preview

    def _render_json_tree(self, result: PreviewResult):
        self.json_tree_preview.load_payload(result.json_payload, result.json_truncated)
        return self.json_tree_preview

    def _render_geotiff(self, result: PreviewResult):
        self.geotiff_preview.load(
            result.path,
            result.revision,
            result.image_bytes,
            result.geo_metadata,
        )
        return self.geotiff_preview

    def _render_media(self, result: PreviewResult):
        # QMediaPlayer is UI-thread-only: the provider only returns the path;
        # setSource happens here on the UI thread.
        self.media_preview.set_media_path(result.media_path)
        return self.media_preview

    def _commit_result(self, result: PreviewResult, target) -> None:
        self._current_result = result
        self.title_label.setText(result.title)
        self.meta_label.setText(self._meta_text(result))
        self.warning_label.setText(result.warning)
        self.stack.setCurrentWidget(target)
        self.current_mode = result.mode
        self.reader_mode_changed.emit(result.mode)

    def apply_preview_settings(self, settings) -> None:
        self.preview_settings = settings
        self.meta_label.setVisible(settings.show_metadata)
        for widget in (
            self.text_preview,
            self.rich_text_preview,
            self.table_preview,
            self.well_log_preview,
            self.seismic_preview,
            self.image_preview_widget,
            self.pdf_preview_widget,
            self.json_tree_preview,
            self.geotiff_preview,
            self.media_preview,
            self.lazy_visualization_tabs,
        ):
            apply = getattr(widget, "apply_settings", None)
            if callable(apply):
                apply(settings)
        if self.web_document_preview is not None:
            self.web_document_preview.apply_settings(settings)

    def set_preview_settings(self, settings) -> None:
        """Apply settings supplied by the application-level dialog."""
        self.provider = self.provider.with_settings(settings)
        self.apply_preview_settings(settings)
        self.preview_settings_changed.emit(settings)

    def _safe_clear_geoviz(self) -> str:
        # Do not force-create the host just to clear an empty state.
        host = self._geoviz_host
        if host is None:
            return ""
        try:
            host.clear()
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
        self._stop_media_if_needed()
        if self._geoviz_host is None:
            return
        try:
            self._geoviz_host.release_all()
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
