from __future__ import annotations

from PySide6.QtCore import Signal
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

    run_requested = Signal()
    export_requested = Signal()
    config_requested = Signal()
    finalize_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3, tokens.SPACE_3)
        layout.setSpacing(tokens.SPACE_3)

        self.title_label = QLabel(
            "成图与审核 · — 古地理图（自动质检 + 人工审核）"
        )
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 600;"
            " border: none; background: transparent;"
        )
        layout.addWidget(self.title_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(tokens.SPACE_2)
        self.run_btn = QPushButton("运行检查")
        self.run_btn.setObjectName("PrimaryButton")
        self.run_btn.setToolTip("运行自动质检规则")
        self.run_btn.clicked.connect(self.run_requested.emit)
        button_row.addWidget(self.run_btn)
        self.config_btn = QPushButton("规则配置")
        self.config_btn.setObjectName("SecondaryButton")
        self.config_btn.setToolTip("当前规则见下方列表（配置面板后续迭代）")
        self.config_btn.clicked.connect(self.config_requested.emit)
        button_row.addWidget(self.config_btn)
        self.export_btn = QPushButton("导出检查报告")
        self.export_btn.setObjectName("PrimaryButton")
        self.export_btn.setToolTip("导出质检报告文件")
        self.export_btn.clicked.connect(self.export_requested.emit)
        button_row.addWidget(self.export_btn)
        self.finalize_btn = QPushButton("专家定稿")
        self.finalize_btn.setObjectName("SecondaryButton")
        self.finalize_btn.setToolTip("将当前古地理图写入 VersionSet 快照并标记为 final")
        self.finalize_btn.clicked.connect(self.finalize_requested.emit)
        button_row.addWidget(self.finalize_btn)
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
        elif map_documents:
            horizon = getattr(map_documents[-1], "linked_target_horizon", None) or "—"
        self.title_label.setText(
            f"成图与审核 · {horizon} 古地理图（自动质检 + 人工审核）"
        )
        self.finalize_btn.setEnabled(bool(map_documents))

        if reports and reports[0].rules:
            chips = " · ".join(reports[0].rules)
        else:
            chips = " · ".join(tokens.DEFAULT_QC_RULES)
        self.rules_label.setText(f"检查规则: {chips}")

        has_maps = bool(map_documents)
        self.run_btn.setEnabled(has_maps)
        self.export_btn.setEnabled(bool(reports))
