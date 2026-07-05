from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.sequence_helpers import field_value


class SequenceSchemeSummary(QFrame):
    """Right-hand summary for sequence scheme readiness."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SequenceSchemeSummary")
        self.setStyleSheet(
            f"QFrame#SequenceSchemeSummary {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title = QLabel("层序方案摘要")
        title.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
            " border: none; background: transparent;"
        )
        layout.addWidget(title)

        self.scheme_value = self._add_value(layout, "当前方案", "LST/TST/HST")
        self.boundary_count_value = self._add_value(layout, "层序界面", "0 个")
        self.systems_tract_value = self._add_value(layout, "体系域", "LST / TST / HST")

        layout.addStretch()
        self.save_btn = QPushButton("保存层序方案")
        self.save_btn.setObjectName("PrimaryButton")
        layout.addWidget(self.save_btn)

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

    def update_state(self, stratigraphy) -> None:
        scheme = field_value(stratigraphy, "systems_tract_scheme", "") or "LST/TST/HST"
        boundaries = field_value(stratigraphy, "sequence_boundaries", []) or []
        self.scheme_value.setText(scheme)
        self.boundary_count_value.setText(f"{len(boundaries)} 个")
        self.systems_tract_value.setText(" / ".join(tokens.SYSTEMS_TRACT_LABELS))
