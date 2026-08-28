from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QMessageBox, QVBoxLayout, QWidget

from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui import AppShell
from paleo_workbench.ui import tokens
from paleo_workbench.ui.pages.preview_settings import PreviewSettingsStore
from paleo_workbench.ui.project_controller import ProjectController
from paleo_workbench.ui.workflow_controller import WorkflowController
from paleo_workbench.workflow.qc import active_quality_reports
from paleo_workbench.workflow.service import dashboard_state, home_workflow_steps


class PaleoWorkbenchWindow(QWidget):
    """The main application window for Paleogeography Workbench.

    Delegates project lifecycle management to ProjectController and cross-page
    workflow/wiring coordination to WorkflowController.
    """

    def __init__(
        self,
        project: ProjectDocument | None = None,
        *,
        preview_settings_store: PreviewSettingsStore | None = None,
    ):
        super().__init__()
        self._project = project or ProjectDocument.new("Untitled Project")
        self._project_path: Path | None = None
        self._preview_settings_store = preview_settings_store

        self.project_controller = ProjectController(self)
        self.workflow_controller = WorkflowController(self)

        self.resize(1440, 900)
        # 低于该尺寸时多页工作台（图标栏 + 页面栈）会挤压变形，禁止缩到不可用。
        self.setMinimumSize(1180, 720)

        self.outer_layout = QVBoxLayout(self)
        self.outer_layout.setContentsMargins(0, 0, 0, 0)

        self.app_shell = AppShell(project=self.project, parent=self)
        self._apply_project_to_shell()
        self.outer_layout.addWidget(self.app_shell)
        self._wire_menu_bar()
        self._setup_shortcuts()
        self._update_title()

    @property
    def project(self) -> ProjectDocument:
        return self._project

    @project.setter
    def project(self, val: ProjectDocument) -> None:
        self._project = val

    @property
    def project_path(self) -> Path | None:
        return self._project_path

    @project_path.setter
    def project_path(self, val: Path | None) -> None:
        self._project_path = val

    @property
    def _last_open_error(self) -> str | None:
        return self.project_controller._last_open_error

    @_last_open_error.setter
    def _last_open_error(self, val: str | None) -> None:
        self.project_controller._last_open_error = val

    @property
    def _confirm_title(self) -> str | None:
        return self.project_controller._confirm_title

    @_confirm_title.setter
    def _confirm_title(self, val: str | None) -> None:
        self.project_controller._confirm_title = val

    @property
    def _confirm_message(self) -> str | None:
        return self.project_controller._confirm_message

    @_confirm_message.setter
    def _confirm_message(self, val: str | None) -> None:
        self.project_controller._confirm_message = val

    @property
    def _preview_settings_dialog(self):
        return self.workflow_controller.preview_settings_dialog

    @_preview_settings_dialog.setter
    def _preview_settings_dialog(self, val) -> None:
        self.workflow_controller.preview_settings_dialog = val

    def _setup_shortcuts(self) -> None:
        """Window-scoped project-op shortcuts.

        Parented to ``self`` (the window) so they survive shell rebuilds; the
        callbacks read the current ``self.app_shell`` at call-time.
        """
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_project)
        QShortcut(QKeySequence("Ctrl+N"), self, self._on_new_project)
        QShortcut(QKeySequence("Ctrl+O"), self, self._on_open_project)
        QShortcut(QKeySequence("Ctrl+F"), self, self._shortcut_focus_search)

    def _shortcut_focus_search(self) -> None:
        """Focus the active search box.

        If the data page is active (it has a toolbar with its own search box),
        focus that; otherwise fall back to the header/menu-bar search box.
        """
        page = self.app_shell.page_stack.currentWidget()
        toolbar = getattr(page, "data_toolbar", None)
        if toolbar is not None and hasattr(toolbar, "search_box"):
            toolbar.search_box.setFocus()
            return
        self.app_shell.menu_bar.search_box.setFocus()

    # --- project lifecycle delegates ---

    def new_project(self, name: str = "Untitled Project") -> None:
        self.project_controller.new_project(name)

    def open_project_path(self, path: str | Path) -> bool:
        return self.project_controller.open_project_path(path)

    def save_project(self) -> Path | None:
        return self.project_controller.save_project()

    def save_project_as(self, path: str | Path | None) -> Path | None:
        return self.project_controller.save_project_as(path)

    def open_sample_project(self, data_root: Path | None = None) -> bool:
        return self.project_controller.open_sample_project(data_root)

    def _confirm_replace_project(self) -> bool:
        return self.project_controller._confirm_replace_project()

    def _choose_open_project(self) -> Path | None:
        return self.project_controller._choose_open_project()

    def _choose_save_project(self) -> Path | None:
        return self.project_controller._choose_save_project()

    def _show_project_error(self, title: str, message: str) -> None:
        self.project_controller._show_project_error(title, message)

    def project_properties_text(self) -> str:
        return self.project_controller.project_properties_text()

    def _show_properties(self) -> None:
        self.project_controller._show_properties()

    def _flush_mapping_draft(self) -> bool:
        """Commit dirty map-scene geometry into the project before serialization.

        Returns False when the mapping page is dirty and ``save_draft`` fails
        (e.g. topology blocks save), so callers can abort project write.
        """
        page = self.app_shell.mapping_page_widget()
        if page is None:
            return True
        if hasattr(page, "is_dirty") and page.is_dirty() and hasattr(page, "save_draft"):
            return bool(page.save_draft())
        return True

    def _on_new_project(self) -> None:
        self.project_controller._on_new_project()

    def _on_open_project(self) -> None:
        self.project_controller._on_open_project()

    def _on_open_sample_project(self) -> None:
        self.project_controller._on_open_sample_project()

    def _on_save_project(self) -> None:
        self.project_controller._on_save_project()

    def _on_properties(self) -> None:
        self.project_controller._on_properties()

    def _show_preview_settings(self) -> None:
        self.workflow_controller.show_preview_settings()

    def _apply_preview_settings(self, settings) -> None:
        self.workflow_controller.apply_preview_settings(settings)

    # --- signal wiring ---

    def _wire_menu_bar(self) -> None:
        """Connect the current menu bar's signals to the handler methods.

        Each shell rebuild creates a fresh :class:`MenuBar`, so this must
        be called from both ``__init__`` and ``_refresh_shell``.
        """
        menu_bar = self.app_shell.menu_bar
        menu_bar.new_project_requested.connect(self._on_new_project)
        menu_bar.open_project_requested.connect(self._on_open_project)
        menu_bar.open_sample_project_requested.connect(self._on_open_sample_project)
        # HomePage start guide cards (recreated on each _refresh_shell)
        try:
            home_page = self.app_shell.home_page_widget()
            if home_page is not None:
                if hasattr(home_page, "new_project_requested"):
                    home_page.new_project_requested.connect(self._on_new_project)
                if hasattr(home_page, "open_project_requested"):
                    home_page.open_project_requested.connect(self._on_open_project)
                if hasattr(home_page, "open_sample_requested"):
                    home_page.open_sample_requested.connect(self._on_open_sample_project)
        except Exception:
            pass
        menu_bar.save_project_requested.connect(self._on_save_project)
        menu_bar.properties_requested.connect(self._on_properties)
        menu_bar.preview_settings_requested.connect(self._show_preview_settings)
        menu_bar.reset_layout_requested.connect(self._on_reset_layout)
        menu_bar.toggle_sidebar_requested.connect(self._on_toggle_sidebar)
        menu_bar.density_changed.connect(self._on_density_changed)
        menu_bar.about_requested.connect(self._on_about)
        menu_bar.search_submitted.connect(self._on_global_search)
        self.workflow_controller.wire_home_page()
        self.workflow_controller.wire_data_visualization_jump()
        self.workflow_controller.wire_mapping_page()
        self.workflow_controller.wire_preparation_page()
        self.workflow_controller.wire_sequence_page()
        self.workflow_controller.wire_seismic_page()
        self.workflow_controller.wire_well_log_page()
        self.workflow_controller.wire_geomodel_page()
        self.workflow_controller.wire_review_page()

    # --- view / help / search handlers ---

    def _on_reset_layout(self) -> None:
        """Reset the contextual sidebar to its expanded state."""
        sidebar = getattr(self.app_shell, "sidebar", None)
        if sidebar is not None and hasattr(sidebar, "toggle_collapse"):
            sidebar.toggle_collapse(False)

    def _on_toggle_sidebar(self) -> None:
        sidebar = getattr(self.app_shell, "sidebar", None)
        if sidebar is not None and hasattr(sidebar, "toggle_collapse"):
            sidebar.toggle_collapse()

    def _on_density_changed(self, density: str) -> None:
        """Rebuild the global QSS at the requested density (comfortable|compact).

        AppShell installs its own widget-level QSS at construction; per Qt's
        cascade rule a widget/ancestor stylesheet wins over the QApplication
        stylesheet, so the compact rebuild must be re-applied on the shell too
        or the comfortable padding silently stays for the whole main window.
        """
        # Route through the ThemeManager so density and the ACTIVE THEME
        # compose — a direct tokens.build_qss(density=...) would silently
        # reset a dark/high-contrast session back to light (#1047 review).
        qss = self.app_shell.theme_manager.get_qss(density=density)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)
        self.app_shell.setStyleSheet(qss)
        self.app_shell.menu_bar.set_density_checked(density)

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "关于",
            "智能岩相古地理重建系统\n"
            "Paleogeography Workbench\n\n"
            "数据管理 · 沉积相预测 · 古地理编图 · 三维地质建模",
        )

    def _on_global_search(self, text: str) -> None:
        """Delegate the global search box to the current page's filter, if any.

        Only pages exposing searchable content (today: the data page's
        ``asset_table.set_search_text``) react. Other pages silently ignore
        the query rather than pretending to search.
        """
        page = self.app_shell.page_stack.currentWidget()
        # Data page: drive its asset table filter and keep the page-local
        # toolbar search box in sync so the two inputs never disagree.
        asset_table = getattr(page, "asset_table", None)
        if asset_table is not None and hasattr(asset_table, "set_search_text"):
            asset_table.set_search_text(text)
            toolbar = getattr(page, "data_toolbar", None)
            if toolbar is not None and hasattr(toolbar, "search_box"):
                if toolbar.search_box.text() != text:
                    toolbar.search_box.blockSignals(True)
                    toolbar.search_box.setText(text)
                    toolbar.search_box.blockSignals(False)

    # --- shell rebuild helpers ---

    def _refresh_shell(self, *, defer_nonvisible_bindings: bool = False) -> None:
        """Tear down the current app shell and build a fresh one for ``self.project``."""
        self.app_shell.hide()
        self.app_shell.shutdown_workers()
        self.outer_layout.removeWidget(self.app_shell)
        self.app_shell.setParent(None)
        self.app_shell.deleteLater()
        self.app_shell = AppShell(
            project=self.project,
            parent=self,
            defer_nonvisible_bindings=defer_nonvisible_bindings,
        )
        self._apply_project_to_shell()
        self.outer_layout.addWidget(self.app_shell)
        self._wire_menu_bar()
        self._update_title()
        # Re-bind project file path after shell rebuild (import/export I/O).
        self.app_shell.set_data_project_path(self.project_path)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Close project-owned workers/catalog deterministically on app exit."""
        if not self.project_controller.shutdown_current_session():
            self.project_controller._restore_current_shell_after_failed_stop()
            if QApplication.platformName() == "offscreen":
                # Headless runs (offscreen CI): a modal here would block the
                # process forever until the test timeout kills it — log
                # instead and leave the window open, same semantics.
                logging.getLogger(__name__).warning(
                    "closeEvent: background tasks still running; window left open (offscreen: no modal)"
                )
            else:
                QMessageBox.warning(
                    self,
                    "无法关闭",
                    "后台任务尚未停止。工程保持打开，等待任务结束后请再次关闭。",
                )
            event.ignore()
            return
        super().closeEvent(event)

    def _apply_project_to_shell(self) -> None:
        """Push ``self.project`` into the current shell's pages (set in __init__/_refresh)."""
        state = dashboard_state(self.project)
        self.app_shell.set_project_name(
            state.get("project_name", self.project.meta.name)
        )
        self._update_status_context()
        steps = home_workflow_steps(self.project)
        self.app_shell.update_home_page(state, steps, project=self.project)
        self.app_shell.update_data_page(
            state,
            self.project.resources,
            self.project.export_artifacts,
            project_path=self.project_path,
        )
        self.app_shell.set_data_project_path(self.project_path)
        self.app_shell.update_well_log_prediction_page(
            self.project.prediction_tasks, project=self.project
        )
        self.app_shell.update_seismic_prediction_page(
            self.project.prediction_tasks, project=self.project
        )
        self.app_shell.update_sequence_framework_page(self.project.stratigraphy)
        self.app_shell.update_stratigraphy_correlation_page(self.project)
        self.app_shell.update_visualization_page(
            self.project.resources,
            self.project.prediction_tasks,
            self.project.paleomap_documents,
            project=self.project,
        )
        self.app_shell.update_preparation_page(self.project.factor_map_tasks)
        self.app_shell.update_mapping_page(
            self.project.paleomap_documents,
            factor_tasks=self.project.factor_map_tasks,
            project_crs=self.project.coordinate.project_crs,
        )
        self.app_shell.update_review_export_page(
            active_quality_reports(self.project),
            self.project.paleomap_documents,
            self.project.export_artifacts,
        )

    def _update_status_context(self) -> None:
        """Push always-available context (CRS + active target horizon) to the status bar.

        Canvas coords/scale are page-specific and stay with each canvas; this
        wires the two project-level fields that should follow the open project.
        """
        project = self.project
        crs = project.coordinate.display_crs
        active_run = project.compilation_runs[-1] if project.compilation_runs else None
        horizon = active_run.target_horizon if active_run else ""
        self.app_shell.status_bar.update_context(crs=crs, horizon=horizon)

    def _update_title(self) -> None:
        self.setWindowTitle(f"{self.project.meta.name} - Paleogeography Workbench")
