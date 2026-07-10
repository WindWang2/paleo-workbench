from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from paleo_workbench.ui import tokens


class ActionHeader(QFrame):
    """Top banner of the 成图审核 page — title, action buttons, rules chips."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.title_label = QLabel(
            "成图与审核 · — 古地理图（自动质检 + 人工审核）"
        )
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
            " border: none; background: transparent;"
        )
        layout.addWidget(self.title_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.run_btn = QPushButton("运行检查")
        self.run_btn.setObjectName("PrimaryButton")
        button_row.addWidget(self.run_btn)
        self.config_btn = QPushButton("规则配置")
        self.config_btn.setObjectName("SecondaryButton")
        button_row.addWidget(self.config_btn)
        self.export_btn = QPushButton("导出检查报告")
        self.export_btn.setObjectName("PrimaryButton")
        button_row.addWidget(self.export_btn)
        button_row.addStretch()
        layout.addLayout(button_row)

        self.rules_label = QLabel(
            f"检查规则: {' · '.join(tokens.DEFAULT_QC_RULES)}"
        )
        self.rules_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            " border: none; background: transparent;"
        )
        layout.addWidget(self.rules_label)

    def update_state(self, reports: list, map_documents: list) -> None:
        horizon = "—"
        if reports:
            linked_id = reports[0].linked_map_document_id
            for doc in map_documents:
                if doc.id == linked_id:
                    horizon = doc.linked_target_horizon or "—"
                    break
        self.title_label.setText(
            f"成图与审核 · {horizon} 古地理图（自动质检 + 人工审核）"
        )

        if reports and reports[0].rules:
            chips = " · ".join(reports[0].rules)
        else:
            chips = " · ".join(tokens.DEFAULT_QC_RULES)
        self.rules_label.setText(f"检查规则: {chips}")
