from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel


class ImagePreviewWidget(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._path = ""
        self._revision: tuple[object, ...] | None = None
        self._pixmap: QPixmap | None = None
        self.transformation_mode = Qt.TransformationMode.SmoothTransformation

    def apply_settings(self, settings) -> None:
        self.transformation_mode = (
            Qt.TransformationMode.SmoothTransformation
            if settings.smooth_images
            else Qt.TransformationMode.FastTransformation
        )
        self.render_current()

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
                self.transformation_mode,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._path:
            self.render_current()
