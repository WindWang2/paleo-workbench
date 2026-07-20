from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedWidget, QTabWidget

from paleo_workbench.ui.pages.preview_provider import PreviewResult
from paleo_workbench.ui.pages.preview_widgets import (
    MessagePreviewWidget,
    TablePreviewWidget,
    TextPreviewWidget,
    SummaryTablePreviewWidget,
)


class LazyVisualizationTabs(QTabWidget):
    """Data list plus an explicitly activated professional visualization."""

    visualization_requested = Signal()

    def __init__(self, engine=None, parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._host = None
        self._requested = False

        self.summary = TablePreviewWidget()
        self.text = TextPreviewWidget()
        self.well_log_summary = SummaryTablePreviewWidget()
        self.summary_stack = QStackedWidget()
        self.summary_stack.addWidget(self.summary)
        self.summary_stack.addWidget(self.text)
        self.summary_stack.addWidget(self.well_log_summary)
        self.addTab(self.summary_stack, "数据列表")

        self.visual_stack = QStackedWidget()
        self.prompt_label = MessagePreviewWidget()
        self.prompt_label.set_message("点击此选项卡生成可视化预览")
        self.loading_label = MessagePreviewWidget()
        self.loading_label.set_message("正在生成可视化预览…")
        self.message_label = MessagePreviewWidget()
        self.visual_stack.addWidget(self.prompt_label)
        self.visual_stack.addWidget(self.loading_label)
        self.visual_stack.addWidget(self.message_label)
        self.addTab(self.visual_stack, "可视化预览")

        self.currentChanged.connect(self._on_current_changed)
        self.setCurrentIndex(0)

    @property
    def host(self):
        if self._host is None:
            from paleo_workbench.viz.hosts.geoviz_preview_host import GeoVizPreviewHost

            self._host = GeoVizPreviewHost(self._engine)
            self.visual_stack.addWidget(self._host)
        return self._host

    def set_engine(self, engine) -> None:
        if self._host is not None:
            raise RuntimeError("cannot replace engine after visualization host creation")
        self._engine = engine

    def load_summary(self, result: PreviewResult) -> None:
        if result.mode == "text":
            self.text.load_text(result.text)
            self.summary_stack.setCurrentWidget(self.text)
        elif result.mode == "well_log":
            self.well_log_summary.load_summary(
                result.summary_rows,
                result.table_headers,
                result.table_rows,
                result.message,
                data_headers=getattr(result, "data_headers", ()),
                data_rows=getattr(result, "data_rows", ()),
            )
            self.summary_stack.setCurrentWidget(self.well_log_summary)
        else:
            self.summary.load_table(result.table_headers, result.table_rows)
            self.summary_stack.setCurrentWidget(self.summary)
        self._requested = False
        self.visual_stack.setCurrentWidget(self.prompt_label)
        self.setCurrentIndex(0)

    def show_loading(self) -> None:
        self._requested = True
        self.visual_stack.setCurrentWidget(self.loading_label)
        self.setCurrentIndex(1)

    def show_preview(self, prepared, *, activate: bool = True) -> None:
        was_visual = self.currentIndex() == 1
        self._requested = True
        host = self.host
        host.render(prepared)
        self.visual_stack.setCurrentWidget(host)
        if activate or was_visual:
            self.setCurrentIndex(1)

    def show_error(
        self,
        message: str,
        *,
        retryable: bool = True,
        activate: bool = False,
    ) -> None:
        was_visual = self.currentIndex() == 1
        self._requested = not retryable
        self.message_label.set_message(message or "可视化预览不可用")
        self.visual_stack.setCurrentWidget(self.message_label)
        if activate or was_visual:
            self.setCurrentIndex(1)

    def reset(self) -> None:
        self._requested = False
        self.visual_stack.setCurrentWidget(self.prompt_label)
        self.setCurrentIndex(0)

    def clear_host(self) -> None:
        if self._host is not None:
            self._host.clear()

    def release_all(self) -> None:
        if self._host is not None:
            self._host.release_all()
        self.reset()

    def apply_settings(self, settings) -> None:
        for widget in (self.summary, self.text, self.well_log_summary):
            apply = getattr(widget, "apply_settings", None)
            if callable(apply):
                apply(settings)

    def _on_current_changed(self, index: int) -> None:
        if index != 1 or self._requested:
            return
        self._requested = True
        self.visualization_requested.emit()
