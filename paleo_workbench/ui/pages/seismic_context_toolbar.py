from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.viz.prediction_helpers import field_value


class SeismicContextToolbar(QFrame):
    """Compact active-task context and primary prediction action."""

    run_requested = Signal()
    demo_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SeismicContextToolbar")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.SPACE_2,
            tokens.PANEL_PADDING,
            tokens.SPACE_2,
        )
        layout.setSpacing(tokens.SPACE_3)

        title = QLabel("当前地震体")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        self.task_value = self._add_context_value(layout, "任务", "未选择预测任务")
        self.horizon_value = self._add_context_value(layout, "层位", "—")
        self.attribute_value = self._add_context_value(layout, "属性", "振幅")
        self.mode_value = self._add_context_value(layout, "显示", "vd")
        layout.addStretch(1)

        self.run_btn = QPushButton("运行预测")
        self.run_btn.setObjectName("PrimaryButton")
        self.run_btn.setToolTip(
            "通过 ModelRegistry 解析生产模型后运行科学预测；"
            "未配置生产模型时不会自动运行 mock"
        )
        self.run_btn.clicked.connect(self.run_requested.emit)
        layout.addWidget(self.run_btn)

        self.demo_btn = QPushButton("运行演示预测")
        self.demo_btn.setObjectName("SecondaryButton")
        self.demo_btn.setToolTip(
            "显式演示模式：运行 DemoModelProvider（合成数据，非科学预测）"
        )
        self.demo_btn.clicked.connect(self.demo_requested.emit)
        layout.addWidget(self.demo_btn)

    @staticmethod
    def _add_context_value(layout: QHBoxLayout, label_text: str, value_text: str) -> QLabel:
        field = QFrame()
        field_layout = QVBoxLayout(field)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(0)
        label = QLabel(label_text)
        label.setObjectName("WorkFieldLabel")
        value = QLabel(value_text)
        value.setObjectName("WorkFieldValue")
        field_layout.addWidget(label)
        field_layout.addWidget(value)
        layout.addWidget(field)
        return value

    def set_context(self, task, horizon: str, attribute: str, display_mode: str) -> None:
        self.task_value.setText(field_value(task, "name", "") or "未选择预测任务")
        self.horizon_value.setText(str(horizon or "—"))
        self.attribute_value.setText(str(attribute or "振幅"))
        self.mode_value.setText(str(display_mode or "vd"))
