"""OwnedWorkerJob payload executing the I/O half of a project save (#1040).

``ProjectSaveTask`` runs ``ProjectManager.execute_save`` on a worker thread so
Ctrl+S never blocks the GUI event loop on ``json.dumps`` + write + ``fsync`` +
rename. The GUI-side phases (``prepare_save`` before, ``commit_save`` and
catalog registration after) stay on the main thread because they touch the
live ``ProjectDocument`` and Qt state.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from paleo_workbench.project.manager import PreparedSave, ProjectManager, ProjectSaveStats


class ProjectSaveTask(QObject):
    """Execute one prepared project save off the GUI thread.

    State machine (per #1040): ``Idle → Preparing (GUI) → Writing (worker)
    → Committing (GUI) → Success`` with ``Failure`` routing to the error slot;
    ``terminal`` always fires last so the owning ``OwnedWorkerJob`` can retire
    the thread either way.
    """

    progress = Signal(str)
    saved = Signal(object)  # ProjectSaveStats
    failed = Signal(str)
    terminal = Signal()

    def __init__(
        self,
        manager: ProjectManager,
        prepared: PreparedSave,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._prepared = prepared

    def run(self) -> None:
        try:
            self.progress.emit("writing")
            stats = self._manager.execute_save(self._prepared)
        except Exception as exc:  # noqa: BLE001 — routed to the GUI error slot
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            self.terminal.emit()
            return
        self.progress.emit("committing")
        self.saved.emit(stats)
        self.terminal.emit()
