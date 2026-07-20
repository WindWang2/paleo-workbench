from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:  # pragma: no cover
    QPdfDocument = None

try:
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:  # pragma: no cover
    QPdfView = None


class PdfPreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        import paleo_workbench.ui.pages.preview_widgets as preview_widgets
        doc_cls = getattr(preview_widgets, "QPdfDocument", QPdfDocument)
        view_cls = getattr(preview_widgets, "QPdfView", QPdfView)
        self.document = doc_cls(self) if doc_cls is not None else None
        self.pdf_view = view_cls(self) if view_cls is not None and self.document is not None else None
        self.fallback_image = QLabel()
        self.fallback_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._content_stack = QStackedWidget(self)
        self._page = 0
        self._path = ""
        self._revision: tuple[object, ...] | None = None
        self._load_failed = False
        self._load_pending = False
        self._source_buffer: QBuffer | None = None
        self.fit_mode = "page"
        self.zoom_percent = 100

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if self.pdf_view is not None:
            self.pdf_view.setDocument(self.document)
            self._content_stack.addWidget(self.pdf_view)
        status_changed = getattr(self.document, "statusChanged", None)
        if status_changed is not None:
            status_changed.connect(self._on_document_status_changed)
        self._content_stack.addWidget(self.fallback_image)
        self._content_stack.setCurrentWidget(self.pdf_view or self.fallback_image)
        layout.addWidget(self._content_stack, 1)

        controls = QHBoxLayout()
        self.prev_btn = QPushButton("上一页")
        self.prev_btn.setObjectName("SecondaryButton")
        self.prev_btn.clicked.connect(self.previous_page)
        self.page_label = QLabel("0 / 0")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_btn = QPushButton("下一页")
        self.next_btn.setObjectName("SecondaryButton")
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

    def apply_settings(self, settings) -> None:
        self.fit_mode = settings.pdf_fit_mode
        self.zoom_percent = settings.pdf_zoom_percent
        if self.pdf_view is None or QPdfView is None:
            return
        if not hasattr(self.pdf_view, "setZoomMode") or not hasattr(QPdfView, "ZoomMode"):
            return
        if self.fit_mode == "page":
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitInView)
        elif self.fit_mode == "width":
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        else:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
            self.pdf_view.setZoomFactor(self.zoom_percent / 100.0)

    def load(
        self,
        path: str,
        revision: tuple[object, ...] | None = None,
        preloaded_image=None,
        pdf_bytes: bytes = b"",
    ) -> None:
        del preloaded_image
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
            self._load_pending = True
            load_result = self._load_document(path, pdf_bytes)
            self._finish_document_load(load_result)
            return
        if self._load_pending:
            return
        if self._load_failed:
            self._show_fallback_message("PDF 预览加载失败")
            self.page_label.setText("0 / 0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        self._render_page()

    def _load_document(self, path: str, pdf_bytes: bytes):
        assert self.document is not None
        self._release_source_buffer()
        if pdf_bytes:
            buffer = QBuffer(self)
            buffer.setData(QByteArray(pdf_bytes))
            if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
                return self.document.load(path)
            self._source_buffer = buffer
            return self.document.load(buffer)
        return self.document.load(path)

    def _on_document_status_changed(self, status) -> None:
        import paleo_workbench.ui.pages.preview_widgets as preview_widgets
        doc_cls = getattr(preview_widgets, "QPdfDocument", QPdfDocument)
        status_type = getattr(doc_cls, "Status", None)
        if status_type is None or status in (getattr(status_type, "Ready", None), getattr(status_type, "Error", None)):
            self._finish_document_load()

    def _finish_document_load(self, load_result=None) -> None:
        """Resolve both QPdfDocument load overloads from document state."""
        if self.document is None:
            return
        import paleo_workbench.ui.pages.preview_widgets as preview_widgets
        doc_cls = getattr(preview_widgets, "QPdfDocument", QPdfDocument)
        status_type = getattr(doc_cls, "Status", None)
        status_getter = getattr(self.document, "status", None)
        status = status_getter() if callable(status_getter) else None
        if status_type is not None and status == getattr(status_type, "Loading", None):
            self._load_pending = True
            self._show_fallback_message("PDF 预览加载中…")
            self.page_label.setText("0 / 0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return

        no_error = getattr(getattr(doc_cls, "Error", None), "None_", 0)
        document_error = getattr(self.document, "error", None)
        current_error = document_error() if callable(document_error) else no_error
        failed = (
            (load_result is not None and load_result != no_error)
            or (status_type is not None and status == getattr(status_type, "Error", None))
            or current_error != no_error
            or self.document.pageCount() <= 0
        )
        self._load_pending = False
        self._load_failed = failed
        if failed:
            self._show_fallback_message("PDF 预览加载失败")
            self.page_label.setText("0 / 0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            return
        self._render_page()

    def _release_source_buffer(self) -> None:
        if self._source_buffer is not None:
            self._source_buffer.close()
            self._source_buffer.deleteLater()
            self._source_buffer = None

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
