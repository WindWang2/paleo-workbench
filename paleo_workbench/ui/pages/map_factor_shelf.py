from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget

from paleo_workbench.ui.pages.factor_preview_grid import FactorPreviewGrid


class MapFactorShelf(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.grid = FactorPreviewGrid()
        layout.addWidget(self.grid)

    def update_state(self, tasks: list) -> None:
        self.grid.update_state(tasks)
