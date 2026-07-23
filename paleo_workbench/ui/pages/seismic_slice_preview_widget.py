from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from paleo_workbench.tokens import BG_SEARCH, BORDER, PRIMARY, PRIMARY_HOVER, RADIUS_BUTTON, SPACE_2, SPACE_3, TEXT_SECONDARY
from paleo_workbench.viz.seismic_3d_api import fast_slice_to_indexed8


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
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(16)
        self._render_timer.timeout.connect(self._render_slice)
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
        self._render_timer.stop()
        self._render_slice()

    def _on_type_changed(self, index: int) -> None:
        self._update_slider_range()
        self._render_timer.stop()
        self._render_slice()

    def _on_slider_changed(self, value: int) -> None:
        if self._volume is not None:
            self.index_label.setText(f"{value} / {self.slider.maximum()}")
            self._render_timer.start()

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

        norm, _, _ = fast_slice_to_indexed8(self._volume, axis=idx, index=val)
        if idx in (0, 1):
            norm = norm.T

        norm = np.ascontiguousarray(norm)
        height, width = norm.shape
        self._last_norm = norm  # Keep memory alive for QImage
        qimg = QImage(norm.data, width, height, width, QImage.Format.Format_Indexed8)

        if getattr(self, "_color_table", None) is None:
            from PySide6.QtGui import qRgba

            t = np.linspace(0.0, 1.0, 256)
            # Blue -> white -> red seismic ramp (white at t=0.5)
            r = np.clip(2.0 * t, 0.0, 1.0)
            b = np.clip(2.0 * (1.0 - t), 0.0, 1.0)
            g = np.minimum(r, b)
            self._color_table = [
                qRgba(int(ri * 255), int(gi * 255), int(bi * 255), 255)
                for ri, gi, bi in zip(r, g, b)
            ]

        if self._color_table:
            qimg.setColorTable(self._color_table)

        pixmap = QPixmap.fromImage(qimg)
        self._last_pixmap = pixmap
        scaled_pixmap = pixmap.scaled(
            max(self.image_label.width() - 4, 10),
            max(self.image_label.height() - 4, 10),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation if self.slider.isSliderDown() else Qt.TransformationMode.SmoothTransformation
        )
        self.image_label.setPixmap(scaled_pixmap)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        last = getattr(self, "_last_pixmap", None)
        if last is not None and not last.isNull():
            self.image_label.setPixmap(last.scaled(
                max(self.image_label.width() - 4, 10),
                max(self.image_label.height() - 4, 10),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def apply_settings(self, settings) -> None:
        font = self.font()
        font.setPointSize(settings.font_size)
        self.setFont(font)
