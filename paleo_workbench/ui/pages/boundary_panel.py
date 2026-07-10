from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens


class BoundaryPanel(QFrame):
    """Right-hand form panel for initial facies boundary configuration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BoundaryPanel")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        self.title_label = QLabel("初始岩相边界制备")
        self.title_label.setObjectName("MapDockTitle")
        layout.addWidget(self.title_label)

        # Threshold spin (0.0–1.0, step 0.05, default 0.55, 2 decimals)
        self.threshold_label = QLabel("概率阈值")
        self.threshold_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(self.threshold_label)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 1.0)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setValue(0.55)
        self.threshold_spin.setStyleSheet(
            f"QDoubleSpinBox {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; padding: 2px 6px; }}"
        )
        layout.addWidget(self.threshold_spin)

        # Smoothing combo (SMOOTHING_LEVELS, default 中)
        self.smoothing_label = QLabel("边界平滑强度")
        self.smoothing_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(self.smoothing_label)
        self.smoothing_combo = QComboBox()
        self.smoothing_combo.addItems(tokens.SMOOTHING_LEVELS)
        self.smoothing_combo.setCurrentText("中")
        self.smoothing_combo.setStyleSheet(
            f"QComboBox {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; padding: 2px 6px; }}"
        )
        layout.addWidget(self.smoothing_combo)

        # Minimum area spin (0.0–10.0, step 0.1, default 0.5, 1 decimal, " km²")
        self.area_label = QLabel("最小图斑面积 (km²)")
        self.area_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(self.area_label)
        self.area_spin = QDoubleSpinBox()
        self.area_spin.setRange(0.0, 10.0)
        self.area_spin.setSingleStep(0.1)
        self.area_spin.setDecimals(1)
        self.area_spin.setValue(0.5)
        self.area_spin.setSuffix(" km²")
        self.area_spin.setStyleSheet(
            f"QDoubleSpinBox {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; padding: 2px 6px; }}"
        )
        layout.addWidget(self.area_spin)

        # Facies placeholder label
        self.facies_label = QLabel("三角洲前缘砂体 · 分流间湾泥")
        self.facies_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(self.facies_label)

        layout.addStretch()

        self.generate_btn = QPushButton("生成初始边界并送入编图")
        self.generate_btn.setObjectName("PrimaryButton")
        layout.addWidget(self.generate_btn)
