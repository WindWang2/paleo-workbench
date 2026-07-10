from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.sequence_boundary_table import SequenceBoundaryTable
from paleo_workbench.ui.pages.sequence_scheme_summary import SequenceSchemeSummary
from paleo_workbench.ui.pages.sequence_target_panel import SequenceTargetPanel


class SequenceFrameworkPage(QWidget):
    """Display-only 层序格架 page backed by project stratigraphy metadata."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SequenceFrameworkPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        outer.setSpacing(16)

        content = QHBoxLayout()
        content.setSpacing(16)

        self.target_panel = SequenceTargetPanel()
        content.addWidget(self.target_panel, 0)

        self.boundary_table = SequenceBoundaryTable()
        content.addWidget(self.boundary_table, 1)

        self.scheme_summary = SequenceSchemeSummary()
        content.addWidget(self.scheme_summary, 0)

        outer.addLayout(content, 1)

    def update_state(self, stratigraphy) -> None:
        self.target_panel.update_state(stratigraphy)
        self.boundary_table.update_state(stratigraphy)
        self.scheme_summary.update_state(stratigraphy)
