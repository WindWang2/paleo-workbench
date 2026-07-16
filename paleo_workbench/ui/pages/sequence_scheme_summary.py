from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.sequence_helpers import field_value


class SequenceSchemeSummary(QFrame):
    """Right-hand summary for sequence scheme readiness."""

    save_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("PanelCard")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
            tokens.PANEL_PADDING,
        )
        layout.setSpacing(tokens.SPACE_2)

        title = QLabel("层序方案摘要")
        title.setObjectName("MapDockTitle")
        layout.addWidget(title)

        self.scheme_value = self._add_value(layout, "当前方案", "LST/TST/HST")
        self.boundary_count_value = self._add_value(layout, "层序界面", "0 个")
        self.systems_tract_value = self._add_value(layout, "体系域", "LST / TST / HST")
        self.status_value = self._add_value(layout, "绑定状态", "未保存")

        layout.addStretch()
        self.save_btn = QPushButton("保存层序方案")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self.save_requested.emit)
        layout.addWidget(self.save_btn)

    def _add_value(self, layout: QVBoxLayout, label_text: str, value_text: str) -> QLabel:
        label = QLabel(label_text)
        label.setObjectName("WorkFieldLabel")
        layout.addWidget(label)
        value = QLabel(value_text)
        value.setObjectName("WorkFieldValue")
        layout.addWidget(value)
        return value

    def update_state(self, stratigraphy) -> None:
        scheme = field_value(stratigraphy, "systems_tract_scheme", "") or "LST/TST/HST"
        boundaries = field_value(stratigraphy, "sequence_boundaries", []) or []
        target = field_value(stratigraphy, "target_horizon", "") or ""
        self.scheme_value.setText(scheme)
        self.boundary_count_value.setText(f"{len(boundaries)} 个")
        self.systems_tract_value.setText(" / ".join(tokens.SYSTEMS_TRACT_LABELS))
        if target:
            self.status_value.setText(f"目标 {target}")
        else:
            self.status_value.setText("未设置目标层位")

    def set_bind_status(self, text: str) -> None:
        self.status_value.setText(text)
