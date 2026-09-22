from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from paleo_workbench.ui import style, tokens


def _field_label_sheet() -> str:
    return (
        f"color: {style.palette()['TEXT_SECONDARY']};"
        f" font-size: {tokens.FONT_SIZE_STATUS};"
        " border: none; background: transparent;"
    )


def _field_control_sheet(selector: str) -> str:
    return (
        f"{selector} {{ background: {style.palette()['BG_SIDEBAR']};"
        f" border: 1px solid {style.palette()['BORDER']};"
        f" border-radius: {tokens.RADIUS_BUTTON}px; padding: 2px 6px; }}"
    )


class BoundaryPanel(QFrame):
    """Right-hand form panel for initial facies boundary configuration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BoundaryPanel")
        # 侧栏宽度：保底 220，窄屏下可收缩、宽屏最多 1.6 倍有界弹性
        self.setMinimumWidth(220)
        self.setMaximumWidth(int(220 * 1.6))

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
        style.bind(self.threshold_label, _field_label_sheet)
        layout.addWidget(self.threshold_label)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 1.0)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setValue(0.55)
        style.bind(
            self.threshold_spin,
            lambda: _field_control_sheet("QDoubleSpinBox"),
        )
        layout.addWidget(self.threshold_spin)

        # Smoothing combo (SMOOTHING_LEVELS, default 中)
        self.smoothing_label = QLabel("边界平滑强度")
        style.bind(self.smoothing_label, _field_label_sheet)
        layout.addWidget(self.smoothing_label)
        self.smoothing_combo = QComboBox()
        self.smoothing_combo.addItems(tokens.SMOOTHING_LEVELS)
        self.smoothing_combo.setCurrentText("中")
        style.bind(
            self.smoothing_combo,
            lambda: _field_control_sheet("QComboBox"),
        )
        layout.addWidget(self.smoothing_combo)

        # Minimum area spin (0.0–10.0, step 0.1, default 0.5, 1 decimal, " km²")
        self.area_label = QLabel("最小图斑面积 (km²)")
        style.bind(self.area_label, _field_label_sheet)
        layout.addWidget(self.area_label)
        self.area_spin = QDoubleSpinBox()
        self.area_spin.setRange(0.0, 10.0)
        self.area_spin.setSingleStep(0.1)
        self.area_spin.setDecimals(1)
        self.area_spin.setValue(0.5)
        self.area_spin.setSuffix(" km²")
        style.bind(self.area_spin, lambda: _field_control_sheet("QDoubleSpinBox"))
        layout.addWidget(self.area_spin)

        # Facies placeholder label
        self.facies_label = QLabel("三角洲前缘砂体 · 分流间湾泥")
        style.bind(self.facies_label, _field_label_sheet)
        layout.addWidget(self.facies_label)

        layout.addStretch()

        self.generate_btn = QPushButton("生成初始边界并送入编图")
        self.generate_btn.setObjectName("PrimaryButton")
        self.generate_btn.setToolTip("生成初始相带边界")
        layout.addWidget(self.generate_btn)
