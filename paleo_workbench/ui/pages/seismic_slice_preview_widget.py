from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from paleo_workbench.tokens import BG_SEARCH, BORDER, PRIMARY, PRIMARY_HOVER, RADIUS_BUTTON, SPACE_2, SPACE_3, TEXT_SECONDARY
from paleo_workbench.viz.seismic_3d_api import fast_slice_extract


class SeismicSlicePreviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._volume: np.ndarray | None = None
        self._path = ""
        self._revision = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACE_2)

        # Top Control Row
        control_layout = QHBoxLayout()
        control_layout.setSpacing(SPACE_3)

        type_label = QLabel("切片方向:")
        type_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-weight: 500;")
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Inline (剖面)", "Crossline (剖面)", "Time (切片)"])
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        self.slider.setStyleSheet(
            f"""
            QSlider::groove:horizontal {{
                border: 1px solid {BORDER};
                height: 6px;
                background: {BG_SEARCH};
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background: {PRIMARY};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: #ffffff;
                border: 2px solid {PRIMARY};
                width: 14px;
                height: 14px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {PRIMARY_HOVER};
                border-color: {PRIMARY_HOVER};
            }}
            """
        )
        self.slider.valueChanged.connect(self._on_slider_changed)

        self.index_label = QLabel("0 / 0")
        self.index_label.setStyleSheet(f"color: {TEXT_SECONDARY}; font-family: monospace; font-weight: 500;")

        control_layout.addWidget(type_label)
        control_layout.addWidget(self.type_combo)
        control_layout.addWidget(self.slider, 1)
        control_layout.addWidget(self.index_label)

        layout.addLayout(control_layout)

        # Image display area
        self.image_label = QLabel("请选择数据")
        self.message_label = self.image_label  # Backwards compatibility
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(
            f"border: 1px solid {BORDER}; border-radius: {RADIUS_BUTTON}px;"
            f" background: {BG_SEARCH};"
        )
        layout.addWidget(self.image_label, 1)

    def load_seismic(
        self,
        path: str,
        revision: tuple[object, ...] | None = None,
        volume: np.ndarray | None = None,
        message: str = "",
    ) -> None:
        self._path = path
        self._revision = revision
        self._volume = volume

        if volume is None:
            self.image_label.setText(message or "无地震数据或无法解析")
            self.slider.setMaximum(0)
            self.slider.setEnabled(False)
            self.type_combo.setEnabled(False)
            self.index_label.setText("0 / 0")
            return

        self.type_combo.setEnabled(True)
        self.slider.setEnabled(True)
        self._update_slider_range()
        self._render_slice()

    def _on_type_changed(self, index: int) -> None:
        self._update_slider_range()
        self._render_slice()

    def _on_slider_changed(self, value: int) -> None:
        if self._volume is not None:
            self.index_label.setText(f"{value} / {self.slider.maximum()}")
            self._render_slice()

    def _update_slider_range(self) -> None:
        if self._volume is None:
            return
        idx = self.type_combo.currentIndex()
        max_val = self._volume.shape[idx] - 1
        self.slider.setMaximum(max(0, max_val))
        self.slider.setValue(max(0, max_val // 2))
        self.index_label.setText(f"{self.slider.value()} / {self.slider.maximum()}")

    def _render_slice(self) -> None:
        if self._volume is None:
            return

        idx = self.type_combo.currentIndex()
        val = self.slider.value()

        slice_data = fast_slice_extract(self._volume, axis=idx, index=val)
        if idx in (0, 1):
            slice_data = slice_data.T

        slice_data = np.nan_to_num(slice_data, nan=0.0, posinf=0.0, neginf=0.0)
        min_val = slice_data.min()
        max_val = slice_data.max()
        if max_val > min_val:
            norm = ((slice_data - min_val) / (max_val - min_val) * 255.0).astype(np.uint8)
        else:
            norm = np.zeros(slice_data.shape, dtype=np.uint8)

        norm = np.ascontiguousarray(norm)
        height, width = norm.shape
        self._last_norm = norm  # Keep memory alive for QImage
        qimg = QImage(norm.data, width, height, width, QImage.Format.Format_Indexed8)

        if not hasattr(self, "_color_table"):
            self._color_table = None
            try:
                import matplotlib.pyplot as plt
                from PySide6.QtGui import qRgba
                cmap = plt.get_cmap("seismic")
                self._color_table = [qRgba(*(int(c * 255) for c in cmap(i / 255.0))) for i in range(256)]
            except Exception:
                pass
        
        if self._color_table:
            qimg.setColorTable(self._color_table)

        pixmap = QPixmap.fromImage(qimg)
        scaled_pixmap = pixmap.scaled(
            max(self.image_label.width() - 4, 10),
            max(self.image_label.height() - 4, 10),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self.image_label.setPixmap(scaled_pixmap)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_slice()

    def apply_settings(self, settings) -> None:
        font = self.font()
        font.setPointSize(settings.font_size)
        self.setFont(font)
