from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.activity_card import RecentActivityCard
from paleo_workbench.ui.pages.completeness_card import DataCompletenessCard
from paleo_workbench.ui.pages.workflow_progress import WorkflowProgress


class HomePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        layout.setSpacing(tokens.SPACE_3)
        self.workflow_progress = WorkflowProgress()
        layout.addWidget(self.workflow_progress)
        bottom = QHBoxLayout()
        bottom.setSpacing(tokens.SPACE_3)
        self.activity_card = RecentActivityCard()
        self.completeness_card = DataCompletenessCard()
        bottom.addWidget(self.activity_card, 1)
        bottom.addWidget(self.completeness_card, 0)
        layout.addLayout(bottom, 1)

    def update_state(self, state: dict, steps: list) -> None:
        self.workflow_progress.update_steps(steps)
        self.activity_card.update_state(state, steps)
        self.completeness_card.update_state(state)
