from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import QLabel

# Preview never needs more than this many pixels on the long side: JPEG
# decoders scale during the DCT pass (a multi-megapixel source decodes in
# a fraction of the full-resolution time), and every later rescale starts
# from a bounded source instead of the full bitmap (#530).
_PREVIEW_MAX_LONG_SIDE = 2048

_RESIZE_DEBOUNCE_MS = 80

_ZOOM_STEP = 1.25
_ZOOM_MIN = 0.1
_ZOOM_MAX = 8.0


class ImagePreviewWidget(QLabel):
    zoom_changed = Signal(float)

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
        # zoom / pan state (session-only, not persisted to settings)
        self._zoom_factor: float = 1.0
        self._fit_mode: bool = True
        self._pan_offset = QPoint(0, 0)
        self._drag_start_pos: QPoint | None = None
        self._drag_start_offset = QPoint(0, 0)

    def sizeHint(self) -> QSize:  # noqa: N802
        # 缩放模式下 pixmap 远大于可视区，默认 sizeHint（=pixmap 大小）会把
        # 外层布局（stack/分隔条）撑开；平移在 paintEvent 内完成，widget 只
        # 需占用布局分配的空间。fit 模式 pixmap 本就贴合 widget，沿用默认。
        if not self._fit_mode:
            return QSize(240, 180)
        return super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        if not self._fit_mode:
            return QSize(240, 180)
        return super().minimumSizeHint()

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
            # new image -> back to fit mode
            self._zoom_factor = 1.0
            self._fit_mode = True
            self._pan_offset = QPoint(0, 0)
            self._drag_start_pos = None
        self.render_current()

    def render_current(self) -> None:
        if self._pixmap is None or self._pixmap.isNull():
            self.clear()
            self.setText("图片预览加载失败")
            self._scaled_key = None
            return
        if self._fit_mode:
            target = QSize(max(self.width(), 240), max(self.height(), 180))
            key = (
                self._path,
                self._revision,
                target.width(),
                target.height(),
                self.transformation_mode,
                "fit",
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
            # fit 模式下居中，不需要平移
            self._pan_offset = QPoint(0, 0)
            self._drag_start_pos = None
            self.update()
        else:
            w = max(1, int(self._pixmap.width() * self._zoom_factor))
            h = max(1, int(self._pixmap.height() * self._zoom_factor))
            target = QSize(w, h)
            key = (
                self._path,
                self._revision,
                target.width(),
                target.height(),
                self.transformation_mode,
                self._zoom_factor,
            )
            if key == self._scaled_key:
                # pixmap 未变，但 pan 可能已更新，仍需重绘
                self._pan_offset = self._clamp_pan(self._pan_offset)
                self.update()
                return
            scaled = self._pixmap.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                self.transformation_mode,
            )
            self._scaled_key = key
            self.setPixmap(scaled)
            self._pan_offset = self._clamp_pan(self._pan_offset)
            self.update()

    # -- zoom public API -------------------------------------------------

    def zoom_in(self) -> None:
        self.set_zoom_factor(self._zoom_factor * _ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set_zoom_factor(self._zoom_factor / _ZOOM_STEP)

    def set_zoom_factor(self, factor: float) -> None:
        clamped = max(_ZOOM_MIN, min(_ZOOM_MAX, float(factor)))
        # 已在边界且仍往边界外尝试时，不改变状态
        if abs(clamped - self._zoom_factor) < 1e-9 and not self._fit_mode:
            return
        self._zoom_factor = clamped
        self._fit_mode = False
        self.render_current()
        try:
            self.zoom_changed.emit(self._zoom_factor)
        except Exception:
            pass

    def set_fit_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._fit_mode:
            return
        self._fit_mode = enabled
        if enabled:
            self._zoom_factor = 1.0
            self._pan_offset = QPoint(0, 0)
            self._drag_start_pos = None
        self.render_current()
        try:
            self.zoom_changed.emit(self._zoom_factor)
        except Exception:
            pass

    def reset_zoom(self) -> None:
        self._zoom_factor = 1.0
        self._fit_mode = True
        self._pan_offset = QPoint(0, 0)
        self._drag_start_pos = None
        self.render_current()
        try:
            self.zoom_changed.emit(self._zoom_factor)
        except Exception:
            pass

    # -- pan helpers -----------------------------------------------------

    def _clamp_pan(self, offset: QPoint) -> QPoint:
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return QPoint(0, 0)
        pw, ph = pm.width(), pm.height()
        ww, wh = self.width(), self.height()
        # widget 尚未布局时 fallback
        if ww <= 0:
            ww = 240
        if wh <= 0:
            wh = 180
        if pw <= ww:
            cx = 0
        else:
            max_off_x = (pw - ww) // 2
            cx = max(-max_off_x, min(max_off_x, offset.x()))
        if ph <= wh:
            cy = 0
        else:
            max_off_y = (ph - wh) // 2
            cy = max(-max_off_y, min(max_off_y, offset.y()))
        return QPoint(cx, cy)

    # -- events ----------------------------------------------------------

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            elif delta < 0:
                self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if not self._fit_mode and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
            self._drag_start_offset = QPoint(self._pan_offset)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_start_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.pos() - self._drag_start_pos
            new_offset = self._drag_start_offset + delta
            self._pan_offset = self._clamp_pan(new_offset)
            self.update()
            event.accept()
            return
        if not self._fit_mode:
            # hover 时给出可拖拽提示
            if self._drag_start_pos is None:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._drag_start_pos is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = None
            if not self._fit_mode:
                self.setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._fit_mode:
            super().paintEvent(event)
            return
        if self._pixmap is None or self._pixmap.isNull():
            super().paintEvent(event)
            return
        pm = self.pixmap()
        if pm is None or pm.isNull():
            super().paintEvent(event)
            return
        painter = QPainter(self)
        ww, wh = self.width(), self.height()
        pw, ph = pm.width(), pm.height()
        x = (ww - pw) // 2 + self._pan_offset.x()
        y = (wh - ph) // 2 + self._pan_offset.y()
        painter.drawPixmap(x, y, pm)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if not self._path:
            return
        if self._fit_mode:
            # Interactive resizes stream dozens of events; coalesce them so
            # each O(source) smooth rescale runs once the user stops (#530).
            self._resize_timer.start()
        else:
            self._pan_offset = self._clamp_pan(self._pan_offset)
            self.update()
