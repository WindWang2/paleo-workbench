from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens

STEP_TYPES = ["data_check", "factor_map", "prediction", "map_compile", "qc", "export"]


class WorkflowProgress(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.step_widgets: list[dict] = []
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for i in range(6):
            badge = QLabel(str(i + 1))
            badge.setFixedSize(30, 30)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                f"background: {tokens.STEP_COLORS[i]}; color: #ffffff;"
                f"border-radius: 8px; font-weight: 600;"
            )
            label = QLabel(tokens.STEP_LABELS[i])
            label.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 500;"
            )
            status = QLabel(tokens.STATUS_TEXT["pending"])
            status.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;")
            step_layout = QVBoxLayout()
            step_layout.setContentsMargins(8, 8, 8, 8)
            step_layout.setSpacing(4)
            step_layout.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
            step_layout.addWidget(label, 0, Qt.AlignmentFlag.AlignHCenter)
            step_layout.addWidget(status, 0, Qt.AlignmentFlag.AlignHCenter)
            card = QFrame()
            card.setLayout(step_layout)
            self.step_widgets.append({
                "badge": badge, "label": label, "status": status, "card": card,
            })
            layout.addWidget(card)
            if i < 5:
                line = QFrame()
                line.setFixedHeight(2)
                line.setStyleSheet(f"background: {tokens.BORDER}; border: none;")
                layout.addWidget(line, 0, Qt.AlignmentFlag.AlignTop)
        layout.addStretch()

    def update_steps(self, steps: list) -> None:
        step_map = {}
        for step in steps:
            step_map[step.step_type] = step.status
        for i, step_type in enumerate(STEP_TYPES):
            status = step_map.get(step_type, "pending")
            self.step_widgets[i]["status"].setText(tokens.STATUS_TEXT.get(status, "待开始"))
