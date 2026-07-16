from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid


class MapFactorShelf(QWidget):
    """Mapping bottom-tab shelf: factor cards + contour draft action."""

    contour_draft_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(tokens.SPACE_2)

        actions = QHBoxLayout()
        actions.setContentsMargins(tokens.SPACE_2, tokens.SPACE_1, tokens.SPACE_2, 0)
        self.contour_draft_btn = QPushButton("从单因素生成等值线初稿")
        self.contour_draft_btn.setObjectName("SecondaryButton")
        self.contour_draft_btn.setMinimumHeight(tokens.CONTROL_HEIGHT)
        self.contour_draft_btn.setToolTip(
            "对已完成网格的单因素任务提取 ContourDraft 并写入当前工程图件"
        )
        self.contour_draft_btn.clicked.connect(self.contour_draft_requested.emit)
        actions.addWidget(self.contour_draft_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.grid = FactorPreviewGrid()
        layout.addWidget(self.grid, 1)

    def update_state(self, tasks: list) -> None:
        self.grid.update_state(tasks)
