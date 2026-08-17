from __future__ import annotations

from PySide6.QtCore import QSize, QTimer, Qt
from PySide6.QtGui import QImageReader, QPixmap
from PySide6.QtWidgets import QLabel

# Preview never needs more than this many pixels on the long side: JPEG
# decoders scale during the DCT pass (a multi-megapixel source decodes in
# a fraction of the full-resolution time), and every later rescale starts
# from a bounded source instead of the full bitmap (#530).
_PREVIEW_MAX_LONG_SIDE = 2048

_RESIZE_DEBOUNCE_MS = 80


class ImagePreviewWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._path = ""
        self._revision: tuple[object, ...] | None = None
        self._pixmap: QPixmap | None = None
        self.transformation_mode = Qt.TransformationMode.SmoothTransformation
        self._scaled_key: tuple[object, ...] | None = None
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(_RESIZE_DEBOUNCE_MS)
        self._resize_timer.timeout.connect(self.render_current)

    def apply_settings(self, settings) -> None:
        self.transformation_mode = (
            Qt.TransformationMode.SmoothTransformation
            if settings.smooth_images
            else Qt.TransformationMode.FastTransformation
        )
        self.render_current()

    @staticmethod
    def _decode_bounded(source) -> QPixmap | None:
        """Decode through QImageReader with a bounded scaled size.

        ``source`` is raw bytes or a file path. Scaling during the decode
        keeps both the decode time and the memory bounded for
        multi-megapixel images; returns None when the source is undecodable
        (the caller then shows the failure text).
        """
        if isinstance(source, (bytes, bytearray)):
            from PySide6.QtCore import QBuffer, QIODevice

            buf = QBuffer()
            buf.setData(bytes(source))
            buf.open(QIODevice.OpenModeFlag.ReadOnly)
            reader = QImageReader(buf)
        else:
            reader = QImageReader(str(source))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > _PREVIEW_MAX_LONG_SIDE:
            scaled = size.scaled(
                _PREVIEW_MAX_LONG_SIDE,
                _PREVIEW_MAX_LONG_SIDE,
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            reader.setScaledSize(scaled)
        image = reader.read()
        if image is None or image.isNull():
            return None
        return QPixmap.fromImage(image)

    def load(
        self,
        path: str,
        revision: tuple[object, ...] | None = None,
        image_bytes: bytes = b"",
    ) -> None:
        if path != self._path or revision != self._revision or self._pixmap is None:
            self._path = path
            self._revision = revision
            # Bytes were read off-thread by the preview worker; the decode
            # below is bounded to preview resolution so even a 64 MB
            # multi-megapixel JPEG costs a fraction of the old full-res
            # decode on the GUI thread (#530).
            self._pixmap = self._decode_bounded(image_bytes or path)
            self._scaled_key = None
        self.render_current()

    def render_current(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            self.clear()
            self.setText("图片预览加载失败")
            return
        target = QSize(max(self.width(), 240), max(self.height(), 180))
        key = (
            self._path,
            self._revision,
            target.width(),
            target.height(),
            self.transformation_mode,
        )
        if key == self._scaled_key:
            return  # already rendered at exactly this size/mode
        scaled = self._pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            self.transformation_mode,
        )
        self._scaled_key = key
        self.setPixmap(scaled)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._path:
            # Interactive resizes stream dozens of events; coalesce them so
            # each O(source) smooth rescale runs once the user stops (#530).
            self._resize_timer.start()
