from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.workflow.service import REQUIRED_RESOURCE_TYPES

RESOURCE_TYPES = REQUIRED_RESOURCE_TYPES


class ResourceSummaryBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_4, tokens.SPACE_3, tokens.SPACE_4, tokens.SPACE_3)
        layout.setSpacing(tokens.SPACE_4)
        self.name_labels: dict[str, QLabel] = {}
        self.count_labels: dict[str, QLabel] = {}
        self.type_labels = self.count_labels
        for rtype in RESOURCE_TYPES:
            group = QWidget()
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(tokens.SPACE_1)

            name_label = QLabel(tokens.RESOURCE_LABELS[rtype])
            name_label.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: {tokens.FONT_SIZE_TITLE}; font-weight: 500;"
            )
            group_layout.addWidget(name_label)

            count_label = QLabel(f"0{tokens.RESOURCE_UNITS.get(rtype, '')}")
            count_label.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;"
            )
            group_layout.addWidget(count_label)

            self.name_labels[rtype] = name_label
            self.count_labels[rtype] = count_label
            layout.addWidget(group)
        layout.addStretch()
        self.status_label = QLabel("—")
        self.status_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 12px;"
        )
        layout.addWidget(self.status_label)

    def update_state(self, state: dict) -> None:
        readiness = state.get("resource_readiness", {})
        available = readiness.get("available_counts", {})
        missing = readiness.get("missing_types", [])
        ready = readiness.get("ready", False)
        for rtype in RESOURCE_TYPES:
            count = available.get(rtype, 0)
            unit = tokens.RESOURCE_UNITS.get(rtype, "")
            self.count_labels[rtype].setText(f"{count}{unit}")
        if ready:
            self.status_label.setText("数据完整")
            self.status_label.setStyleSheet(
                f"color: {tokens.SUCCESS}; font-size: 12px; font-weight: 500;"
            )
        else:
            missing_labels = [tokens.RESOURCE_LABELS.get(m, m) for m in missing]
            self.status_label.setText(f"缺少: {'、'.join(missing_labels)}")
            self.status_label.setStyleSheet(
                f"color: {tokens.ERROR_RED}; font-size: 12px; font-weight: 500;"
            )
