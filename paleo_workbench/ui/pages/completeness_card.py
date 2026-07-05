from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from paleo_workbench.ui import tokens

RESOURCE_TYPES = ["well_log", "seismic", "horizon"]


class DataCompletenessCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CompletenessCard")
        self.setStyleSheet(
            f"QFrame#CompletenessCard {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        self.title_label = QLabel("数据完整度")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;"
        )
        layout.addWidget(self.title_label)
        self.rows: list[dict] = []
        for rtype in RESOURCE_TYPES:
            name_label = QLabel(tokens.RESOURCE_LABELS[rtype])
            name_label.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: 12.5px;"
            )
            count_label = QLabel("0")
            count_label.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
            )
            status_label = QLabel("—")
            status_label.setStyleSheet(
                f"color: {tokens.TEXT_SECONDARY}; font-size: 14px;"
            )
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            row_layout.addWidget(name_label, 1)
            row_layout.addWidget(count_label)
            row_layout.addWidget(status_label)
            row_widget = QFrame()
            row_widget.setLayout(row_layout)
            self.rows.append({
                "name": name_label, "count": count_label,
                "status": status_label, "widget": row_widget,
            })
            layout.addWidget(row_widget)
        self.summary_label = QLabel("—")
        self.summary_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
        )
        layout.addWidget(self.summary_label)
        layout.addStretch()

    def update_state(self, state: dict) -> None:
        readiness = state.get("resource_readiness", {})
        available = readiness.get("available_counts", {})
        missing = readiness.get("missing_types", [])
        ready = readiness.get("ready", False)
        for i, rtype in enumerate(RESOURCE_TYPES):
            count = available.get(rtype, 0)
            self.rows[i]["count"].setText(str(count))
            if count > 0:
                self.rows[i]["status"].setText("✓")
                self.rows[i]["status"].setStyleSheet(
                    f"color: {tokens.SUCCESS}; font-size: 14px; font-weight: 600;"
                )
            else:
                self.rows[i]["status"].setText("✗")
                self.rows[i]["status"].setStyleSheet(
                    f"color: {tokens.ERROR_RED}; font-size: 14px; font-weight: 600;"
                )
        if ready:
            self.summary_label.setText("数据完整")
            self.summary_label.setStyleSheet(
                f"color: {tokens.SUCCESS}; font-size: 11px; font-weight: 500;"
            )
        else:
            missing_labels = [tokens.RESOURCE_LABELS.get(m, m) for m in missing]
            self.summary_label.setText(f"缺少: {'、'.join(missing_labels)}")
            self.summary_label.setStyleSheet(
                f"color: {tokens.ERROR_RED}; font-size: 11px; font-weight: 500;"
            )
