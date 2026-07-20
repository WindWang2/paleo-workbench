from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from paleo_workbench.tokens import SPACE_2
from paleo_workbench.ui.pages.table_preview_widget import TablePreviewWidget


class GeoTiffPreviewWidget(QWidget):
    """GeoTIFF thumbnail + geographic metadata summary table.

    The PNG thumbnail bytes are produced off-thread by the preview provider;
    this widget only decodes them on the UI thread (mirroring ImagePreviewWidget).
    The metadata table reuses TablePreviewWidget.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_2)
        self._image_label = QLabel()
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumHeight(160)
        layout.addWidget(self._image_label, 1)
        self.summary_table = TablePreviewWidget()
        layout.addWidget(self.summary_table)
        self._pixmap: QPixmap | None = None
        self._transformation_mode = Qt.TransformationMode.SmoothTransformation

    def apply_settings(self, settings) -> None:
        self.summary_table.setVisible(settings.show_geo_metadata)
        self.summary_table.apply_settings(settings)
        self._transformation_mode = (
            Qt.TransformationMode.SmoothTransformation
            if settings.smooth_images
            else Qt.TransformationMode.FastTransformation
        )
        self._render_thumbnail()

    def load(
        self,
        path: str,
        revision: tuple[object, ...] | None,
        image_bytes: bytes,
        geo_metadata: tuple[tuple[str, str], ...],
    ) -> None:
        del path, revision
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
                self._transformation_mode,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_thumbnail()
