from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
)

from paleo_workbench.ui.header_toolbar import HeaderToolbar
from paleo_workbench.ui.icon_rail import IconRail
from paleo_workbench.ui.menu_bar import MenuBar
from paleo_workbench.ui.page_placeholder import PagePlaceholder
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.home_page import HomePage
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.ui.pages.preparation_page import PreparationPage
from paleo_workbench.ui.pages.review_export_page import ReviewExportPage
from paleo_workbench.ui.pages.sequence_framework_page import SequenceFrameworkPage
from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage
from paleo_workbench.ui.pages.visualization_page import VisualizationPage
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage
from paleo_workbench.ui.sidebar import TextSidebar
from paleo_workbench.ui.status_bar import StatusBar
from paleo_workbench.ui import tokens
from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem


class AppShell(QWidget):
    def __init__(self, project: ProjectDocument | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("AppShell")
        self.project = project or ProjectDocument.new("Untitled Project")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.menu_bar = MenuBar()
        self.header_toolbar = HeaderToolbar()
        outer.addWidget(self.menu_bar)
        outer.addWidget(self.header_toolbar)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        self.icon_rail = IconRail()
        self.sidebar = TextSidebar()
        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(HomePage())        # index 0 = 首页
        self.data_page = DataPage(project=self.project)
        self.data_page.data_context_changed.connect(self.update_data_context)
        self.page_stack.addWidget(self.data_page)        # index 1 = 数据
        self.update_data_context(self._build_data_context())
        self.page_stack.addWidget(WellLogPredictionPage()) # index 2 = 测井预测
        self.page_stack.addWidget(SeismicPredictionPage()) # index 3 = 地震预测
        self.page_stack.addWidget(SequenceFrameworkPage()) # index 4 = 层序格架
        self.page_stack.addWidget(VisualizationPage()) # index 5 = 可视化
        self.page_stack.addWidget(PreparationPage()) # index 6 = 制备
        self.page_stack.addWidget(MappingPage())      # index 7 = 编图
        self.page_stack.addWidget(ReviewExportPage()) # index 8 = 成图审核
        middle.addWidget(self.icon_rail)
        middle.addWidget(self.sidebar)
        middle.addWidget(self.page_stack, 1)
        outer.addLayout(middle, 1)

        self.status_bar = StatusBar()
        outer.addWidget(self.status_bar)

        self.icon_rail.page_changed.connect(self._switch_page)

    def _switch_page(self, index: int) -> None:
        self.page_stack.setCurrentIndex(index)
        self.sidebar.set_context(tokens.PAGE_NAMES[index])

    def set_project_name(self, name: str) -> None:
        self.status_bar.set_project_name(name)

    def update_home_page(self, state: dict, steps: list) -> None:
        home = self.page_stack.widget(0)
        if hasattr(home, "update_state"):
            home.update_state(state, steps)

    def update_data_page(
        self,
        state: dict,
        resources: list,
        artifacts: list | None = None,
    ) -> None:
        current_artifacts = artifacts or []
        page = self.page_stack.widget(1)
        if hasattr(page, "update_state"):
            page.update_state(state, resources, current_artifacts)
        self.update_data_context(
            self._build_data_context(resources=resources, artifacts=current_artifacts)
        )

    def update_data_context(self, context: dict) -> None:
        self.sidebar.update_data_context(
            resource_count=context.get("resource_count", 0),
            artifact_count=context.get("artifact_count", 0),
            issue_count=context.get("issue_count", 0),
            selected_name=context.get("selected_name", "未选择"),
            selected_type=context.get("selected_type", ""),
            selected_format=context.get("selected_format", ""),
            reader_mode=context.get("reader_mode", "empty"),
        )

    def _build_data_context(
        self,
        resources: list[ResourceItem] | None = None,
        artifacts: list[ExportArtifact] | None = None,
    ) -> dict:
        current_resources = resources if resources is not None else self.project.resources
        current_artifacts = (
            artifacts if artifacts is not None else self.project.export_artifacts
        )
        issue_count = sum(
            1
            for resource in current_resources
            if resource.status in {"missing", "warning", "failed", "error"}
        )
        selected = getattr(self.data_page, "_selected_asset", None)
        selected_name = "未选择"
        selected_type = ""
        selected_format = ""
        if isinstance(selected, ResourceItem):
            selected_name = selected.name
            selected_type = selected.type
            selected_format = selected.format
        elif isinstance(selected, ExportArtifact):
            selected_name = Path(selected.output_path).name
            selected_type = "成果"
            selected_format = selected.format
        return {
            "resource_count": len(current_resources),
            "artifact_count": len(current_artifacts),
            "issue_count": issue_count,
            "selected_name": selected_name,
            "selected_type": selected_type,
            "selected_format": selected_format,
            "reader_mode": self.data_page.current_reader_mode(),
        }

    def update_well_log_prediction_page(self, prediction_tasks: list) -> None:
        page = self.page_stack.widget(2)
        if hasattr(page, "update_state"):
            page.update_state(prediction_tasks)

    def update_seismic_prediction_page(self, prediction_tasks: list) -> None:
        page = self.page_stack.widget(3)
        if hasattr(page, "update_state"):
            page.update_state(prediction_tasks)

    def update_sequence_framework_page(self, stratigraphy) -> None:
        page = self.page_stack.widget(4)
        if hasattr(page, "update_state"):
            page.update_state(stratigraphy)

    def update_visualization_page(self, resources: list, prediction_tasks: list, map_documents: list) -> None:
        page = self.page_stack.widget(5)
        if hasattr(page, "update_state"):
            page.update_state(resources, prediction_tasks, map_documents)

    def update_preparation_page(self, tasks: list) -> None:
        page = self.page_stack.widget(6)
        if hasattr(page, "update_state"):
            page.update_state(tasks)

    def update_mapping_page(self, map_documents: list) -> None:
        page = self.page_stack.widget(7)
        if hasattr(page, "update_state"):
            page.update_state(map_documents)

    def update_review_export_page(self, reports: list, map_documents: list, artifacts: list) -> None:
        page = self.page_stack.widget(8)
        if hasattr(page, "update_state"):
            page.update_state(reports, map_documents, artifacts)
