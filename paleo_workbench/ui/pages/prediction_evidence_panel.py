from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QListWidget, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.prediction_helpers import field_value


class PredictionEvidencePanel(QFrame):
    """Right-hand evidence and action summary for prediction output."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PredictionEvidencePanel")
        self.setFixedWidth(220)
        self.setStyleSheet(
            f"QFrame#PredictionEvidencePanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("预测证据")
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
            " border: none; background: transparent;"
        )
        layout.addWidget(title)

        self.mock_value = self._add_value(layout, "输出性质", "—")

        evidence_label = QLabel("证据贡献")
        evidence_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(evidence_label)

        self.evidence_list = QListWidget()
        self.evidence_list.setStyleSheet(
            f"QListWidget {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_BUTTON}px; padding: 2px; }}"
        )
        layout.addWidget(self.evidence_list, 1)

        self.run_btn = QPushButton("运行测井预测")
        self.run_btn.setObjectName("SecondaryButton")
        layout.addWidget(self.run_btn)
        self.send_btn = QPushButton("发送制备")
        self.send_btn.setObjectName("PrimaryButton")
        layout.addWidget(self.send_btn)

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 500;"
            " border: none; background: transparent;"
        )
        layout.addWidget(value)
        return value

    def update_state(self, task) -> None:
        summary = field_value(task, "result_summary", {}) or {}
        if task is None:
            self.mock_value.setText("—")
        else:
            mock_text = "Mock" if summary.get("is_mock") else "真实"
            replaceable = "可替换" if summary.get("is_replaceable", False) else "固定"
            self.mock_value.setText(f"{mock_text} · {replaceable}")

        self.evidence_list.clear()
        for item in field_value(task, "evidence_contribution", []) or []:
            name = item.get("name", "未命名证据")
            weight = item.get("weight", 0)
            self.evidence_list.addItem(f"{name}: {weight:.0%}")
