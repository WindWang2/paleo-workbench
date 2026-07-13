from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QLabel, QPushButton, QVBoxLayout

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.filter_index import CATEGORIES


class DataCatalogPanel(QFrame):
    category_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataCatalogPanel")
        self.setFixedWidth(180)
        self.setStyleSheet(
            f"QFrame#DataCatalogPanel {{ background: {tokens.BG_SIDEBAR};"
            f" border: 1px solid {tokens.BORDER};"
            f" border-radius: {tokens.RADIUS_CARD}px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        self.title_label = QLabel("数据目录")
        self.title_label.setStyleSheet(
            f"color: {tokens.TEXT_PRIMARY}; font-weight: 600;"
        )
        layout.addWidget(self.title_label)

        self.category_labels: dict[str, QPushButton] = {}
        for label in CATEGORIES:
            button = QPushButton(f"{label} 0")
            button.setObjectName("SecondaryButton")
            button.clicked.connect(
                lambda _checked=False, name=label: self.category_changed.emit(name)
            )
            self.category_labels[label] = button
            layout.addWidget(button)

        layout.addStretch()

    def update_counts(self, resources: list, artifacts: list) -> None:
        # CATEGORIES now lives in filter_index (canonical home). Importing
        # compute_category_counts here is no longer circular. Temporary wiring
        # — DataCatalogPanel is replaced by NavigationTree and deleted in Task 6.
        from paleo_workbench.ui.pages.filter_index import compute_category_counts

        counts = compute_category_counts(resources, artifacts)
        for label, count in counts.items():
            if label in self.category_labels:
                self.category_labels[label].setText(f"{label} {count}")
