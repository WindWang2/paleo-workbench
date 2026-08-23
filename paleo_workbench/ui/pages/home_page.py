from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget, QLabel, QScrollArea

from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.activity_card import RecentActivityCard
from paleo_workbench.ui.pages.completeness_card import DataCompletenessCard
from paleo_workbench.ui.pages.workflow_progress import WorkflowProgress
from paleo_workbench.ui.pages.module_relationship import ModuleRelationshipWidget, LegendWidget
from paleo_workbench.ui.pages.workflow_contract_panel import WorkflowContractPanel


class HomePage(QWidget):
    navigation_requested = Signal(int)
    new_project_requested = Signal()
    open_project_requested = Signal()
    open_sample_requested = Signal()

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

        from paleo_workbench.ui.pages.onboarding_report_card import OnboardingReportCard
        from paleo_workbench.ui.pages.start_guide_card import StartGuideCard

        self.start_guide_card = StartGuideCard()
        self.start_guide_card.new_project_requested.connect(self.new_project_requested.emit)
        self.start_guide_card.open_project_requested.connect(self.open_project_requested.emit)
        self.start_guide_card.open_sample_requested.connect(self.open_sample_requested.emit)
        self.onboarding_report_card = OnboardingReportCard()

        self.workflow_progress = WorkflowProgress()
        layout.addWidget(self.start_guide_card)
        layout.addWidget(self.onboarding_report_card)
        layout.addWidget(self.workflow_progress)

        # Title of the module relationship diagram
        title_container = QHBoxLayout()
        title_container.setContentsMargins(4, 0, 4, 0)

        title_label = QLabel("智能岩相古地理重建系统 - 模块关系图")
        title_label.setStyleSheet(f"""
            font-size: {tokens.FONT_SIZE_TITLE};
            font-weight: {tokens.FONT_WEIGHT_TITLE};
            color: {tokens.PRIMARY};
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
        self.contract_panel = WorkflowContractPanel()
        self.contract_panel.setMinimumWidth(280)
        self.contract_panel.setMaximumHeight(320)
        bottom.addWidget(self.activity_card, 1)
        bottom.addWidget(self.contract_panel, 1)
        bottom.addWidget(self.completeness_card, 0)
        layout.addLayout(bottom, 0)
        self._project = None

    def update_state(self, state: dict, steps: list, project=None) -> None:
        self.workflow_progress.update_steps(steps)
        self.relationship_widget.update_states(steps)
        self.activity_card.update_state(state, steps)
        self.completeness_card.update_state(state)
        if project is not None:
            self._project = project
        if self._project is not None:
            self.contract_panel.set_project(self._project)
            # Map first incomplete/stale-ish step to a contract if possible
            step_to_contract = {
                "data_check": "data_import",
                "factor_map": "factor_interpolation",
                "prediction": "facies_prediction",
                "map_compile": "paleomap_compile",
                "qc": "quality_control",
                "export": "export",
            }
            for step in steps:
                cid = step_to_contract.get(getattr(step, "step_type", ""))
                if cid and getattr(step, "status", "") in {
                    "pending",
                    "stale",
                    "running",
                    "warning",
                }:
                    self.contract_panel.set_contract_id(cid)
                    break
        # Start guide visibility: no resources and no onboarding report
        resource_counts = state.get("resource_counts") if isinstance(state, dict) else None
        total_resources = 0
        if isinstance(resource_counts, dict):
            try:
                total_resources = sum(int(v) for v in resource_counts.values())
            except Exception:
                total_resources = 0
        onboarding = {}
        proj = project if project is not None else self._project
        if proj is not None:
            onboarding = getattr(proj, "onboarding_report", {}) or {}
        has_report = bool(onboarding)
        if hasattr(self, "start_guide_card"):
            show_guide = (total_resources == 0 and not has_report)
            self.start_guide_card.setVisible(show_guide)
        if hasattr(self, "onboarding_report_card"):
            report = onboarding if has_report else None
            # Also handle project is None case
            if proj is None:
                report = None
            else:
                report = onboarding if has_report else None
            self.onboarding_report_card.set_report(report)
