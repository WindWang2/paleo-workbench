from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.viz.prediction_helpers import field_value
from paleo_workbench.workflow.seismic_prediction import SEISMIC_DISPLAY_MODES


class SeismicControlPanel(QFrame):
    """Right-hand intelligent analysis summary for the current seismic view."""

    send_requested = Signal()
    display_mode_changed = Signal(str)
    well_tie_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicControlPanel")
        self.setFixedWidth(240)
        self._suppress = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        self.title_label = QLabel("智能分析结果")
        self.title_label.setObjectName("MapDockTitle")
        layout.addWidget(self.title_label)

        self.status_value = self._add_value(layout, "分析状态", "待开始")
        self.shape_value = self._add_value(layout, "体数据维度", "—")
        self.horizon_value = self._add_value(layout, "目标层位", "—")
        self.mock_value = self._add_value(layout, "输出性质", "—")
        self.attribute_value = self._add_value(layout, "当前属性", "振幅")

        mode_label = QLabel("显示模式")
        mode_label.setObjectName("WorkFieldLabel")
        layout.addWidget(mode_label)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(list(SEISMIC_DISPLAY_MODES))
        self.mode_combo.currentTextChanged.connect(self._on_mode)
        layout.addWidget(self.mode_combo)
        # Backward-compatible label mirror
        self.mode_value = self.mode_combo

        self.well_tie_btn = QPushButton("井震标定 (Auto-Tie)")
        self.well_tie_btn.setObjectName("SecondaryButton")
        self.well_tie_btn.setCheckable(True)
        self.well_tie_btn.toggled.connect(self._on_well_tie)
        layout.addWidget(self.well_tie_btn)

        layout.addStretch()
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

    def _on_well_tie(self, checked: bool) -> None:
        if not self._suppress:
            self.well_tie_toggled.emit(bool(checked))

    def set_controls_enabled(self, enabled: bool) -> None:
        self.mode_combo.setEnabled(enabled)
        self.well_tie_btn.setEnabled(enabled)
        self.send_btn.setEnabled(enabled)

    def set_attribute_label(self, label: str) -> None:
        self.attribute_value.setText(str(label or "振幅"))

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
        self.status_value.setText(field_value(task, "status", "") or "待开始")

        if task is None:
            self.mock_value.setText("—")
            self.set_controls_enabled(False)
            return

        # Honest output labeling (P2): random/mock output must never display
        # as 真实, and heuristic output is not a scientific prediction.
        # Mirrors prediction_evidence_panel.py (review finding I3).
        if summary.get("is_mock"):
            nature = "Mock"
        elif not summary.get("final_scientific_prediction", False):
            nature = "启发式"
        else:
            nature = "科学预测"
        if summary.get("demo") or summary.get("source") == "synthetic/demo":
            nature = f"Demo · {nature}"
        replaceable = "可替换" if summary.get("is_replaceable", False) else "固定"
        self.mock_value.setText(f"{nature} · {replaceable}")
        self.set_controls_enabled(True)
