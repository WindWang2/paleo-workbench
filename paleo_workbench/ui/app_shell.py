from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QGraphicsOpacityEffect, QHBoxLayout, QLineEdit,
    QStackedWidget, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

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

# Stable page indices (avoid magic numbers in callers/tests).
PAGE_INDEX_HOME = 0
PAGE_INDEX_DATA = 1
PAGE_INDEX_WELL_LOG = 2
PAGE_INDEX_SEISMIC = 3
PAGE_INDEX_SEQUENCE = 4
PAGE_INDEX_VISUALIZATION = 5
PAGE_INDEX_PREPARATION = 6
PAGE_INDEX_MAPPING = 7
PAGE_INDEX_REVIEW = 8


class AppShell(QWidget):
    def __init__(self, project: ProjectDocument | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("AppShell")
        self.project = project or ProjectDocument.new("Untitled Project")
        self._fade_anim: QPropertyAnimation | None = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.menu_bar = MenuBar()
        outer.addWidget(self.menu_bar)

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
        self._data_context = self._build_data_context()
        self.page_stack.addWidget(WellLogPredictionPage()) # index 2 = 测井预测
        self.page_stack.addWidget(SeismicPredictionPage()) # index 3 = 地震预测
        self.page_stack.addWidget(SequenceFrameworkPage()) # index 4 = 层序格架
        self.page_stack.addWidget(VisualizationPage()) # index 5 = 可视化
        self.page_stack.addWidget(PreparationPage()) # index 6 = 制备
        self.mapping_page = MappingPage()
        self.mapping_page.mapping_context_changed.connect(self.update_mapping_context)
        self.page_stack.addWidget(self.mapping_page)  # index 7 = 编图
        self.page_stack.addWidget(ReviewExportPage()) # index 8 = 成图审核
        self._mapping_context = self._build_mapping_context()
        middle.addWidget(self.icon_rail)
        middle.addWidget(self.sidebar)
        middle.addWidget(self.page_stack, 1)
        outer.addLayout(middle, 1)

        self.status_bar = StatusBar()
        outer.addWidget(self.status_bar)

        self.icon_rail.page_changed.connect(self._switch_page)

        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        """Register 1-9 digit shortcuts that switch the active page.

        The guard in :meth:`_shortcut_switch_page` blocks these while a text
        field has focus so digit entry isn't hijacked.
        """
        for i in range(min(9, len(tokens.PAGE_NAMES))):
            digit = str(i + 1)
            QShortcut(QKeySequence(digit), self,
                      lambda idx=i: self._shortcut_switch_page(idx))

    def _shortcut_switch_page(self, idx: int) -> None:
        """Page-switch handler bound to the 1-9 digit shortcuts.

        No-op when a text-entry widget (QLineEdit/QTextEdit/QTextBrowser) has
        focus, so typing digits into search/name fields isn't intercepted.
        """
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QTextBrowser)):
            return
        if 0 <= idx < self.page_stack.count():
            # Keep the icon-rail's visual active state in sync with the page.
            self.icon_rail.set_active(idx)
            self._switch_page(idx)

    def _switch_page(self, index: int) -> None:
        self.page_stack.setCurrentIndex(index)
        self.sidebar.setVisible(index != PAGE_INDEX_DATA)
        if index == PAGE_INDEX_DATA:
            self.sidebar.update_data_context(**self._data_context)
        elif index == PAGE_INDEX_MAPPING:
            self.sidebar.update_mapping_context(**self._mapping_context)
        else:
            self.sidebar.set_context(tokens.PAGE_NAMES[index])
        self._animate_page_fade(index)

    def _animate_page_fade(self, index: int) -> None:
        """Fade the newly switched page in from 0.7 to 1.0 opacity (150ms).

        A fresh :class:`QGraphicsOpacityEffect` is installed on each switch so
        rapid back-to-back switches restart cleanly: the previous animation is
        stopped and both the previous and current pages are restored to full
        opacity before the new fade begins.
        """
        page = self.page_stack.widget(index)
        if page is None:
            return
        # Stop any in-flight animation and clear effects on the last faded page.
        if self._fade_anim is not None:
            self._fade_anim.stop()
        prev = getattr(self, "_fade_page", None)
        if prev is not None and prev is not page:
            prev.setGraphicsEffect(None)
        existing = page.graphicsEffect()
        if isinstance(existing, QGraphicsOpacityEffect):
            existing.setOpacity(1.0)
            page.setGraphicsEffect(None)
        effect = QGraphicsOpacityEffect(page)
        effect.setOpacity(0.7)
        page.setGraphicsEffect(effect)
        self._fade_page = page
        self._fade_anim = QPropertyAnimation(effect, b"opacity", page)
        self._fade_anim.setDuration(150)
        self._fade_anim.setStartValue(0.7)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._fade_anim.finished.connect(lambda p=page: p.setGraphicsEffect(None))
        self._fade_anim.start()

    def data_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_DATA)

    def mapping_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_MAPPING)

    def set_project_name(self, name: str) -> None:
        self.status_bar.set_project_name(name)

    def update_home_page(self, state: dict, steps: list) -> None:
        home = self.page_stack.widget(PAGE_INDEX_HOME)
        if hasattr(home, "update_state"):
            home.update_state(state, steps)

    def update_data_page(
        self,
        state: dict,
        resources: list,
        artifacts: list | None = None,
        *,
        project_path=None,
    ) -> None:
        current_artifacts = artifacts or []
        page = self.data_page_widget()
        if project_path is not None and hasattr(page, "set_project_path"):
            page.set_project_path(project_path)
        if hasattr(page, "update_state"):
            page.update_state(state, resources, current_artifacts)
        self._data_context = self._build_data_context(
            resources=resources, artifacts=current_artifacts
        )
        if self.page_stack.currentIndex() == PAGE_INDEX_DATA:
            self.sidebar.update_data_context(**self._data_context)

    def set_data_project_path(self, path) -> None:
        """Propagate the open ``*.paleo.json`` path to DataPage I/O."""
        page = self.data_page_widget()
        if hasattr(page, "set_project_path"):
            page.set_project_path(path)

    def update_data_context(self, context: dict) -> None:
        self._data_context = {
            "resource_count": context.get("resource_count", 0),
            "artifact_count": context.get("artifact_count", 0),
            "issue_count": context.get("issue_count", 0),
            "selected_name": context.get("selected_name", "未选择"),
            "selected_type": context.get("selected_type", ""),
            "selected_format": context.get("selected_format", ""),
            "reader_mode": context.get("reader_mode", "empty"),
        }
        if self.page_stack.currentIndex() == 1:
            self.sidebar.update_data_context(**self._data_context)

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

    def update_well_log_prediction_page(self, prediction_tasks: list, project=None) -> None:
        page = self.page_stack.widget(2)
        if hasattr(page, "update_state"):
            page.update_state(prediction_tasks, project=project)

    def update_seismic_prediction_page(self, prediction_tasks: list, project=None) -> None:
        page = self.page_stack.widget(3)
        if hasattr(page, "update_state"):
            page.update_state(prediction_tasks, project=project)

    def update_sequence_framework_page(self, stratigraphy) -> None:
        page = self.page_stack.widget(4)
        if hasattr(page, "update_state"):
            page.update_state(stratigraphy)

    def update_visualization_page(
        self,
        resources: list,
        prediction_tasks: list,
        map_documents: list,
        project=None,
    ) -> None:
        page = self.page_stack.widget(5)
        if hasattr(page, "update_state"):
            page.update_state(
                resources,
                prediction_tasks,
                map_documents,
                project=project if project is not None else self.project,
            )

    def update_preparation_page(self, tasks: list) -> None:
        page = self.page_stack.widget(6)
        if hasattr(page, "set_project"):
            page.set_project(self.project)
        if hasattr(page, "update_state"):
            page.update_state(tasks)

    def preparation_page_widget(self):
        return self.page_stack.widget(6)

    def update_mapping_page(
        self,
        map_documents: list,
        *,
        factor_tasks: list | None = None,
        project_crs: str | None = None,
    ) -> None:
        page = self.mapping_page_widget()
        if hasattr(page, "update_state"):
            page.update_state(
                map_documents,
                factor_tasks=factor_tasks,
                project_crs=project_crs,
            )
        self._mapping_context = self._build_mapping_context()
        if self.page_stack.currentIndex() == PAGE_INDEX_MAPPING:
            self.sidebar.update_mapping_context(**self._mapping_context)

    def update_mapping_context(self, context: dict) -> None:
        self._mapping_context = self._normalize_mapping_context(context)
        if self.page_stack.currentIndex() == PAGE_INDEX_MAPPING:
            self.sidebar.update_mapping_context(**self._mapping_context)

    def _build_mapping_context(self) -> dict:
        page = self.mapping_page_widget()
        if hasattr(page, "mapping_context"):
            return self._normalize_mapping_context(page.mapping_context())
        return self._normalize_mapping_context({})

    @staticmethod
    def _normalize_mapping_context(context: dict | None) -> dict:
        ctx = context or {}
        return {
            "map_name": ctx.get("map_name", "未选择") or "未选择",
            "horizon": ctx.get("horizon", "") or "",
            "dirty": bool(ctx.get("dirty", False)),
            "preview": bool(ctx.get("preview", False)),
        }

    def update_review_export_page(self, reports: list, map_documents: list, artifacts: list) -> None:
        page = self.page_stack.widget(8)
        if hasattr(page, "update_state"):
            page.update_state(reports, map_documents, artifacts)
