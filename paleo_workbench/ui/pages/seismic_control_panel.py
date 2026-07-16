from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import field_value
from paleo_workbench.workflow.seismic_prediction import (
    SEISMIC_ATTRIBUTE_LABELS,
    SEISMIC_DISPLAY_MODES,
)


class SeismicControlPanel(QFrame):
    """Right-hand summary and actions for seismic prediction output."""

    run_requested = Signal()
    send_requested = Signal()
    display_mode_changed = Signal(str)
    attribute_changed = Signal(str)
    well_tie_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicControlPanel")
        self.setFixedWidth(220)
        self._suppress = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        title = QLabel("地震预测控制")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        self.shape_value = self._add_value(layout, "体数据维度", "—")
        self.horizon_value = self._add_value(layout, "目标层位", "—")
        self.mock_value = self._add_value(layout, "输出性质", "—")

        mode_label = QLabel("显示模式")
        mode_label.setObjectName("WorkFieldLabel")
        layout.addWidget(mode_label)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(list(SEISMIC_DISPLAY_MODES))
        self.mode_combo.currentTextChanged.connect(self._on_mode)
        layout.addWidget(self.mode_combo)
        # Backward-compatible label mirror
        self.mode_value = self.mode_combo

        attr_label = QLabel("地震属性")
        attr_label.setObjectName("WorkFieldLabel")
        layout.addWidget(attr_label)
        self.attribute_combo = QComboBox()
        self.attribute_combo.addItems(list(SEISMIC_ATTRIBUTE_LABELS))
        self.attribute_combo.currentTextChanged.connect(self._on_attribute)
        layout.addWidget(self.attribute_combo)

        self.well_tie_btn = QPushButton("井震标定 (Auto-Tie)")
        self.well_tie_btn.setObjectName("SecondaryButton")
        self.well_tie_btn.setCheckable(True)
        self.well_tie_btn.toggled.connect(self._on_well_tie)
        layout.addWidget(self.well_tie_btn)

        layout.addStretch()
        self.run_btn = QPushButton("运行地震预测")
        self.run_btn.setObjectName("SecondaryButton")
        self.run_btn.clicked.connect(self.run_requested.emit)
        layout.addWidget(self.run_btn)
        self.send_btn = QPushButton("发送编图")
        self.send_btn.setObjectName("PrimaryButton")
        self.send_btn.clicked.connect(self.send_requested.emit)
        layout.addWidget(self.send_btn)

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setObjectName("WorkFieldLabel")
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setObjectName("WorkFieldValue")
        layout.addWidget(value)
        return value

    def _on_mode(self, text: str) -> None:
        if not self._suppress:
            self.display_mode_changed.emit(text)

    def _on_attribute(self, text: str) -> None:
        if not self._suppress:
            self.attribute_changed.emit(text)

    def _on_well_tie(self, checked: bool) -> None:
        if not self._suppress:
            self.well_tie_toggled.emit(bool(checked))

    def set_controls_enabled(self, enabled: bool) -> None:
        self.mode_combo.setEnabled(enabled)
        self.attribute_combo.setEnabled(enabled)
        self.well_tie_btn.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)

    def update_state(self, task, volume_shape: tuple[int, int, int] | None = None) -> None:
        self.shape_value.setText(
            " × ".join(str(value) for value in volume_shape) if volume_shape else "—"
        )

        summary = field_value(task, "result_summary", {}) or {}
        meta = field_value(task, "model_metadata", {}) or {}
        horizon = ""
        if isinstance(meta, dict):
            horizon = str(meta.get("target_horizon") or "")
        if not horizon and isinstance(summary, dict):
            horizon = str(summary.get("target_horizon") or "")
        self.horizon_value.setText(horizon or "—")

        if task is None:
            self.mock_value.setText("—")
            self.set_controls_enabled(False)
            self.run_btn.setEnabled(True)
            return

        mock_text = "Mock" if summary.get("is_mock") else "真实"
        replaceable = "可替换" if summary.get("is_replaceable", False) else "固定"
        self.mock_value.setText(f"{mock_text} · {replaceable}")
        self.set_controls_enabled(True)
        self.run_btn.setEnabled(True)
