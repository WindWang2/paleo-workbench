from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import field_value


class SeismicControlPanel(QFrame):
    """Right-hand summary and actions for seismic prediction output."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicControlPanel")
        self.setFixedWidth(220)

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
        self.mode_value = self._add_value(layout, "显示模式", "vd")
        self.mock_value = self._add_value(layout, "输出性质", "—")

        layout.addStretch()
        self.run_btn = QPushButton("运行地震预测")
        self.run_btn.setObjectName("SecondaryButton")
        layout.addWidget(self.run_btn)
        self.send_btn = QPushButton("发送编图")
        self.send_btn.setObjectName("PrimaryButton")
        layout.addWidget(self.send_btn)

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setObjectName("WorkFieldLabel")
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setObjectName("WorkFieldValue")
        layout.addWidget(value)
        return value

    def update_state(self, task, volume_shape: tuple[int, int, int] | None = None) -> None:
        self.shape_value.setText(" × ".join(str(value) for value in volume_shape) if volume_shape else "—")
        self.mode_value.setText("vd")

        summary = field_value(task, "result_summary", {}) or {}
        if task is None:
            self.mock_value.setText("—")
        else:
            mock_text = "Mock" if summary.get("is_mock") else "真实"
            replaceable = "可替换" if summary.get("is_replaceable", False) else "固定"
            self.mock_value.setText(f"{mock_text} · {replaceable}")
