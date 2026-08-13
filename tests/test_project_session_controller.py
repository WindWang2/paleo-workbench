from __future__ import annotations

from pathlib import Path

from paleo_workbench.project.manager import ProjectManager
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.ui.project_controller import ProjectController


class _Shell:
    def __init__(self, *, joined: bool = True) -> None:
        self.joined = joined
        self.calls = 0

    def shutdown_workers(self, _wait_ms=3_000) -> bool:
        self.calls += 1
        return self.joined


class _Window:
    def __init__(self, project: ProjectDocument, path: Path | None = None) -> None:
        self.project = project
        self.project_path = path
        self.app_shell = _Shell()
        self.errors: list[tuple[str, str]] = []
        self.refresh_calls: list[bool] = []

    def _refresh_shell(self, *, defer_nonvisible_bindings: bool = False) -> None:
        self.refresh_calls.append(defer_nonvisible_bindings)
        self.app_shell = _Shell()

    def _show_project_error(self, title: str, message: str) -> None:
        self.errors.append((title, message))

    def _flush_mapping_draft(self) -> bool:
        return True

    def _flush_joint_analysis_state(self) -> None:
        pass


def test_open_aborts_without_closing_catalog_when_worker_does_not_join(tmp_path):
    source = tmp_path / "source.paleo.json"
    target = tmp_path / "target.paleo.json"
    ProjectManager(target).save(ProjectDocument.new("Target"))
    window = _Window(ProjectDocument.new("Source"), source)
    window.app_shell = _Shell(joined=False)
    controller = ProjectController(window)

    assert controller.open_project_path(target) is False
    assert window.project.meta.name == "Source"
    assert window.project_path == source
    assert window.refresh_calls == [True]
    assert "后台任务" in (controller._last_open_error or "")


def test_queued_catalog_maintenance_is_ignored_after_session_replacement(qtbot, tmp_path):
    target = tmp_path / "target.paleo.json"
    loaded = ProjectDocument.new("Target")
    window = _Window(loaded, target)
    controller = ProjectController(window)
    controller._session_generation = 3
    controller._schedule_catalog_maintenance(target, loaded)
    controller._session_generation += 1

    # A queued callback may run later, but generation mismatch is a no-op.
    qtbot.wait(10)
    assert window.project is loaded
