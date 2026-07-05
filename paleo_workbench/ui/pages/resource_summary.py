from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from paleo_workbench.ui import tokens

RESOURCE_TYPES = ["well_log", "seismic", "horizon"]


class ResourceSummaryBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ResourceSummaryBar")
        self.setStyleSheet(
            f"QFrame#ResourceSummaryBar {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(24)
        self.type_labels: dict[str, QLabel] = {}
        for rtype in RESOURCE_TYPES:
            label = QLabel(f"{tokens.RESOURCE_LABELS[rtype]}: 0{tokens.RESOURCE_UNITS.get(rtype, '')}")
            label.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 500;"
            )
            self.type_labels[rtype] = label
            layout.addWidget(label)
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
            self.type_labels[rtype].setText(
                f"{tokens.RESOURCE_LABELS[rtype]}: {count}{unit}"
            )
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
