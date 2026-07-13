from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QSize, Qt, QUrl
from PySide6.QtGui import QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
try:
    from PySide6.QtPdf import QPdfDocument
except ImportError:  # pragma: no cover
    QPdfDocument = None

try:
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:  # pragma: no cover
    QPdfView = None

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except ImportError:  # pragma: no cover
    QAudioOutput = None
    QMediaPlayer = None

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QTextEdit,
    QTreeView,
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


class _LocalOnlyRequestInterceptor(QWebEngineUrlRequestInterceptor):
    """Block WebEngine resource requests outside the local document sandbox."""

    _ALLOWED_SCHEMES = {"file", "data", "about", "blob"}

    def interceptRequest(self, info) -> None:
        if info.requestUrl().scheme() not in self._ALLOWED_SCHEMES:
            info.block(True)


class _LocalOnlyPage(QWebEnginePage):
    """Reject user-initiated navigation away from local document content."""

    _ALLOWED_SCHEMES = {"file", "data", "about", "blob"}

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        del navigation_type, is_main_frame
        return url.scheme() in self._ALLOWED_SCHEMES


class WebDocumentPreviewWidget(QWebEngineView):
    """Render local HTML or bounded Markdown output without network access."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._profile = QWebEngineProfile(self)
        self._interceptor = _LocalOnlyRequestInterceptor(self)
        self._profile.setUrlRequestInterceptor(self._interceptor)
        self._page = _LocalOnlyPage(self._profile, self)
        self.setPage(self._page)
        self.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            False,
        )

    def load_document(self, path: str, html: str = "") -> None:
        base_url = QUrl.fromLocalFile(str(Path(path).parent) + "/")
        if html:
            self.setHtml(html, base_url)
        else:
            self.load(QUrl.fromLocalFile(path))


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

    def load(
        self,
        path: str,
        revision: tuple[object, ...] | None = None,
        image_bytes: bytes = b"",
    ) -> None:
        if path != self._path or revision != self._revision or self._pixmap is None:
            self._path = path
            self._revision = revision
            if image_bytes:
                # Bytes were read off-thread; decode here without re-opening the file.
                self._pixmap = QPixmap()
                self._pixmap.loadFromData(image_bytes)
            else:
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
        # Keep buffer alive for the lifetime of a QPdfDocument loaded from bytes.
        self._source_buffer: QBuffer | None = None

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

    def load(
        self,
        path: str,
        revision: tuple[object, ...] | None = None,
        preloaded_image=None,
        pdf_bytes: bytes = b"",
    ) -> None:
        # QPdfDocument stays on the UI thread (not worker-safe). File bytes should
        # arrive pre-read off-thread so the UI only parses/renders.
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
            error = self._load_document(path, pdf_bytes)
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

    def _load_document(self, path: str, pdf_bytes: bytes):
        """Load from pre-read bytes when available; fall back to path."""
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


class GeoTiffPreviewWidget(QWidget):
    """GeoTIFF thumbnail + geographic metadata summary table.

    The PNG thumbnail bytes are produced off-thread by the preview provider;
    this widget only decodes them on the UI thread (mirroring
    :class:`ImagePreviewWidget`). The metadata table reuses
    :class:`TablePreviewWidget`.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumHeight(160)
        layout.addWidget(self._image_label, 1)
        self.summary_table = TablePreviewWidget()
        layout.addWidget(self.summary_table)
        self._pixmap: QPixmap | None = None

    def load(
        self,
        path: str,
        revision: tuple[object, ...] | None,
        image_bytes: bytes,
        geo_metadata: tuple[tuple[str, str], ...],
    ) -> None:
        del path, revision  # revision tracked upstream; bytes are pre-read
        headers = ("属性", "值")
        rows = tuple(geo_metadata) if geo_metadata else ()
        self.summary_table.load_table(headers, rows)
        self._pixmap = QPixmap()
        if image_bytes:
            self._pixmap.loadFromData(image_bytes)
        self._render_thumbnail()

    def pixmap(self) -> QPixmap | None:
        """Expose the decoded thumbnail pixmap (mirrors QLabel.pixmap)."""
        return self._pixmap

    def _render_thumbnail(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            self._image_label.setText("缩略图不可用")
            return
        self._image_label.setPixmap(
            self._pixmap.scaled(
                max(self._image_label.width(), 240),
                max(self._image_label.height(), 160),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_thumbnail()


class JsonTreePreviewWidget(QTreeView):
    """Collapsible tree view for parsed JSON/GeoJSON payloads.

    Arrays longer than ``JSON_ARRAY_COLLAPSE_THRESHOLD`` render as a single
    ``"[N items]"`` node that populates children lazily when expanded. This
    keeps the visible tree cheap for huge arrays — the full list is stashed in
    :attr:`Qt.ItemDataRole.UserRole` on the key item and only materialized into
    child rows the first time the user expands that node.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(False)
        self._model = QStandardItemModel()
        self._model.setHorizontalHeaderLabels(["键", "值/类型"])
        self.setModel(self._model)
        self.expanded.connect(self._on_expanded)

    def load_payload(self, payload: object, truncated: bool = False) -> None:
        self._model.clear()
        self._model.setHorizontalHeaderLabels(["键", "值/类型"])
        root = self._model.invisibleRootItem()
        if isinstance(payload, dict):
            for key, value in payload.items():
                root.appendRow(self._build_row(str(key), value))
        elif isinstance(payload, list):
            root.appendRow(self._build_row("[root]", payload))
        else:
            root.appendRow(self._build_row("[root]", payload))

    def _build_row(self, key: str, value: object):
        from paleo_workbench.ui.pages.preview_provider import JSON_ARRAY_COLLAPSE_THRESHOLD

        key_item = QStandardItem(key)
        if isinstance(value, dict):
            val_item = QStandardItem(f"{{object · {len(value)} keys}}")
            val_item.setEditable(False)
            for k, v in value.items():
                key_item.appendRow(self._build_row(str(k), v))
            return [key_item, val_item]
        if isinstance(value, list):
            if len(value) > JSON_ARRAY_COLLAPSE_THRESHOLD:
                # Collapsed placeholder: store the full list for lazy expansion.
                # The expanded-signal handler materializes children on demand.
                val_item = QStandardItem(f"[{len(value)} items]")
                val_item.setEditable(False)
                key_item.setEditable(False)
                key_item.setData(value, Qt.ItemDataRole.UserRole)
                return [key_item, val_item]
            val_item = QStandardItem(f"[list · {len(value)}]")
            val_item.setEditable(False)
            for i, v in enumerate(value):
                key_item.appendRow(self._build_row(str(i), v))
            return [key_item, val_item]
        # scalar
        val_item = QStandardItem(str(value))
        val_item.setEditable(False)
        key_item.setEditable(False)
        return [key_item, val_item]

    def _on_expanded(self, index):
        """Lazily populate children for a collapsed-array node on first expand."""
        item = self._model.itemFromIndex(index)
        stored = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(stored, list) and item.rowCount() == 0:
            for i, v in enumerate(stored):
                item.appendRow(self._build_row(str(i), v))


class MediaPreviewWidget(QWidget):
    """Inline audio player (wav/mp3/flac). QMediaPlayer is UI-thread only.

    The provider only returns the file path; the QMediaPlayer/QAudioOutput live
    on the UI thread and the media source is set here in :meth:`set_media_path`.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = QMediaPlayer(self) if QMediaPlayer is not None else None
        self._audio_out = QAudioOutput(self) if QAudioOutput is not None else None
        if self._player is not None and self._audio_out is not None:
            self._player.setAudioOutput(self._audio_out)
            self._audio_out.setVolume(0.8)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.status_label = QLabel("未加载")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        controls = QHBoxLayout()
        self.play_btn = QPushButton("播放")
        self.play_btn.clicked.connect(self._toggle_play)
        controls.addWidget(self.play_btn)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        controls.addWidget(self.position_slider, 1)
        self.time_label = QLabel("00:00 / 00:00")
        controls.addWidget(self.time_label)
        layout.addLayout(controls)

        vol = QHBoxLayout()
        vol.addWidget(QLabel("音量"))
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        vol.addWidget(self.volume_slider, 1)
        layout.addLayout(vol)
        layout.addStretch()

        if self._player is None:
            # No QtMultimedia backend available — keep the widget usable as a
            # status surface but never let play be triggered.
            self.status_label.setText("音频预览不可用")
            self.play_btn.setEnabled(False)
            return

        self.position_slider.sliderMoved.connect(self._player.setPosition)
        self.volume_slider.valueChanged.connect(
            lambda v: self._audio_out.setVolume(v / 100.0)
        )
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.errorOccurred.connect(self._on_error)

    def set_media_path(self, path: str) -> None:
        from PySide6.QtCore import QUrl

        if self._player is None:
            self.status_label.setText("音频预览不可用")
            self.play_btn.setEnabled(False)
            return
        if not path:
            self.status_label.setText("未加载")
            self.play_btn.setEnabled(False)
            return
        # setSource is UI-thread only; never call this off the UI thread.
        self._player.setSource(QUrl.fromLocalFile(path))
        self.status_label.setText("就绪")
        self.play_btn.setEnabled(True)
        self.play_btn.setText("播放")

    def _toggle_play(self) -> None:
        if self._player is None:
            return
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self.play_btn.setText("播放")
        else:
            self._player.play()
            self.play_btn.setText("暂停")

    def _on_position(self, ms: int) -> None:
        self.position_slider.setValue(ms)
        self._update_time(ms, self._player.duration())

    def _on_duration(self, ms: int) -> None:
        self.position_slider.setRange(0, ms)
        self._update_time(self._player.position(), ms)

    def _on_error(self, _error, msg: str) -> None:
        # Codec/backend missing under offscreen or no-decoder environments.
        self.status_label.setText("无法播放此格式（缺少解码器）")
        self.play_btn.setEnabled(False)

    def _update_time(self, pos: int, dur: int) -> None:
        self.time_label.setText(f"{self._ms(pos)} / {self._ms(dur)}")

    @staticmethod
    def _ms(ms: int) -> str:
        s = ms // 1000
        return f"{s // 60:02d}:{s % 60:02d}"
