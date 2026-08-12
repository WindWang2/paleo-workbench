from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from paleo_workbench.ui import tokens
from paleo_workbench.workflow.service import STEP_ORDER

STEP_TYPES = STEP_ORDER


class WorkflowProgress(QWidget):
    """Home workflow strip with evidence + freshness (需更新) labels."""

    recompute_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.step_widgets: list[dict] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(tokens.SPACE_1)

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        for i in range(6):
            badge = QLabel(str(i + 1))
            badge.setObjectName("WorkflowStepBadge")
            badge.setProperty("stepColor", tokens.STEP_COLORS[i])
            badge.setFixedSize(30, 30)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setStyleSheet(
                f"background: {tokens.STEP_COLORS[i]}; color: #ffffff;"
                f"border-radius: {tokens.RADIUS_BADGE}px; font-weight: 600;"
            )
            label = QLabel(tokens.STEP_LABELS[i])
            label.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 500;"
            )
            status = QLabel(tokens.STATUS_TEXT["pending"])
            status.setStyleSheet(f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;")
            step_layout = QVBoxLayout()
            step_layout.setContentsMargins(tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2, tokens.SPACE_2)
            step_layout.setSpacing(tokens.SPACE_1)
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
                line.setFixedHeight(24)
                line.setFixedWidth(30)
                line.setStyleSheet(f"background: transparent; border-bottom: 2px solid {tokens.BORDER}; margin-bottom: 12px;")
                layout.addWidget(line, 0, Qt.AlignmentFlag.AlignTop)
        layout.addStretch()
        root.addLayout(layout)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(tokens.SPACE_2, 0, tokens.SPACE_2, 0)
        self.plan_label = QLabel("")
        self.plan_label.setObjectName("WorkflowRecomputePlan")
        self.plan_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
        )
        self.plan_label.setWordWrap(True)
        self.recompute_button = QPushButton("更新受影响成果")
        self.recompute_button.setObjectName("WorkflowRecomputeButton")
        self.recompute_button.setVisible(False)
        self.recompute_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.recompute_button.clicked.connect(self.recompute_requested.emit)
        action_row.addWidget(self.plan_label, 1)
        action_row.addWidget(self.recompute_button, 0)
        root.addLayout(action_row)

    def update_steps(self, steps: list) -> None:
        step_map = {}
        for step in steps:
            step_map[step.step_type] = step.status
        stale_count = 0
        for i, step_type in enumerate(STEP_TYPES):
            status = step_map.get(step_type, "pending")
            if status == "stale":
                stale_count += 1
            self.step_widgets[i]["status"].setText(
                tokens.STATUS_TEXT.get(status, "未开始")
            )
            color = (
                tokens.WARNING
                if status == "stale"
                else tokens.TEXT_SECONDARY
            )
            self.step_widgets[i]["status"].setStyleSheet(
                f"color: {color}; font-size: 11px;"
            )
        self.recompute_button.setVisible(stale_count > 0)
        if stale_count > 0:
            self.plan_label.setText(
                f"{stale_count} 个工作流步骤需更新（相对当前上游版本）"
            )
        else:
            self.plan_label.setText("")

    def set_recompute_plan_summary(self, summary: str) -> None:
        """Optional multi-line plan preview (from build_affected_products_plan)."""
        if summary:
            self.plan_label.setText(summary)
            self.recompute_button.setVisible(True)
