"""PROTOTYPE — THROW AWAY CODE FOR TESTING DUAL-VOLUME OVERLAY & BLENDING DESIGNS

Run command:
    python paleo_workbench/ui/prototypes/proto_dual_volume_overlay.py

Purpose:
    Explore and evaluate 3 distinct UI variants and blending algorithms for
    overlaying secondary attributes (e.g. Coherence/Faults) onto primary
    3D Seismic Amplitude volumes in real-time.
"""
from __future__ import annotations

import sys
import time
import numpy as np

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap, QPainter, QFont, QPen, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSlider, QLabel, QComboBox, QRadioButton, QButtonGroup, QFrame,
    QPushButton, QGroupBox
)


def generate_synthetic_seismic_volumes(nx=200, ny=200, nz=200):
    """Generate synthetic 3D amplitude and coherence volumes in memory."""
    x = np.linspace(-3, 3, nx)
    y = np.linspace(-3, 3, ny)
    z = np.linspace(0, 4 * np.pi, nz)
    X, Y, Z = np.meshgrid(x, y, z, indexing='ij')

    # Primary volume: dipping layers with sinusoidal seismic reflections
    dip = 0.3 * X + 0.2 * Y
    amp_vol = np.sin(Z + dip) * np.exp(-0.05 * (X**2 + Y**2)).astype(np.float32)

    # Secondary volume: synthetic coherence fault plane + channel anomaly
    fault_mask = np.exp(-15.0 * ((X - 0.5 * Y) - 0.2 * Z / (4 * np.pi))**2)
    coh_vol = (1.0 - 0.8 * fault_mask).astype(np.float32)

    return amp_vol, coh_vol


class DualVolumeOverlayWidget(QWidget):
    """Interactive prototype canvas displaying slice overlay with state readout."""

    def __init__(self, amp_vol: np.ndarray, coh_vol: np.ndarray, parent=None):
        super().__init__(parent)
        self.amp_vol = amp_vol
        self.coh_vol = coh_vol
        self.nx, self.ny, self.nz = amp_vol.shape

        self.variant = "Variant A: Alpha Blending"
        self.axis = 2  # 0: Inline, 1: Crossline, 2: Time
        self.slice_idx = self.nz // 2
        self.opacity = 0.5
        self.cmap_name = "seismic"
        self.threshold = 0.6

        self._last_render_ms = 0.0
        self._pixmap: QPixmap | None = None

    def set_variant(self, variant: str):
        self.variant = variant
        self.update_render()

    def set_slice(self, axis: int, idx: int):
        self.axis = axis
        self.slice_idx = idx
        self.update_render()

    def set_opacity(self, val: float):
        self.opacity = val
        self.update_render()

    def set_threshold(self, val: float):
        self.threshold = val
        self.update_render()

    def update_render(self):
        t0 = time.perf_counter()

        # Extract 2D slices
        if self.axis == 0:
            idx = int(np.clip(self.slice_idx, 0, self.nx - 1))
            amp_slice = self.amp_vol[idx, :, :]
            coh_slice = self.coh_vol[idx, :, :]
        elif self.axis == 1:
            idx = int(np.clip(self.slice_idx, 0, self.ny - 1))
            amp_slice = self.amp_vol[:, idx, :]
            coh_slice = self.coh_vol[:, idx, :]
        else:
            idx = int(np.clip(self.slice_idx, 0, self.nz - 1))
            amp_slice = self.amp_vol[:, :, idx]
            coh_slice = self.coh_vol[:, :, idx]

        h, w = amp_slice.shape
        rgba = np.zeros((h, w, 4), dtype=np.uint8)

        # Normalize primary amplitude to 0..255 (Greyscale background)
        amp_norm = np.clip((amp_slice + 1.0) * 127.5, 0, 255).astype(np.uint8)

        if "Variant A" in self.variant:
            # Variant A: Alpha Blending (Amplitude Grayscale + Coherence Jet/Red overlay)
            # Map coherence 0..1 to Red channel highlight
            coh_red = np.clip((1.0 - coh_slice) * 255.0 * 2.0, 0, 255).astype(np.uint8)
            alpha_b = self.opacity

            rgba[:, :, 0] = np.clip((1 - alpha_b) * amp_norm + alpha_b * coh_red, 0, 255).astype(np.uint8)
            rgba[:, :, 1] = np.clip((1 - alpha_b) * amp_norm, 0, 255).astype(np.uint8)
            rgba[:, :, 2] = np.clip((1 - alpha_b) * amp_norm, 0, 255).astype(np.uint8)
            rgba[:, :, 3] = 255

        elif "Variant B" in self.variant:
            # Variant B: RGB Multi-Channel Spectral Fusion
            # Red: Amplitude positive, Green: Amplitude negative, Blue: Coherence anomaly
            rgba[:, :, 0] = np.clip(amp_slice * 255.0, 0, 255).astype(np.uint8)
            rgba[:, :, 1] = np.clip(-amp_slice * 255.0, 0, 255).astype(np.uint8)
            rgba[:, :, 2] = np.clip((1.0 - coh_slice) * 255.0, 0, 255).astype(np.uint8)
            rgba[:, :, 3] = 255

        else:
            # Variant C: Coherence Threshold Masking Overlay
            # Show primary amplitude everywhere; highlight low coherence < threshold in Cyan/Yellow
            mask = coh_slice < self.threshold
            rgba[:, :, 0] = amp_norm
            rgba[:, :, 1] = amp_norm
            rgba[:, :, 2] = amp_norm
            rgba[:, :, 3] = 255

            # Highlight masked fault regions with high contrast Cyan
            rgba[mask, 0] = 0
            rgba[mask, 1] = 240
            rgba[mask, 2] = 255

        qimg = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888)
        self._pixmap = QPixmap.fromImage(qimg)

        self._last_render_ms = (time.perf_counter() - t0) * 1000.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#12141C"))

        if self._pixmap:
            # Draw overlay image scaled to viewport
            scaled_pm = self._pixmap.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            x = (self.width() - scaled_pm.width()) // 2
            y = (self.height() - scaled_pm.height()) // 2
            painter.drawPixmap(x, y, scaled_pm)

        # Draw State Readout Overlay
        painter.setPen(QColor("#00E5FF"))
        painter.setFont(QFont("Monospace", 10, QFont.Weight.Bold))
        axis_names = ["Inline (0)", "Crossline (1)", "Time (2)"]
        readout = (
            f"[PROTOTYPE STATE READOUT]\n"
            f"Active Variant : {self.variant}\n"
            f"Current Axis   : {axis_names[self.axis]}\n"
            f"Slice Index    : {self.slice_idx}\n"
            f"Opacity        : {self.opacity:.2f}\n"
            f"Threshold      : {self.threshold:.2f}\n"
            f"Render Time    : {self._last_render_ms:.2f} ms ({1000.0 / max(0.1, self._last_render_ms):.0f} FPS)"
        )
        painter.drawText(15, 25, readout)


class MainWindow(QMainWindow):
    """Prototype host window with controls and bottom variant switcher bar."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PROTOTYPE — 3D Seismic Dual-Volume Overlay & Blending (Throwaway Code)")
        self.resize(1000, 750)

        # Generate data
        self.amp_vol, self.coh_vol = generate_synthetic_seismic_volumes(200, 200, 200)

        # Main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Top Control Bar
        ctrl_box = QGroupBox("Interactive Overlay Controls (PROTOTYPE)")
        ctrl_layout = QHBoxLayout(ctrl_box)

        # Axis Selector
        ctrl_layout.addWidget(QLabel("Axis:"))
        self.axis_combo = QComboBox()
        self.axis_combo.addItems(["Inline", "Crossline", "Time"])
        self.axis_combo.setCurrentIndex(2)
        self.axis_combo.currentIndexChanged.connect(self._on_axis_changed)
        ctrl_layout.addWidget(self.axis_combo)

        # Slice Slider
        ctrl_layout.addWidget(QLabel("Slice:"))
        self.slice_slider = QSlider(Qt.Orientation.Horizontal)
        self.slice_slider.setRange(0, 199)
        self.slice_slider.setValue(100)
        self.slice_slider.valueChanged.connect(self._on_slice_changed)
        ctrl_layout.addWidget(self.slice_slider)

        # Opacity Slider
        ctrl_layout.addWidget(QLabel("Opacity:"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(50)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        ctrl_layout.addWidget(self.opacity_slider)

        # Threshold Slider
        ctrl_layout.addWidget(QLabel("Threshold:"))
        self.thresh_slider = QSlider(Qt.Orientation.Horizontal)
        self.thresh_slider.setRange(0, 100)
        self.thresh_slider.setValue(60)
        self.thresh_slider.valueChanged.connect(self._on_thresh_changed)
        ctrl_layout.addWidget(self.thresh_slider)

        main_layout.addWidget(ctrl_box)

        # Prototype Canvas
        self.canvas = DualVolumeOverlayWidget(self.amp_vol, self.coh_vol)
        main_layout.addWidget(self.canvas, stretch=1)

        # Bottom Variant Switcher Bar (UI Prototype Skill Standard)
        variant_box = QFrame()
        variant_box.setStyleSheet("QFrame { background: #1B1E2B; border-top: 2px solid #00E5FF; padding: 6px; }")
        variant_layout = QHBoxLayout(variant_box)
        variant_layout.addWidget(QLabel("<b>UI VARIANT SWITCHER:</b>"))

        self.btn_var_a = QRadioButton("Variant A: Alpha Blending")
        self.btn_var_b = QRadioButton("Variant B: RGB Multi-Channel Fusion")
        self.btn_var_c = QRadioButton("Variant C: Coherence Masking Overlay")
        self.btn_var_a.setChecked(True)

        self.var_group = QButtonGroup(self)
        self.var_group.addButton(self.btn_var_a, 0)
        self.var_group.addButton(self.btn_var_b, 1)
        self.var_group.addButton(self.btn_var_c, 2)
        self.var_group.idToggled.connect(self._on_variant_changed)

        variant_layout.addWidget(self.btn_var_a)
        variant_layout.addWidget(self.btn_var_b)
        variant_layout.addWidget(self.btn_var_c)
        variant_layout.addStretch()

        main_layout.addWidget(variant_box)

        # Initial render
        self.canvas.update_render()

    def _on_axis_changed(self, idx: int):
        self.canvas.set_slice(idx, self.slice_slider.value())

    def _on_slice_changed(self, val: int):
        self.canvas.set_slice(self.axis_combo.currentIndex(), val)

    def _on_opacity_changed(self, val: int):
        self.canvas.set_opacity(val / 100.0)

    def _on_thresh_changed(self, val: int):
        self.canvas.set_threshold(val / 100.0)

    def _on_variant_changed(self, id: int, checked: bool):
        if not checked:
            return
        variants = [
            "Variant A: Alpha Blending",
            "Variant B: RGB Multi-Channel Fusion",
            "Variant C: Coherence Masking Overlay"
        ]
        self.canvas.set_variant(variants[id])


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
