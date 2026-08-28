from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, QEasingCurve, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QGraphicsOpacityEffect, QHBoxLayout, QLineEdit,
    QStackedWidget, QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from paleo_workbench.ui.icon_rail import IconRail
from paleo_workbench.ui.deferred_page_bindings import DeferredPageBindings
from paleo_workbench.ui.menu_bar import MenuBar
from paleo_workbench.ui.page_placeholder import PagePlaceholder
from paleo_workbench.ui.pages.data_page import DataPage
from paleo_workbench.ui.pages.home_page import HomePage
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.ui.pages.preparation_page import PreparationPage
from paleo_workbench.ui.pages.review_export_page import ReviewExportPage
from paleo_workbench.ui.pages.sequence_framework_page import SequenceFrameworkPage
from paleo_workbench.ui.pages.seismic_prediction_page import SeismicPredictionPage
from paleo_workbench.ui.pages.stratigraphy_correlation_page import StratigraphyCorrelationPage
from paleo_workbench.ui.pages.visualization_page import VisualizationPage
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage
from paleo_workbench.ui.pages.geological_modeling_3d_page import GeologicalModeling3DPage
from paleo_workbench.viz.hosts.well_location_preview import (
    WellLocationPreviewStateStore,
)
from paleo_workbench.ui.sidebar import ContextSidebar, TextSidebar
from paleo_workbench.ui.status_bar import StatusBar
from paleo_workbench.ui.workflow_stepper import WorkflowStepper
from paleo_workbench import tokens
from paleo_workbench.project.models import ExportArtifact, ProjectDocument, ResourceItem

from paleo_workbench.ui import navigation
from paleo_workbench.ui.navigation import (
    PAGE_INDEX_DATA,
    PAGE_INDEX_HOME,
    PAGE_INDEX_MAPPING,
    PAGE_INDEX_PREPARATION,
    PAGE_INDEX_REVIEW,
    PAGE_INDEX_SEISMIC,
    PAGE_INDEX_SEQUENCE,
    PAGE_INDEX_STRATIGRAPHY,
    PAGE_INDEX_VISUALIZATION,
    PAGE_INDEX_WELL_LOG,
    PAGE_INDEX_GEOMODEL,
)


class AppShell(QWidget):
    def __init__(
        self,
        project: ProjectDocument | None = None,
        parent=None,
        *,
        defer_nonvisible_bindings: bool = False,
    ):
        super().__init__(parent)
        self.setObjectName("AppShell")
        # One theme system (#1047): the manager renders the token sheet for
        # the active palette; AppShell never bypasses it with a direct
        # tokens.build_qss() call.
        from paleo_workbench.ui.theme import theme_manager

        self.theme_manager = theme_manager
        self.setStyleSheet(self.theme_manager.get_qss())
        self.theme_manager.theme_changed.connect(self._on_theme_changed)
        self.project = project or ProjectDocument.new("Untitled Project")
        self._well_location_state_store = WellLocationPreviewStateStore()
        self._fade_anim: QPropertyAnimation | None = None
        # Opening a large project must not eagerly bind every data-heavy page.
        # These are main-thread callbacks only, keyed by page and operation so
        # repeated refreshes retain just the latest committed project state.
        self._defer_nonvisible_bindings = defer_nonvisible_bindings
        self._deferred_page_bindings = DeferredPageBindings()

        # Stage memory: track the last visited page for each stage
        self._stage_subpage_memory: dict[int, int] = {
            navigation.STAGE_INDEX_DATA: PAGE_INDEX_DATA,
            navigation.STAGE_INDEX_INTERPRETATION: PAGE_INDEX_WELL_LOG,
            navigation.STAGE_INDEX_MAPPING: PAGE_INDEX_MAPPING,
            navigation.STAGE_INDEX_REVIEW: PAGE_INDEX_HOME,
        }

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.menu_bar = MenuBar(self)
        outer.addWidget(self.menu_bar)

        self.workflow_stepper = WorkflowStepper(self)
        outer.addWidget(self.workflow_stepper)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        self.icon_rail = IconRail(self)
        self.icon_rail.setVisible(True)
        self.sidebar = ContextSidebar(self)
        self.sidebar.setVisible(True)
        self.page_stack = QStackedWidget(self)
        self.page_stack.addWidget(HomePage(self.page_stack))        # index 0 = 首页
        self.data_page = DataPage(
            project=self.project,
            well_state_store=self._well_location_state_store,
            parent=self.page_stack,
        )
        self.data_page.data_context_changed.connect(self.update_data_context)
        self.page_stack.addWidget(self.data_page)        # index 1 = 数据
        self._data_context = self._build_data_context()
        self.page_stack.addWidget(WellLogPredictionPage(self.page_stack)) # index 2 = 测井预测
        self.page_stack.addWidget(SeismicPredictionPage(self.page_stack)) # index 3 = 地震预测
        self.page_stack.addWidget(SequenceFrameworkPage(self.page_stack)) # index 4 = 层序格架
        self.page_stack.addWidget(StratigraphyCorrelationPage(self.page_stack))  # index 5 = 地层对比
        self.page_stack.addWidget(
            VisualizationPage(
                well_state_store=self._well_location_state_store,
                parent=self.page_stack,
            )
        ) # index 6 = 可视化
        self.page_stack.addWidget(PreparationPage(self.page_stack)) # index 7 = 制备
        self.mapping_page = MappingPage(self.page_stack)
        self.mapping_page.mapping_context_changed.connect(self.update_mapping_context)
        self.page_stack.addWidget(self.mapping_page)  # index 8 = 编图
        self.page_stack.addWidget(ReviewExportPage(self.page_stack)) # index 9 = 成图审核
        self.geomodel_page = GeologicalModeling3DPage(self.page_stack)
        self._run_or_defer_page_update(
            PAGE_INDEX_GEOMODEL,
            "project",
            lambda: self.geomodel_page.set_project(self.project),
        )
        self.page_stack.addWidget(self.geomodel_page)  # index 10 = 井震联合
        # 井位地图 lives inside the Data page as a collapsible panel (§18);
        # DataPage wires its own map ↔ tree sync and initial domain binding.
        self._mapping_context = self._build_mapping_context()
        middle.addWidget(self.icon_rail)
        middle.addWidget(self.sidebar)
        middle.addWidget(self.page_stack, 1)
        outer.addLayout(middle, 1)

        self.status_bar = StatusBar(self)
        outer.addWidget(self.status_bar)

        # Signal connections
        self.workflow_stepper.stage_changed.connect(self._on_stepper_stage_changed)
        self.sidebar.subpage_selected.connect(self._switch_page)
        self.icon_rail.page_changed.connect(self._switch_page)

        # Sync initial stage with default HomePage (index 0 -> Stage 3: 成图与审核)
        initial_stage = navigation.get_stage_for_page(0)
        self.workflow_stepper.set_active_stage(initial_stage)
        self.sidebar.set_stage(initial_stage, active_page_index=0)

        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        """Register Stage (Ctrl+1~4), Subpage (Alt+1~4), and 1-9/0 digit shortcuts."""
        # 1-9 and 0 digit shortcuts (backward compatibility)
        for i in range(min(10, len(tokens.PAGE_NAMES))):  # keys 1-9,0 only
            digit = str(i + 1) if i < 9 else "0"
            QShortcut(QKeySequence(digit), self,
                      lambda idx=i: self._shortcut_switch_page(idx))

        # Stage shortcuts Ctrl+1 ~ Ctrl+4
        for s in range(4):
            QShortcut(QKeySequence(f"Ctrl+{s + 1}"), self,
                      lambda stage_idx=s: self._shortcut_switch_stage(stage_idx))

        # Subpage shortcuts Alt+1 ~ Alt+4
        for p in range(4):
            QShortcut(QKeySequence(f"Alt+{p + 1}"), self,
                      lambda sub_idx=p: self._shortcut_switch_subpage(sub_idx))

    def _shortcut_switch_stage(self, stage_idx: int) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QTextBrowser)):
            return
        self._on_stepper_stage_changed(stage_idx)

    def _shortcut_switch_subpage(self, sub_idx: int) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QTextBrowser)):
            return
        curr_stage = self.workflow_stepper.active_stage_index
        subpages = navigation.get_subpages_for_stage(curr_stage)
        if 0 <= sub_idx < len(subpages):
            self._switch_page(subpages[sub_idx])

    def _shortcut_switch_page(self, idx: int) -> None:
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit, QTextBrowser)):
            return
        if 0 <= idx < self.page_stack.count():
            self.icon_rail.set_active(idx)
            self._switch_page(idx)

    def _on_stepper_stage_changed(self, stage_index: int) -> None:
        target_page = self._stage_subpage_memory.get(
            stage_index, navigation.get_subpages_for_stage(stage_index)[0]
        )
        self._switch_page(target_page)

    def set_theme(self, mode) -> None:
        """Switch the application theme (#1047): palette change, same tokens."""
        self.theme_manager.set_theme(mode)

    def _on_theme_changed(self, _theme: str) -> None:
        qss = self.theme_manager.get_qss()
        self.setStyleSheet(qss)
        # top-level windows outside this shell (dialogs) follow the theme too
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)

    def _switch_page(self, index: int) -> None:
        if not 0 <= index < self.page_stack.count():
            return
        self._flush_page_updates(index)
        self.page_stack.setCurrentIndex(index)
        page = self.page_stack.widget(index)
        activate = getattr(page, "activate_page", None)
        if callable(activate):
            activate()

        # Update Stage & Subpage state memory
        stage_idx = navigation.get_stage_for_page(index)
        self._stage_subpage_memory[stage_idx] = index
        self.workflow_stepper.set_active_stage(stage_idx)
        self.sidebar.set_stage(stage_idx, active_page_index=index)
        self.icon_rail.set_active(index)

        # The sidebar keeps the user's state across page switches (#1047):
        # visible stays visible, collapsed stays collapsed, and context
        # updates continue so any later reveal is already current.
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
        fade_timer = getattr(self, "_fade_finalize_timer", None)
        if fade_timer is not None:
            fade_timer.stop()
            fade_timer.deleteLater()
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
        def finalize_fade(p=page, e=effect) -> None:
            # A busy offscreen event loop may leave the unified animation
            # timer one frame short of exactly 1.0.  Finalize by identity so
            # stale timers from rapid switches cannot clear a newer effect.
            try:
                if p.graphicsEffect() is e:
                    e.setOpacity(1.0)
                    p.setGraphicsEffect(None)
            except RuntimeError:
                return

        self._fade_anim.finished.connect(finalize_fade)
        self._fade_finalize_timer = QTimer(page)
        self._fade_finalize_timer.setSingleShot(True)
        self._fade_finalize_timer.timeout.connect(finalize_fade)
        self._fade_finalize_timer.start(self._fade_anim.duration())
        self._fade_anim.start()

    def data_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_DATA)

    def home_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_HOME)

    def mapping_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_MAPPING)

    def shutdown_workers(self, wait_ms: int = 3_000) -> bool:
        """Deterministically release project-scoped jobs before a switch.

        Page ``closeEvent`` handlers remain a last line of defence, but a
        project switch must not wait for Qt deferred deletion before closing a
        catalog or replacing native sessions.
        """
        all_joined = True
        for index in range(self.page_stack.count()):
            page = self.page_stack.widget(index)
            if page is None:
                continue
            shutdown = getattr(page, "shutdown_workers", None)
            if callable(shutdown):
                result = shutdown(wait_ms)
                if result is False:
                    all_joined = False
                continue
            shutdown = getattr(page, "_shutdown_workers", None)
            if callable(shutdown):
                result = shutdown()
                if result is False:
                    all_joined = False
        joint_shutdown = getattr(getattr(self, "geomodel_page", None), "_joint_host", None)
        shutdown = getattr(joint_shutdown, "shutdown", None)
        if callable(shutdown):
            shutdown()
        return all_joined

    def _run_or_defer_page_update(
        self, index: int, name: str, callback
    ) -> None:
        """Apply a page binding now, or retain its newest state until visit."""

        if (
            self._defer_nonvisible_bindings
            and index != PAGE_INDEX_DATA
            and index != PAGE_INDEX_HOME
            and self.page_stack.currentIndex() != index
        ):
            self._deferred_page_bindings.schedule(index, name, callback)
            return
        callback()

    def _update_or_defer_page(
        self, index: int, name: str, callback
    ) -> None:
        """Apply a semantic page state refresh, even after its first visit."""

        if self._defer_nonvisible_bindings and index != self.page_stack.currentIndex():
            self._deferred_page_bindings.schedule(index, name, callback)
            return
        callback()

    def defer_page_project_binding(self, index: int, page) -> None:
        """Let workflow wiring bind a project without defeating lazy open."""

        setter = getattr(page, "set_project", None)
        if callable(setter):
            self._run_or_defer_page_update(
                index,
                "project",
                lambda: setter(self.project),
            )

    def _flush_page_updates(self, index: int) -> None:
        self._deferred_page_bindings.flush(index)

    def has_deferred_page_updates(self, index: int) -> bool:
        """Testing/diagnostic seam for first-usable-project page binding."""

        return self._deferred_page_bindings.has_pending(index)

    def set_project_name(self, name: str) -> None:
        self.status_bar.set_project_name(name)

    # --- Well Location GIS ↔ Data Manager sync (§18) -----------------
    # The map is embedded in the Data page (WellMapPanel); sync is wired
    # inside DataPage itself.


    def update_home_page(self, state: dict, steps: list, project=None) -> None:
        home = self.page_stack.widget(PAGE_INDEX_HOME)
        if hasattr(home, "update_state"):
            # Optional project enables Stage-11 readiness on the contract panel.
            try:
                home.update_state(state, steps, project=project)
            except TypeError:
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
        # Keep the embedded well-location map in sync with the document (§18).
        refresh_map = getattr(page, "refresh_well_map_panel", None)
        if callable(refresh_map):
            refresh_map()

    def set_data_project_path(self, path) -> None:
        """Propagate the open ``*.paleo.json`` path to every project-bound page.

        DataPage, VisualizationPage, WellLogPredictionPage,
        StratigraphyCorrelationPage and ReviewExportPage derive artifact /
        export locations from the real project file path; without this
        routing they would fabricate ``project.paleo.json`` / ``x.paleo.json``
        names and write into phantom ``.artifacts/`` trees. Pages without a
        ``set_project_path`` hook are skipped.
        """
        for index in range(self.page_stack.count()):
            page = self.page_stack.widget(index)
            if page is None or not hasattr(page, "set_project_path"):
                continue
            try:
                page.set_project_path(path)
            except Exception:
                continue

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
        page = self.page_stack.widget(PAGE_INDEX_WELL_LOG)
        selected_project = project if project is not None else self.project

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(selected_project)
            if hasattr(page, "update_state"):
                page.update_state(prediction_tasks, project=selected_project)

        self._update_or_defer_page(PAGE_INDEX_WELL_LOG, "state", update)

    def well_log_prediction_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_WELL_LOG)

    def update_seismic_prediction_page(self, prediction_tasks: list, project=None) -> None:
        page = self.page_stack.widget(PAGE_INDEX_SEISMIC)
        selected_project = project if project is not None else self.project

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(selected_project)
            if hasattr(page, "update_state"):
                page.update_state(prediction_tasks, project=selected_project)

        self._update_or_defer_page(PAGE_INDEX_SEISMIC, "state", update)

    def seismic_prediction_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_SEISMIC)

    def update_sequence_framework_page(self, stratigraphy) -> None:
        page = self.page_stack.widget(PAGE_INDEX_SEQUENCE)

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(self.project)
            if hasattr(page, "update_state"):
                page.update_state(stratigraphy)

        self._update_or_defer_page(PAGE_INDEX_SEQUENCE, "state", update)

    def sequence_framework_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_SEQUENCE)

    def update_stratigraphy_correlation_page(self, project=None) -> None:
        page = self.page_stack.widget(PAGE_INDEX_STRATIGRAPHY)
        selected_project = project if project is not None else self.project

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(selected_project)
            if hasattr(page, "update_state"):
                page.update_state(selected_project)

        self._update_or_defer_page(PAGE_INDEX_STRATIGRAPHY, "state", update)

    def stratigraphy_correlation_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_STRATIGRAPHY)

    def update_visualization_page(
        self,
        resources: list,
        prediction_tasks: list,
        map_documents: list,
        project=None,
    ) -> None:
        page = self.page_stack.widget(PAGE_INDEX_VISUALIZATION)
        selected_project = project if project is not None else self.project

        def update() -> None:
            if hasattr(page, "update_state"):
                page.update_state(
                    resources,
                    prediction_tasks,
                    map_documents,
                    project=selected_project,
                )

        self._update_or_defer_page(PAGE_INDEX_VISUALIZATION, "state", update)

    def update_preparation_page(self, tasks: list) -> None:
        page = self.page_stack.widget(PAGE_INDEX_PREPARATION)

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(self.project)
            if hasattr(page, "update_state"):
                page.update_state(tasks)

        self._update_or_defer_page(PAGE_INDEX_PREPARATION, "state", update)

    def preparation_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_PREPARATION)

    def update_mapping_page(
        self,
        map_documents: list,
        *,
        factor_tasks: list | None = None,
        project_crs: str | None = None,
    ) -> None:
        page = self.mapping_page_widget()

        def update() -> None:
            if hasattr(page, "update_state"):
                page.update_state(
                    map_documents,
                    factor_tasks=factor_tasks,
                    project_crs=project_crs,
                )
            self._mapping_context = self._build_mapping_context()
            if self.page_stack.currentIndex() == PAGE_INDEX_MAPPING:
                self.sidebar.update_mapping_context(**self._mapping_context)

        self._update_or_defer_page(PAGE_INDEX_MAPPING, "state", update)

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
        page = self.page_stack.widget(PAGE_INDEX_REVIEW)

        def update() -> None:
            if hasattr(page, "set_project"):
                page.set_project(self.project)
            if hasattr(page, "update_state"):
                page.update_state(reports, map_documents, artifacts)

        self._update_or_defer_page(PAGE_INDEX_REVIEW, "state", update)

    def review_export_page_widget(self):
        return self.page_stack.widget(PAGE_INDEX_REVIEW)
