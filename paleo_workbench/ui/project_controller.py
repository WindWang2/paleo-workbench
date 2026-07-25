from __future__ import annotations

import json
from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QMessageBox
from pydantic import ValidationError

from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.project.paths import ProjectPathError
from paleo_workbench.pipeline.assets import ensure_demo_prediction
from paleo_workbench.pipeline.bootstrap import (
    bootstrap_sample_project,
    resolve_sample_data_root,
)

_PROJECT_SUFFIX = ".paleo.json"
_PROJECT_FILTER = "Project (*.paleo.json)"


class ProjectController:
    """Manages project lifecycle operations and file I/O for PaleoWorkbenchWindow."""

    def __init__(self, window) -> None:
        self.window = window
        self._last_open_error: str | None = None
        self._confirm_title: str | None = None
        self._confirm_message: str | None = None

    def new_project(self, name: str = "Untitled Project") -> None:
        """Replace the in-memory project (no confirm — callers that need one ask first)."""
        self.window.project = ProjectDocument.new(name)
        self.window.project_path = None
        self.window._refresh_shell()

    def open_project_path(self, path: str | Path) -> bool:
        """Load project from path (no confirm — UI handlers ask before calling)."""
        self._last_open_error = None
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
        except ProjectPathError as e:
            self._last_open_error = (
                f"工程内相对路径非法（疑似逃出工程目录）：\n{target}\n{e}"
            )
            return False
        except OSError as e:
            self._last_open_error = f"无法读取工程文件：\n{target}\n{e}"
            return False
        self.window.project = loaded
        self.window.project.meta.project_root = str(target.resolve().parent)
        self.window.project_path = target
        self.window._refresh_shell()
        return True

    def save_project(self) -> Path | None:
        if not self.window._flush_mapping_draft():
            self.window._show_project_error(
                "保存工程失败",
                "编图草稿未通过拓扑检查，工程文件未写入。请修复拓扑问题后重试。",
            )
            return None
        self._flush_joint_analysis_state()
        if self.window.project_path is not None:
            try:
                self.window.project.meta.project_root = str(
                    self.window.project_path.resolve().parent
                )
                ProjectManager(self.window.project_path).save(self.window.project)
            except OSError as e:
                self.window._show_project_error("保存工程失败", str(e))
                return None
            return self.window.project_path
        # No path yet: ask the user via the save dialog, then save to that path.
        chosen = self.window._choose_save_project()
        return self.save_project_as(chosen)

    def save_project_as(self, path: str | Path | None) -> Path | None:
        if path is None:
            return None
        if not self.window._flush_mapping_draft():
            self.window._show_project_error(
                "保存工程失败",
                "编图草稿未通过拓扑检查，工程文件未写入。请修复拓扑问题后重试。",
            )
            return None
        self._flush_joint_analysis_state()
        target = self._normalize_project_path(Path(path))
        try:
            self.window.project.meta.project_root = str(target.resolve().parent)
            ProjectManager(target).save(self.window.project)
        except OSError as e:
            self.window._show_project_error("保存工程失败", str(e))
            return None
        self.window.project_path = target
        return target

    def _flush_joint_analysis_state(self) -> None:
        """Persist joint presentation from 三维建模 page before project write.

        Only flush when the hybrid joint UI has actually been loaded/shown
        (``_joint_loaded_once``). Otherwise a pristine page defaults to Time
        and would clobber a previously saved Depth/fence/tree state when the
        user saves from another page without revisiting 三维建模.
        """
        shell = getattr(self.window, "app_shell", None)
        page = getattr(shell, "geomodel_page", None) if shell is not None else None
        if page is not None and hasattr(page, "save_joint_analysis_to_project"):
            if not getattr(page, "_joint_loaded_once", False):
                return
            try:
                # Keep page project pointer aligned with window project
                if hasattr(page, "set_project"):
                    page.set_project(self.window.project)
                page.save_joint_analysis_to_project()
            except Exception:
                pass

    def open_sample_project(self, data_root: Path | None = None) -> bool:
        """Bootstrap sample data into the current window (no auto-save)."""
        if not self.window._confirm_replace_project():
            return False
        try:
            root = resolve_sample_data_root(data_root)
            result = bootstrap_sample_project(root)
        except (FileNotFoundError, ValueError, OSError) as e:
            self.window._show_project_error("打开样例工程失败", str(e))
            return False
        self.window.project = result.document
        ensure_demo_prediction(self.window.project, seed=0)
        self.window.project_path = None
        self.window._refresh_shell()
        return True

    def _confirm_replace_project(self) -> bool:
        """Ask the user before discarding the current in-memory project.

        Zero-arg signature is intentional so tests can monkeypatch with
        ``lambda: True`` / ``lambda: False``.
        """
        title = (
            getattr(self.window, "_confirm_title", None)
            or self._confirm_title
            or "替换工程"
        )
        message = (
            getattr(self.window, "_confirm_message", None)
            or self._confirm_message
            or "将替换当前工程（未保存更改会丢失）。是否继续？"
        )
        reply = QMessageBox.question(
            self.window,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _on_new_project(self) -> None:
        self.window._confirm_title = "新建工程"
        self.window._confirm_message = (
            "将创建新工程并替换当前内容（未保存更改会丢失）。是否继续？"
        )
        if not self.window._confirm_replace_project():
            return
        self.new_project()

    def _on_open_project(self) -> None:
        path = self.window._choose_open_project()
        if path is None:
            return
        self.window._confirm_title = "打开工程"
        self.window._confirm_message = (
            "将打开所选工程并替换当前内容（未保存更改会丢失）。是否继续？"
        )
        if not self.window._confirm_replace_project():
            return
        if not self.open_project_path(path):
            detail = self._last_open_error or f"无法打开工程文件：\n{path}"
            self.window._show_project_error("打开工程失败", detail)

    def _on_open_sample_project(self) -> None:
        self.window._confirm_title = "打开样例工程"
        self.window._confirm_message = (
            "将用样例数据替换当前工程（未保存更改会丢失）。是否继续？"
        )
        self.open_sample_project()

    def _on_save_project(self) -> None:
        self.save_project()

    def _on_properties(self) -> None:
        self.window._show_properties()

    def _choose_open_project(self) -> Path | None:
        start_dir = (
            str(self.window.project_path.parent)
            if self.window.project_path
            else str(Path.home())
        )
        path, _ = QFileDialog.getOpenFileName(
            self.window, "打开工程", start_dir, _PROJECT_FILTER
        )
        return Path(path) if path else None

    def _choose_save_project(self) -> Path | None:
        suggested = f"{self.window.project.meta.name}{_PROJECT_SUFFIX}"
        start_dir = (
            str(self.window.project_path.parent)
            if self.window.project_path
            else str(Path.home())
        )
        path, _ = QFileDialog.getSaveFileName(
            self.window, "保存工程", str(Path(start_dir) / suggested), _PROJECT_FILTER
        )
        return Path(path) if path else None

    def _show_project_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self.window, title, message)

    def project_properties_text(self) -> str:
        """Build the read-only summary shown by the properties dialog."""
        project = self.window.project
        path_str = (
            str(self.window.project_path)
            if self.window.project_path is not None
            else "未保存"
        )
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
        QMessageBox.information(
            self.window, "工程属性", self.project_properties_text()
        )

    @staticmethod
    def _normalize_project_path(path: Path) -> Path:
        """Ensure the filename ends with ``.paleo.json`` without double-appending.

        - "p"            -> "p.paleo.json"
        - "p.json"       -> "p.paleo.json"
        - "p.paleo.json" -> "p.paleo.json" (unchanged)
        """
        if path.name.endswith(_PROJECT_SUFFIX):
            return path
        stem = (
            path.name[: -len(".json")] if path.name.endswith(".json") else path.name
        )
        return path.with_name(stem + _PROJECT_SUFFIX)
