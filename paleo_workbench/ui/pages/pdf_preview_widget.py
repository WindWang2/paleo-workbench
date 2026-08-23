from __future__ import annotations

from PySide6.QtCore import QBuffer, QByteArray, QEvent, QIODevice, QPointF, QSize, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui import tokens

try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:  # pragma: no cover
    QPdfDocument = None

try:
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:  # pragma: no cover
    QPdfView = None

_ZOOM_MIN = 10
_ZOOM_MAX = 800
_ZOOM_STEP = 1.25


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
        # 默认以宽度为主拉伸页面（连续滚动视图下最自然的阅读方式）
        self.fit_mode = "width"
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
        # fallback 连续页面：所有页按宽度渲染进滚动区
        self._fallback_page_labels: list[QLabel] = []
        self._fallback_pages = QWidget()
        self._fallback_pages_layout = QVBoxLayout(self._fallback_pages)
        self._fallback_pages_layout.setContentsMargins(0, 0, 0, 0)
        self._fallback_pages_layout.setSpacing(tokens.SPACE_1)
        self._fallback_scroll = QScrollArea(self)
        self._fallback_scroll.setWidgetResizable(True)
        self._fallback_scroll.setWidget(self._fallback_pages)
        scrollbar = self._fallback_scroll.verticalScrollBar()
        if scrollbar is not None:
            scrollbar.valueChanged.connect(self._on_fallback_scroll)
        self._content_stack.addWidget(self._fallback_scroll)
        self._content_stack.setCurrentWidget(self.pdf_view or self.fallback_image)
        layout.addWidget(self._content_stack, 1)

        controls = QHBoxLayout()
        controls.setSpacing(tokens.SPACE_2)
        self.prev_btn = QPushButton("上一页")
        self.prev_btn.setObjectName("SecondaryButton")
        self.prev_btn.clicked.connect(self.previous_page)
        self.page_label = QLabel("0 / 0")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.next_btn = QPushButton("下一页")
        self.next_btn.setObjectName("SecondaryButton")
        self.next_btn.clicked.connect(self.next_page)
        self.copy_all_btn = QPushButton("复制全部文本")
        self.copy_all_btn.setObjectName("SecondaryButton")
        self.copy_all_btn.clicked.connect(self._copy_all_text)

        # 缩放控件
        self.fit_page_btn = QPushButton("适应窗口")
        self.fit_page_btn.setObjectName("SecondaryButton")
        self.fit_page_btn.setCheckable(True)
        self.fit_width_btn = QPushButton("适应宽度")
        self.fit_width_btn.setObjectName("SecondaryButton")
        self.fit_width_btn.setCheckable(True)
        self.zoom_out_btn = QPushButton("−")
        self.zoom_out_btn.setObjectName("SecondaryButton")
        self.zoom_in_btn = QPushButton("+")
        self.zoom_in_btn.setObjectName("SecondaryButton")
        self.zoom_label = QLabel(f"{self.zoom_percent}%")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setMinimumWidth(48)

        self.fit_page_btn.clicked.connect(self._on_fit_page_clicked)
        self.fit_width_btn.clicked.connect(self._on_fit_width_clicked)
        self.zoom_out_btn.clicked.connect(self._zoom_out)
        self.zoom_in_btn.clicked.connect(self._zoom_in)

        controls.addWidget(self.prev_btn)
        controls.addWidget(self.page_label, 1)
        controls.addWidget(self.next_btn)
        controls.addWidget(self.fit_page_btn)
        controls.addWidget(self.fit_width_btn)
        controls.addWidget(self.zoom_out_btn)
        controls.addWidget(self.zoom_label)
        controls.addWidget(self.zoom_in_btn)
        controls.addWidget(self.copy_all_btn)
        layout.addLayout(controls)

        if self.pdf_view is not None:
            try:
                self.pdf_view.installEventFilter(self)
            except Exception:
                pass
            # 同步缩放百分比显示：监听 pageNavigator currentZoomChanged（fake 环境无此信号）
            try:
                navigator = self.pdf_view.pageNavigator()
                signal = getattr(navigator, "currentZoomChanged", None)
                if signal is not None:
                    signal.connect(self._on_current_zoom_changed)
                # 连续滚动时同步当前页码显示
                page_signal = getattr(navigator, "currentPageChanged", None)
                if page_signal is not None:
                    page_signal.connect(self._on_current_page_changed)
            except Exception:
                pass

        self._sync_zoom_ui()

        if self.document is None:
            self._show_fallback_message("PDF 预览不可用")
            self.page_label.setText("0 / 0")
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
            self.copy_all_btn.setEnabled(False)
            self.copy_all_btn.setVisible(False)

    # -- 缩放核心 --

    def _clamp_zoom(self, value: int) -> int:
        return max(_ZOOM_MIN, min(_ZOOM_MAX, int(value)))

    def _sync_zoom_ui(self) -> None:
        if hasattr(self, "zoom_label"):
            try:
                self.zoom_label.setText(f"{self.zoom_percent}%")
            except Exception:
                pass
        if hasattr(self, "fit_page_btn") and hasattr(self, "fit_width_btn"):
            try:
                self.fit_page_btn.blockSignals(True)
                self.fit_width_btn.blockSignals(True)
                self.fit_page_btn.setChecked(self.fit_mode == "page")
                self.fit_width_btn.setChecked(self.fit_mode == "width")
            finally:
                try:
                    self.fit_page_btn.blockSignals(False)
                except Exception:
                    pass
                try:
                    self.fit_width_btn.blockSignals(False)
                except Exception:
                    pass

    def _apply_fit_mode(self) -> None:
        self._sync_zoom_ui()
        if self.pdf_view is not None:
            try:
                import paleo_workbench.ui.pages.preview_widgets as preview_widgets
                view_cls = getattr(preview_widgets, "QPdfView", QPdfView)
                if view_cls is None:
                    view_cls = QPdfView
                if view_cls is not None and hasattr(view_cls, "ZoomMode") and hasattr(self.pdf_view, "setZoomMode"):
                    if self.fit_mode == "page":
                        self.pdf_view.setZoomMode(view_cls.ZoomMode.FitInView)
                    elif self.fit_mode == "width":
                        self.pdf_view.setZoomMode(view_cls.ZoomMode.FitToWidth)
            except Exception:
                pass
        else:
            # fallback 路径：重新渲染以反映 fit 切换（fit 下按基础尺寸渲染）
            if self._path and self.document is not None and self.document.pageCount() > 0:
                self._render_page()

    def _apply_custom_zoom(self) -> None:
        self._sync_zoom_ui()
        if self.pdf_view is not None:
            try:
                import paleo_workbench.ui.pages.preview_widgets as preview_widgets
                view_cls = getattr(preview_widgets, "QPdfView", QPdfView)
                if view_cls is None:
                    view_cls = QPdfView
                if view_cls is not None and hasattr(view_cls, "ZoomMode") and hasattr(self.pdf_view, "setZoomMode"):
                    self.pdf_view.setZoomMode(view_cls.ZoomMode.Custom)
                if hasattr(self.pdf_view, "setZoomFactor"):
                    self.pdf_view.setZoomFactor(self.zoom_percent / 100.0)
            except Exception:
                pass
        else:
            if self._path and self.document is not None and self.document.pageCount() > 0:
                self._render_page()

    def _on_fit_page_clicked(self) -> None:
        # 手写互斥：点击即进入 page 模式
        self.fit_mode = "page"
        self._apply_fit_mode()

    def _on_fit_width_clicked(self) -> None:
        self.fit_mode = "width"
        self._apply_fit_mode()

    def _zoom_in(self) -> None:
        new_percent = self._clamp_zoom(int(round(self.zoom_percent * _ZOOM_STEP)))
        if new_percent == self.zoom_percent:
            return
        self.zoom_percent = new_percent
        self.fit_mode = "custom"
        self._apply_custom_zoom()

    def _zoom_out(self) -> None:
        new_percent = self._clamp_zoom(int(round(self.zoom_percent / _ZOOM_STEP)))
        if new_percent == self.zoom_percent:
            # 已在边界，避免死循环
            return
        self.zoom_percent = new_percent
        self.fit_mode = "custom"
        self._apply_custom_zoom()

    def _on_current_zoom_changed(self, zoom: float) -> None:
        try:
            percent = int(round(float(zoom) * 100))
        except Exception:
            return
        percent = self._clamp_zoom(percent)
        # 仅更新标签显示，保持 fit_mode 不变（由交互逻辑驱动 fit_mode）
        self.zoom_percent = percent
        try:
            self.zoom_label.setText(f"{self.zoom_percent}%")
        except Exception:
            pass

    def _on_current_page_changed(self, page) -> None:
        """连续滚动模式下，QPdfView 滚动时同步页码显示。"""
        try:
            page = int(page)
        except Exception:
            return
        if page < 0 or page == self._page:
            return
        self._page = page
        self._update_page_status()

    def _update_page_status(self) -> None:
        page_count = 0
        if self.document is not None:
            try:
                page_count = self.document.pageCount()
            except Exception:
                page_count = 0
        self.page_label.setText(f"{self._page + 1} / {page_count}")
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < page_count - 1)

    def eventFilter(self, obj, event) -> bool:  # type: ignore[override]
        if obj is self.pdf_view and event.type() == QEvent.Type.Wheel:
            try:
                mods = event.modifiers()
            except Exception:
                mods = Qt.KeyboardModifier.NoModifier
            if mods & Qt.KeyboardModifier.ControlModifier:
                try:
                    delta = event.angleDelta().y()
                except Exception:
                    delta = 0
                # 滚轮向上放大，向下缩小
                if delta > 0:
                    self._zoom_in()
                elif delta < 0:
                    self._zoom_out()
                return True
        return super().eventFilter(obj, event)

    def apply_settings(self, settings) -> None:
        self.fit_mode = settings.pdf_fit_mode
        self.zoom_percent = self._clamp_zoom(settings.pdf_zoom_percent)
        self._sync_zoom_ui()
        if self.pdf_view is None or QPdfView is None:
            # fallback 仍需重绘以应用缩放
            if self.pdf_view is None and self.document is not None and self._path and self.document.pageCount() > 0:
                try:
                    self._render_page()
                except Exception:
                    pass
            return
        if not hasattr(self.pdf_view, "setZoomMode"):
            return
        import paleo_workbench.ui.pages.preview_widgets as preview_widgets
        view_cls = getattr(preview_widgets, "QPdfView", QPdfView)
        if view_cls is None:
            view_cls = QPdfView
        if view_cls is None or not hasattr(view_cls, "ZoomMode"):
            return
        try:
            if self.fit_mode == "page":
                self.pdf_view.setZoomMode(view_cls.ZoomMode.FitInView)
            elif self.fit_mode == "width":
                self.pdf_view.setZoomMode(view_cls.ZoomMode.FitToWidth)
            else:
                self.pdf_view.setZoomMode(view_cls.ZoomMode.Custom)
                if hasattr(self.pdf_view, "setZoomFactor"):
                    self.pdf_view.setZoomFactor(self.zoom_percent / 100.0)
        except Exception:
            pass

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
            self._goto_page()

    def previous_page(self) -> None:
        if self.document is None or self._load_failed:
            return
        if self._page > 0:
            self._page -= 1
            self._goto_page()

    def _goto_page(self) -> None:
        """连续模式下翻页 = 滚动定位到目标页，不重新渲染。"""
        if self.pdf_view is not None:
            navigator = self.pdf_view.pageNavigator()
            navigator.jump(self._page, QPointF(), navigator.currentZoom())
        elif 0 <= self._page < len(self._fallback_page_labels):
            label = self._fallback_page_labels[self._page]
            scrollbar = self._fallback_scroll.verticalScrollBar()
            if scrollbar is not None:
                scrollbar.setValue(label.y())
        self._update_page_status()

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
            import paleo_workbench.ui.pages.preview_widgets as preview_widgets
            view_cls = getattr(preview_widgets, "QPdfView", QPdfView)
            page_mode_cls = getattr(view_cls, "PageMode", None)
            # 连续页面滚动优先；旧 fake/环境无 MultiPage 时退回单页
            page_mode = getattr(page_mode_cls, "MultiPage", None)
            if page_mode is None:
                page_mode = getattr(page_mode_cls, "SinglePage", None)
            if hasattr(self.pdf_view, "setPageMode") and page_mode is not None:
                self.pdf_view.setPageMode(page_mode)
            navigator = self.pdf_view.pageNavigator()
            navigator.jump(self._page, QPointF(), navigator.currentZoom())
        else:
            self._render_fallback_pages()
        self._update_page_status()

    def _render_fallback_pages(self) -> None:
        """无 QPdfView 时的降级路径：所有页按宽度连续渲染进滚动区。"""
        assert self.document is not None
        page_count = self.document.pageCount()
        try:
            factor = self.zoom_percent / 100.0
        except Exception:
            factor = 1.0
        viewport = self._fallback_scroll.viewport()
        base_w = max(
            viewport.width() if viewport is not None else 0,
            self.width(),
            420,
        )
        width = max(1, int(base_w * factor))
        point_size = getattr(self.document, "pagePointSize", None)
        first_failed = False
        for i in range(page_count):
            height = 0
            if callable(point_size):
                try:
                    ps = point_size(i)
                    if ps.width() > 0:
                        height = int(width * ps.height() / ps.width())
                except Exception:
                    height = 0
            if height <= 0:
                height = int(width * 1.414)  # 默认 A4 纵向纵横比
            image = self.document.render(i, QSize(width, height))
            if i == 0 and (image is None or image.isNull()):
                first_failed = True
                break
            label = self._ensure_fallback_label(i)
            if image is None or image.isNull():
                label.setText(f"第 {i + 1} 页渲染失败")
            else:
                label.setPixmap(QPixmap.fromImage(image))
        if first_failed:
            self._show_fallback_message("PDF 页面渲染失败")
            return
        # 尾页裁掉多余的 label（换到页数更少的文档时）
        while len(self._fallback_page_labels) > page_count:
            label = self._fallback_page_labels.pop()
            self._fallback_pages_layout.removeWidget(label)
            label.deleteLater()
        self._content_stack.setCurrentWidget(self._fallback_scroll)

    def _ensure_fallback_label(self, index: int) -> QLabel:
        while len(self._fallback_page_labels) <= index:
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet(f"background: {tokens.BG_HEADER};")
            self._fallback_pages_layout.addWidget(label)
            self._fallback_page_labels.append(label)
        return self._fallback_page_labels[index]

    def _on_fallback_scroll(self, value: int) -> None:
        """fallback 连续滚动时按可视区中点更新当前页码。"""
        if not self._fallback_page_labels:
            return
        viewport = self._fallback_scroll.viewport()
        midpoint = value + (viewport.height() // 2 if viewport is not None else 0)
        page = 0
        for idx, label in enumerate(self._fallback_page_labels):
            if midpoint >= label.y():
                page = idx
        if page != self._page:
            self._page = page
            self._update_page_status()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._path and self.pdf_view is None and self.document is not None and self.document.pageCount() > 0:
            self._render_page()

    def _copy_all_text(self) -> None:
        if self.document is None:
            return
        try:
            page_count = self.document.pageCount()
        except Exception:
            return
        if page_count <= 0:
            return
        texts: list[str] = []
        for i in range(page_count):
            try:
                sel = self.document.getAllText(i)
            except Exception:
                texts.append("")
                continue
            if sel is None:
                texts.append("")
                continue
            if isinstance(sel, str):
                texts.append(sel)
                continue
            # QPdfSelection case: .text is a method returning str
            t_attr = getattr(sel, "text", None)
            if callable(t_attr):
                try:
                    txt = t_attr()
                except Exception:
                    txt = str(sel)
                texts.append(txt if isinstance(txt, str) else str(txt))
            elif isinstance(t_attr, str):
                texts.append(t_attr)
            elif t_attr is not None:
                texts.append(str(t_attr))
            else:
                texts.append(str(sel))
        full = "\n".join(texts)
        truncated = False
        if len(full) > 1_000_000:
            full = full[:1_000_000]
            truncated = True
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(full)
        # feedback
        self.copy_all_btn.setText("已复制（已截断）" if truncated else "已复制")

        def _restore_copy_btn_text() -> None:
            try:
                self.copy_all_btn.setText("复制全部文本")
            except RuntimeError:
                # Widget may already be destroyed when the timer fires (tests).
                pass

        QTimer.singleShot(1500, _restore_copy_btn_text)

    def _show_fallback_message(self, text: str) -> None:
        self.fallback_image.clear()
        self.fallback_image.setText(text)
        self._content_stack.setCurrentWidget(self.fallback_image)
