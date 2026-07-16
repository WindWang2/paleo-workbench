from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QFileDialog, QMessageBox, QVBoxLayout, QWidget

from paleo_workbench.pipeline.assets import ensure_demo_prediction
from paleo_workbench.pipeline.bootstrap import (
    bootstrap_sample_project,
    resolve_sample_data_root,
)
from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui import AppShell
from paleo_workbench.workflow.service import dashboard_state

_PROJECT_SUFFIX = ".paleo.json"
_PROJECT_FILTER = "Project (*.paleo.json)"


class PaleoWorkbenchWindow(QWidget):
    def __init__(self, project: ProjectDocument | None = None):
        super().__init__()
        self.project = project or ProjectDocument.new("Untitled Project")
        self.project_path: Path | None = None
        self._last_open_error: str | None = None
        self.resize(1440, 900)

        self.outer_layout = QVBoxLayout(self)
        self.outer_layout.setContentsMargins(0, 0, 0, 0)

        self.app_shell = AppShell(project=self.project)
        self._apply_project_to_shell()
        self.outer_layout.addWidget(self.app_shell)
        self._wire_menu_bar()
        self._setup_shortcuts()
        self._update_title()

    def _setup_shortcuts(self) -> None:
        """Window-scoped project-op shortcuts.

        Parented to ``self`` (the window) so they survive shell rebuilds; the
        callbacks read the current ``self.app_shell`` at call-time.
        """
        QShortcut(QKeySequence("Ctrl+S"), self, self.save_project)
        QShortcut(QKeySequence("Ctrl+N"), self, self.new_project)
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

    # --- project lifecycle (path-based, no dialogs) ---

    def new_project(self, name: str = "Untitled Project") -> None:
        """Replace the in-memory project (no confirm — callers that need one ask first)."""
        self.project = ProjectDocument.new(name)
        self.project_path = None
        self._refresh_shell()

    def open_project_path(self, path: str | Path) -> bool:
        """Load project from path (no confirm — UI handlers ask before calling)."""
        self._last_open_error: str | None = None
        target = Path(path)
        try:
            loaded = ProjectManager(target).load()
        except FileNotFoundError:
            self._last_open_error = f"文件不存在：\n{target}"
            return False
        except json.JSONDecodeError as e:
            self._last_open_error = f"工程文件 JSON 损坏：\n{target}\n{e}"
            return False
        except ValidationError as e:
            self._last_open_error = f"工程文件格式无效：\n{target}\n{e}"
            return False
        except OSError as e:
            self._last_open_error = f"无法读取工程文件：\n{target}\n{e}"
            return False
        self.project = loaded
        self.project.meta.project_root = str(target.resolve().parent)
        self.project_path = target
        self._refresh_shell()
        return True

    def save_project(self) -> Path | None:
        self._flush_mapping_draft()
        if self.project_path is not None:
            try:
                self.project.meta.project_root = str(
                    self.project_path.resolve().parent
                )
                ProjectManager(self.project_path).save(self.project)
            except OSError as e:
                self._show_project_error("保存工程失败", str(e))
                return None
            return self.project_path
        # No path yet: ask the user via the save dialog, then save to that path.
        chosen = self._choose_save_project()
        return self.save_project_as(chosen)

    def save_project_as(self, path: str | Path | None) -> Path | None:
        if path is None:
            return None
        self._flush_mapping_draft()
        target = self._normalize_project_path(Path(path))
        try:
            self.project.meta.project_root = str(target.resolve().parent)
            ProjectManager(target).save(self.project)
        except OSError as e:
            self._show_project_error("保存工程失败", str(e))
            return None
        self.project_path = target
        return target

    def _flush_mapping_draft(self) -> None:
        """Commit dirty map-scene geometry into the project before serialization."""
        page = self.app_shell.mapping_page_widget()
        if page is None:
            return
        if hasattr(page, "is_dirty") and page.is_dirty() and hasattr(page, "save_draft"):
            page.save_draft()

    # --- toolbar handlers (signals -> dialogs -> core methods) ---

    def open_sample_project(self, data_root: Path | None = None) -> bool:
        """Bootstrap sample data into the current window (no auto-save)."""
        if not self._confirm_replace_project():
            return False
        try:
            root = resolve_sample_data_root(data_root)
            result = bootstrap_sample_project(root)
        except FileNotFoundError as e:
            self._show_project_error("打开样例工程失败", str(e))
            return False
        except ValueError as e:
            self._show_project_error("打开样例工程失败", str(e))
            return False
        except OSError as e:
            self._show_project_error("打开样例工程失败", str(e))
            return False
        self.project = result.document
        ensure_demo_prediction(self.project, seed=0)
        self.project_path = None
        self._refresh_shell()
        return True

    def _confirm_replace_project(self) -> bool:
        """Ask the user before discarding the current in-memory project.

        Zero-arg signature is intentional so tests can monkeypatch with
        ``lambda: True`` / ``lambda: False``.
        """
        title = getattr(self, "_confirm_title", "替换工程")
        message = getattr(
            self,
            "_confirm_message",
            "将替换当前工程（未保存更改会丢失）。是否继续？",
        )
        reply = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _on_new_project(self) -> None:
        self._confirm_title = "新建工程"
        self._confirm_message = (
            "将创建新工程并替换当前内容（未保存更改会丢失）。是否继续？"
        )
        if not self._confirm_replace_project():
            return
        self.new_project()

    def _on_open_project(self) -> None:
        path = self._choose_open_project()
        if path is None:
            return
        self._confirm_title = "打开工程"
        self._confirm_message = (
            "将打开所选工程并替换当前内容（未保存更改会丢失）。是否继续？"
        )
        if not self._confirm_replace_project():
            return
        if not self.open_project_path(path):
            detail = getattr(self, "_last_open_error", None) or f"无法打开工程文件：\n{path}"
            self._show_project_error("打开工程失败", detail)

    def _on_open_sample_project(self) -> None:
        self._confirm_title = "打开样例工程"
        self._confirm_message = (
            "将用样例数据替换当前工程（未保存更改会丢失）。是否继续？"
        )
        self.open_sample_project()

    def _on_save_project(self) -> None:
        self.save_project()

    def _on_properties(self) -> None:
        self._show_properties()

    # --- file dialogs / message boxes ---

    def _choose_open_project(self) -> Path | None:
        start_dir = str(self.project_path.parent) if self.project_path else str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self, "打开工程", start_dir, _PROJECT_FILTER
        )
        return Path(path) if path else None

    def _choose_save_project(self) -> Path | None:
        suggested = f"{self.project.meta.name}{_PROJECT_SUFFIX}"
        start_dir = (
            str(self.project_path.parent) if self.project_path else str(Path.home())
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "保存工程", str(Path(start_dir) / suggested), _PROJECT_FILTER
        )
        return Path(path) if path else None

    def _show_project_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def project_properties_text(self) -> str:
        """Build the read-only summary shown by the properties dialog."""
        project = self.project
        path_str = str(self.project_path) if self.project_path is not None else "未保存"
        return "\n".join(
            [
                f"工程名称: {project.meta.name}",
                f"区域: {project.meta.region or '—'}",
                f"工程文件: {path_str}",
                f"资源数量: {len(project.resources)}",
                f"导出图件: {len(project.export_artifacts)}",
                f"显示坐标系: {project.coordinate.display_crs}",
                f"版本: {project.meta.version}",
            ]
        )

    def _show_properties(self) -> None:
        QMessageBox.information(self, "工程属性", self.project_properties_text())

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
        menu_bar.save_project_requested.connect(self._on_save_project)
        menu_bar.properties_requested.connect(self._on_properties)
        self._wire_data_visualization_jump()
        self._wire_mapping_page()

    def _wire_data_visualization_jump(self) -> None:
        page = self.app_shell.data_page_widget()
        if hasattr(page, "open_in_visualization"):
            page.open_in_visualization.connect(self._on_open_in_visualization)

    def _wire_mapping_page(self) -> None:
        page = self.app_shell.mapping_page_widget()
        if hasattr(page, "generate_demo_draft_requested"):
            page.generate_demo_draft_requested.connect(self._on_generate_demo_map_draft)

    def _on_generate_demo_map_draft(self) -> None:
        from paleo_workbench.pipeline.compile_map import compile_map_draft

        compile_map_draft(self.project, seed=0)
        self._refresh_shell()

    def _on_open_in_visualization(self, ref) -> None:
        from paleo_workbench.ui.app_shell import PAGE_INDEX_VISUALIZATION

        self.app_shell.icon_rail.set_active(PAGE_INDEX_VISUALIZATION)
        self.app_shell._switch_page(PAGE_INDEX_VISUALIZATION)
        viz = self.app_shell.page_stack.widget(PAGE_INDEX_VISUALIZATION)
        if hasattr(viz, "open_ref"):
            viz.open_ref(ref)

    # --- shell rebuild helpers ---

    def _refresh_shell(self) -> None:
        """Tear down the current app shell and build a fresh one for ``self.project``."""
        self.outer_layout.removeWidget(self.app_shell)
        self.app_shell.setParent(None)
        self.app_shell.deleteLater()
        self.app_shell = AppShell(project=self.project)
        self._apply_project_to_shell()
        self.outer_layout.addWidget(self.app_shell)
        self._wire_menu_bar()
        self._update_title()

    def _apply_project_to_shell(self) -> None:
        """Push ``self.project`` into the current shell's pages (set in __init__/_refresh)."""
        state = dashboard_state(self.project)
        self.app_shell.set_project_name(state.get("project_name", self.project.meta.name))
        active_run = self.project.compilation_runs[-1] if self.project.compilation_runs else None
        steps = active_run.workflow_steps if active_run else []
        self.app_shell.update_home_page(state, steps)
        self.app_shell.update_data_page(
            state,
            self.project.resources,
            self.project.export_artifacts,
        )
        self.app_shell.update_well_log_prediction_page(
            self.project.prediction_tasks, project=self.project
        )
        self.app_shell.update_seismic_prediction_page(
            self.project.prediction_tasks, project=self.project
        )
        self.app_shell.update_sequence_framework_page(self.project.stratigraphy)
        self.app_shell.update_visualization_page(
            self.project.resources,
            self.project.prediction_tasks,
            self.project.paleomap_documents,
        )
        self.app_shell.update_preparation_page(self.project.factor_map_tasks)
        self.app_shell.update_mapping_page(
            self.project.paleomap_documents,
            factor_tasks=self.project.factor_map_tasks,
            project_crs=self.project.coordinate.project_crs,
        )
        self.app_shell.update_review_export_page(
            self.project.quality_reports,
            self.project.paleomap_documents,
            self.project.export_artifacts,
        )

    def _update_title(self) -> None:
        self.setWindowTitle(
            f"{self.project.meta.name} - Paleogeography Workbench"
        )

    # --- internal utils ---

    @staticmethod
    def _normalize_project_path(path: Path) -> Path:
        """Ensure the filename ends with ``.paleo.json`` without double-appending.

        - "p"            -> "p.paleo.json"
        - "p.json"       -> "p.paleo.json"
        - "p.paleo.json" -> "p.paleo.json" (unchanged)
        """
        if path.name.endswith(_PROJECT_SUFFIX):
            return path
        stem = path.name[:-len(".json")] if path.name.endswith(".json") else path.name
        return path.with_name(stem + _PROJECT_SUFFIX)
