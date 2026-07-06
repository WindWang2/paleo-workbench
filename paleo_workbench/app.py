from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtWidgets import QFileDialog, QMessageBox, QVBoxLayout, QWidget

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
        self.resize(1440, 900)

        self.outer_layout = QVBoxLayout(self)
        self.outer_layout.setContentsMargins(0, 0, 0, 0)

        self.app_shell = AppShell(project=self.project)
        self._apply_project_to_shell()
        self.outer_layout.addWidget(self.app_shell)
        self._wire_toolbar()
        self._update_title()

    # --- project lifecycle (path-based, no dialogs) ---

    def new_project(self, name: str = "Untitled Project") -> None:
        self.project = ProjectDocument.new(name)
        self.project_path = None
        self._refresh_shell()

    def open_project_path(self, path: str | Path) -> bool:
        try:
            loaded = ProjectManager(path).load()
        except (json.JSONDecodeError, ValidationError, OSError, FileNotFoundError):
            return False
        self.project = loaded
        self.project_path = Path(path)
        self._refresh_shell()
        return True

    def save_project(self) -> Path | None:
        if self.project_path is not None:
            ProjectManager(self.project_path).save(self.project)
            return self.project_path
        # No path yet: ask the user via the save dialog, then save to that path.
        chosen = self._choose_save_project()
        return self.save_project_as(chosen)

    def save_project_as(self, path: str | Path | None) -> Path | None:
        if path is None:
            return None
        target = self._normalize_project_path(Path(path))
        ProjectManager(target).save(self.project)
        self.project_path = target
        return target

    # --- toolbar handlers (signals -> dialogs -> core methods) ---

    def _on_new_project(self) -> None:
        self.new_project()

    def _on_open_project(self) -> None:
        path = self._choose_open_project()
        if path is None:
            return
        if not self.open_project_path(path):
            self._show_project_error(
                "打开工程失败",
                f"无法打开工程文件：\n{path}",
            )

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

    def _show_properties(self) -> None:
        # Placeholder; Task 4 fills in the real properties text.
        QMessageBox.information(self, "工程属性", "")

    # --- signal wiring ---

    def _wire_toolbar(self) -> None:
        """Connect the current toolbar's signals to the handler methods.

        Each shell rebuild creates a fresh :class:`HeaderToolbar`, so this must
        be called from both ``__init__`` and ``_refresh_shell``.
        """
        toolbar = self.app_shell.header_toolbar
        toolbar.new_project_requested.connect(self._on_new_project)
        toolbar.open_project_requested.connect(self._on_open_project)
        toolbar.save_project_requested.connect(self._on_save_project)
        toolbar.properties_requested.connect(self._on_properties)

    # --- shell rebuild helpers ---

    def _refresh_shell(self) -> None:
        """Tear down the current app shell and build a fresh one for ``self.project``."""
        self.outer_layout.removeWidget(self.app_shell)
        self.app_shell.setParent(None)
        self.app_shell.deleteLater()
        self.app_shell = AppShell(project=self.project)
        self._apply_project_to_shell()
        self.outer_layout.addWidget(self.app_shell)
        self._wire_toolbar()
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
        self.app_shell.update_well_log_prediction_page(self.project.prediction_tasks)
        self.app_shell.update_seismic_prediction_page(self.project.prediction_tasks)
        self.app_shell.update_sequence_framework_page(self.project.stratigraphy)
        self.app_shell.update_visualization_page(
            self.project.resources,
            self.project.prediction_tasks,
            self.project.paleomap_documents,
        )
        self.app_shell.update_preparation_page(self.project.factor_map_tasks)
        self.app_shell.update_mapping_page(self.project.paleomap_documents)
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
