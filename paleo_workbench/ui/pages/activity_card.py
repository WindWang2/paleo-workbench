from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.workflow.service import STEP_ORDER

STEP_TYPES = STEP_ORDER


class RecentActivityCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4, tokens.SPACE_4)
        layout.setSpacing(tokens.SPACE_2)
        self.title_label = QLabel("最近活动")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 14px; font-weight: 600;"
        )
        layout.addWidget(self.title_label)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._entries_widget = QWidget()
        self.entries_layout = QVBoxLayout(self._entries_widget)
        self.entries_layout.setContentsMargins(0, 0, 0, 0)
        self.entries_layout.setSpacing(tokens.SPACE_1)
        self._entries_widget.setLayout(self.entries_layout)
        self._scroll.setWidget(self._entries_widget)
        layout.addWidget(self._scroll, 1)
        self.empty_label = QLabel("暂无活动")
        self.empty_label.setObjectName("EmptyStateLabel")
        self.entries_layout.addWidget(self.empty_label)
        self._entry_labels: list[QWidget] = []

    def update_state(self, state: dict, steps: list) -> None:
        self._clear_entries()
        count = 0
        for step in steps:
            if step.status == "pending":
                continue
            step_index = STEP_TYPES.index(step.step_type) if step.step_type in STEP_TYPES else 0
            label_text = tokens.STEP_LABELS[step_index]
            status_text = tokens.STATUS_TEXT.get(step.status, step.status)
            count += self._append_entry("刚刚", f"{label_text}: {status_text}")
        # Evidence-based fallback when steps are all pending but project has work.
        if count == 0:
            for label, value_key in (
                ("数据资源", "resource_counts"),
                ("单因素图", "factor_map_count"),
                ("预测任务", "prediction_count"),
                ("古地理图", "map_document_count"),
                ("质检问题", "qc_issue_count"),
                ("导出成果", "export_count"),
            ):
                raw = state.get(value_key, 0)
                if value_key == "resource_counts" and isinstance(raw, dict):
                    total = sum(int(v) for v in raw.values())
                    if total > 0:
                        count += self._append_entry("工程", f"{label}: {total} 项")
                    continue
                try:
                    n = int(raw or 0)
                except (TypeError, ValueError):
                    n = 0
                if n > 0:
                    count += self._append_entry("工程", f"{label}: {n}")
        if count > 0:
            self.empty_label.hide()
        else:
            self.empty_label.show()
        self._entry_count = count

    def _append_entry(self, when: str, description: str) -> int:
        time_label = QLabel(when)
        time_label.setStyleSheet(
            f"color: {tokens.TEXT_SECONDARY}; font-size: 11px;"
        )
        desc_label = QLabel(description)
        desc_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 12.5px;"
        )
        entry_layout = QHBoxLayout()
        entry_layout.setContentsMargins(0, 0, 0, 0)
        entry_layout.setSpacing(tokens.SPACE_2)
        entry_layout.addWidget(time_label)
        entry_layout.addWidget(desc_label, 1)
        entry_widget = QWidget()
        entry_widget.setLayout(entry_layout)
        self.entries_layout.addWidget(entry_widget)
        self._entry_labels.append(entry_widget)
        return 1

    def _clear_entries(self) -> None:
        for entry in self._entry_labels:
            self.entries_layout.removeWidget(entry)
            entry.deleteLater()
        self._entry_labels.clear()

    def entry_count(self) -> int:
        return getattr(self, "_entry_count", 0)
