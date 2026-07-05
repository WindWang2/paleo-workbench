from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens

STEP_TYPES = ["data_check", "factor_map", "prediction", "map_compile", "qc", "export"]


class RecentActivityCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ActivityCard")
        self.setStyleSheet(
            f"QFrame#ActivityCard {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        self.title_label = QLabel("最近活动")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;"
        )
        layout.addWidget(self.title_label)
        self._entries_widget = QWidget()
        self.entries_layout = QVBoxLayout(self._entries_widget)
        self.entries_layout.setContentsMargins(0, 0, 0, 0)
        self.entries_layout.setSpacing(4)
        layout.addWidget(self._entries_widget)
        self.empty_label = QLabel("暂无活动")
        self.empty_label.setStyleSheet(f"color: {tokens.TEXT_SECONDARY};")
        self.entries_layout.addWidget(self.empty_label)
        self._entry_labels: list[QLabel] = []
        layout.addStretch()

    def update_state(self, state: dict, steps: list) -> None:
        self._clear_entries()
        count = 0
        for step in steps:
            if step.status == "pending":
                continue
            step_index = STEP_TYPES.index(step.step_type) if step.step_type in STEP_TYPES else 0
            label_text = tokens.STEP_LABELS[step_index]
            status_text = tokens.STATUS_TEXT.get(step.status, step.status)
            entry = QLabel(f"{label_text}: {status_text}")
            entry.setStyleSheet(
                f"color: {tokens.TEXT_PRIMARY}; font-size: 12.5px;"
            )
            self.entries_layout.addWidget(entry)
            self._entry_labels.append(entry)
            count += 1
        if count > 0:
            self.empty_label.hide()
        else:
            self.empty_label.show()
        self._entry_count = count

    def _clear_entries(self) -> None:
        for entry in self._entry_labels:
            self.entries_layout.removeWidget(entry)
            entry.deleteLater()
        self._entry_labels.clear()

    def entry_count(self) -> int:
        return getattr(self, "_entry_count", 0)
