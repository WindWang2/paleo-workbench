"""OwnedWorkerJob payload executing the I/O half of a project save (#1040).

``ProjectSaveTask`` runs ``ProjectManager.execute_save`` on a worker thread so
Ctrl+S never blocks the GUI event loop on ``json.dumps`` + write + ``fsync`` +
rename. The GUI-side phases (``prepare_save`` before, ``commit_save`` and
catalog registration after) stay on the main thread because they touch the
live ``ProjectDocument``.

The state machine itself lives in ``ProjectManager.prepare_save /
execute_save / commit_save`` orchestrated by
``ProjectController.save_project_async``; this task is only the worker-side
transport. Outcomes (``outcome_stats`` / ``outcome_error``) are recorded on
the object so a session drain that beats the queued signal can still commit a
successfully completed write instead of dropping it (review C1).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from paleo_workbench.project.manager import PreparedSave, ProjectManager, ProjectSaveStats


class ProjectSaveTask(QObject):
    """Execute one prepared project save off the GUI thread."""

    progress = Signal(str)
    saved = Signal(object)  # ProjectSaveStats
    failed = Signal(str)
    terminal = Signal()

    def __init__(
        self,
        manager: ProjectManager,
        prepared: PreparedSave,
        generation: int = -1,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._prepared = prepared
        self.generation = int(generation)
        # Outcome bookkeeping for drain-side completion (both written by the
        # worker thread before the matching signal emit, read on GUI only).
        self.outcome_stats: ProjectSaveStats | None = None
        self.outcome_error: str | None = None
        self.committed = False

    @property
    def manager(self) -> ProjectManager:
        return self._manager

    @property
    def prepared(self) -> PreparedSave:
        return self._prepared

    def run(self) -> None:
        try:
            self.progress.emit("writing")
            stats = self._manager.execute_save(self._prepared)
        except Exception as exc:  # noqa: BLE001 — routed to the GUI error slot
            self.outcome_error = f"{type(exc).__name__}: {exc}"
            self.failed.emit(self.outcome_error)
            self.terminal.emit()
            return
        self.outcome_stats = stats
        self.progress.emit("committing")
        self.saved.emit(stats)
        self.terminal.emit()
