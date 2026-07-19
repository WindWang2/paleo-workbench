from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QLabel, QScrollArea

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.activity_card import RecentActivityCard
from paleo_workbench.ui.pages.completeness_card import DataCompletenessCard
from paleo_workbench.ui.pages.workflow_progress import WorkflowProgress
from paleo_workbench.ui.pages.module_relationship import ModuleRelationshipWidget, LegendWidget


class HomePage(QWidget):
    navigation_requested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HomePage")
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Scroll Area to handle smaller screens gracefully
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        main_layout.addWidget(scroll)
        
        container = QWidget()
        container.setObjectName("HomeContainer")
        scroll.setWidget(container)
        
        layout = QVBoxLayout(container)
        layout.setContentsMargins(
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
            tokens.PAGE_MARGIN,
        )
        layout.setSpacing(tokens.SPACE_3)
        
        self.workflow_progress = WorkflowProgress()
        layout.addWidget(self.workflow_progress)
        
        # Title of the module relationship diagram
        title_container = QHBoxLayout()
        title_container.setContentsMargins(4, 0, 4, 0)
        
        title_label = QLabel("智能岩相古地理重建系统 - 模块关系图")
        title_label.setStyleSheet(f"""
            font-size: 14.5px;
            font-weight: bold;
            color: #1e56a0;
            font-family: {tokens.FONT_FAMILY};
        """)
        title_container.addWidget(title_label)
        
        # Add legend widget
        self.legend = LegendWidget()
        title_container.addWidget(self.legend)
        
        layout.addLayout(title_container)
        
        # Add relationship widget
        self.relationship_widget = ModuleRelationshipWidget()
        self.relationship_widget.setMinimumWidth(1100)
        self.relationship_widget.navigation_requested.connect(self.navigation_requested.emit)
        layout.addWidget(self.relationship_widget, 1)
        
        # Set minimum width on container to prevent horizontal compression in scroll area
        container.setMinimumWidth(1140)
        
        bottom = QHBoxLayout()
        bottom.setSpacing(tokens.SPACE_3)
        self.activity_card = RecentActivityCard()
        self.completeness_card = DataCompletenessCard()
        bottom.addWidget(self.activity_card, 1)
        bottom.addWidget(self.completeness_card, 0)
        layout.addLayout(bottom, 0)

    def update_state(self, state: dict, steps: list) -> None:
        self.workflow_progress.update_steps(steps)
        self.relationship_widget.update_states(steps)
        self.activity_card.update_state(state, steps)
        self.completeness_card.update_state(state)
