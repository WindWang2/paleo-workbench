from __future__ import annotations

import importlib
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication


class _ProbeWorker(QObject):
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.ran_off_gui = False

    @Slot()
    def run(self) -> None:
        app = QApplication.instance()
        assert app is not None
        self.ran_off_gui = QThread.currentThread() is not app.thread()
        self.finished.emit()


class _BlockingWorker(QObject):
    completed = Signal(str)
    finished = Signal()

    def __init__(self, started: Event, release: Event) -> None:
        super().__init__()
        self._started = started
        self._release = release

    @Slot()
    def run(self) -> None:
        self._started.set()
        self._release.wait(timeout=5.0)
        self.completed.emit("stale")
        self.finished.emit()


def test_owned_worker_job_runs_off_gui_and_releases_normal_completion(qtbot):
    module = importlib.import_module("paleo_workbench.ui.owned_worker_job")
    job = module.OwnedWorkerJob()
    worker = _ProbeWorker()
    released: list[bool] = []
    job.released.connect(lambda: released.append(True))

    job.start(worker, terminal_signals=(worker.finished,))

    qtbot.waitUntil(lambda: released == [True], timeout=3_000)
    assert worker.ran_off_gui is True
    assert job.is_running is False
    assert job.thread is None
    assert job.worker is None


def test_start_rejects_worker_with_parent(qtbot):
    """A parented worker makes moveToThread a silent no-op, so run() would
    execute on the GUI thread; OwnedWorkerJob must refuse it loudly (C17).
    """
    import pytest
    from PySide6.QtWidgets import QWidget

    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

    parent = QWidget()
    worker = _ProbeWorker()
    worker.setParent(parent)
    job = OwnedWorkerJob()
    with pytest.raises(RuntimeError, match="without a parent"):
        job.start(worker, terminal_signals=(worker.finished,))
    assert job.is_running is False


def test_shutdown_cancels_disconnects_results_and_detaches_blocked_worker(qtbot):
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
    from paleo_workbench.ui.thread_keeper import detached_job_keeper

    started = Event()
    release = Event()
    cancelled = Event()
    results: list[str] = []
    target = object()
    worker = _BlockingWorker(started, release)
    job = OwnedWorkerJob()
    job.start(
        worker,
        terminal_signals=(worker.finished,),
        result_connections=((worker.completed, results.append),),
        cancel=cancelled.set,
        target=target,
    )
    assert started.wait(timeout=2.0)
    thread = job.thread
    assert thread is not None
    assert job.target is target

    joined = job.shutdown(wait_ms=1)

    keeper = detached_job_keeper()
    assert joined is False
    assert cancelled.is_set()
    assert keeper.owns(thread)
    assert job.thread is None
    assert job.worker is None
    assert job.target is None
    release.set()
    qtbot.waitUntil(lambda: not keeper.owns(thread), timeout=3_000)
    assert results == []


def test_job_remains_running_until_gui_release_is_processed(qtbot):
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

    worker = _ProbeWorker()
    job = OwnedWorkerJob()
    job.start(worker, terminal_signals=(worker.finished,))
    thread = job.thread
    assert thread is not None
    assert thread.wait(3_000)

    assert job.thread is thread
    assert job.is_running is True
    qtbot.waitUntil(lambda: job.thread is None, timeout=3_000)


def test_detached_old_worker_cannot_release_a_new_job(qtbot):
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
    from paleo_workbench.ui.thread_keeper import detached_job_keeper

    first_started = Event()
    first_release = Event()
    first = _BlockingWorker(first_started, first_release)
    job = OwnedWorkerJob()
    job.start(first, terminal_signals=(first.finished,))
    assert first_started.wait(timeout=2.0)
    first_thread = job.thread
    assert first_thread is not None
    assert job.shutdown(wait_ms=1) is False

    second_started = Event()
    second_release = Event()
    second = _BlockingWorker(second_started, second_release)
    job.start(second, terminal_signals=(second.finished,))
    assert second_started.wait(timeout=2.0)
    second_thread = job.thread
    assert second_thread is not None

    first_release.set()
    keeper = detached_job_keeper()
    qtbot.waitUntil(lambda: not keeper.owns(first_thread), timeout=3_000)
    assert job.thread is second_thread
    assert job.worker is second

    second_release.set()
    qtbot.waitUntil(lambda: job.thread is None, timeout=3_000)


def test_owned_worker_job_adopts_running_thread_on_destroy(qtbot):
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
    from paleo_workbench.ui.thread_keeper import detached_job_keeper

    started = Event()
    release = Event()
    worker = _BlockingWorker(started, release)
    
    # We put job inside a parent widget to trigger QObject hierarchy deletion.
    from PySide6.QtWidgets import QWidget
    parent = QWidget()
    job = OwnedWorkerJob(parent)
    job.start(worker, terminal_signals=(worker.finished,))
    
    assert started.wait(timeout=2.0)
    thread = job.thread
    assert thread is not None
    
    # Destroy the parent widget, which deletes job.
    from PySide6.QtCore import QCoreApplication, QEvent
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    
    # Verify the thread was adopted by detached_job_keeper.
    keeper = detached_job_keeper()
    assert keeper.owns(thread) is True
    
    # Let the thread finish.
    release.set()
    qtbot.waitUntil(lambda: not keeper.owns(thread), timeout=3_000)


def test_factor_map_worker_lifecycle_with_owned_worker_job(qtbot, monkeypatch):
    """Verify _FactorMapWorker operates safely with OwnedWorkerJob off the GUI thread."""
    from unittest.mock import Mock
    from paleo_workbench.mapping.layers import MapDocument
    from paleo_workbench.project.models import ProjectDocument, ProjectMeta
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
    from paleo_workbench.ui.pages.create_factor_map_dialog import _FactorMapWorker

    fake_map_doc = MapDocument(id="doc_1", title="Test Factor Map")
    fake_task = object()
    mock_service = Mock()
    mock_service.create_factor_map.return_value = (fake_map_doc, fake_task)
    project = ProjectDocument(meta=ProjectMeta(name="test_proj"))

    params = {
        "factor_name": "孔隙度",
        "target_horizon": "T1",
        "method": "kriging",
        "grid_n": 50,
    }
    worker = _FactorMapWorker(mock_service, project, params)
    assert worker.parent() is None

    job = OwnedWorkerJob()
    results = []
    job.start(
        worker,
        terminal_signals=(worker.finished, worker.failed),
        result_connections=((worker.finished, lambda doc, task: results.append((doc, task))),),
    )

    qtbot.waitUntil(lambda: len(results) == 1, timeout=3_000)
    assert results[0][0] is fake_map_doc
    assert results[0][1] is fake_task
    qtbot.waitUntil(lambda: not job.is_running, timeout=3_000)


def test_factor_map_worker_handles_failure(qtbot, monkeypatch):
    """Verify _FactorMapWorker failure emits failed signal and shuts down cleanly."""
    from unittest.mock import Mock
    from paleo_workbench.project.models import ProjectDocument, ProjectMeta
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob
    from paleo_workbench.ui.pages.create_factor_map_dialog import _FactorMapWorker

    mock_service = Mock()
    mock_service.create_factor_map.side_effect = ValueError("Insufficient well data points")
    project = ProjectDocument(meta=ProjectMeta(name="test_proj"))

    params = {"factor_name": "孔隙度"}
    worker = _FactorMapWorker(mock_service, project, params)

    job = OwnedWorkerJob()
    failures = []
    job.start(
        worker,
        terminal_signals=(worker.finished, worker.failed),
        result_connections=((worker.failed, failures.append),),
    )

    qtbot.waitUntil(lambda: len(failures) == 1, timeout=3_000)
    assert "Insufficient well data points" in failures[0]
    qtbot.waitUntil(lambda: not job.is_running, timeout=3_000)


def test_create_factor_map_dialog_reject_and_close_shutdown(qtbot, monkeypatch):
    """Verify CreateFactorMapDialog closeEvent and reject cleanly terminate active jobs."""
    from unittest.mock import Mock
    from paleo_workbench.project.models import ProjectDocument, ProjectMeta
    from paleo_workbench.ui.pages.create_factor_map_dialog import CreateFactorMapDialog

    started = Event()
    release = Event()

    def _slow_create_factor_map(*args, **kwargs):
        started.set()
        release.wait(timeout=5.0)
        return Mock(), Mock()

    mock_service = Mock()
    mock_service.create_factor_map.side_effect = _slow_create_factor_map

    project = ProjectDocument(meta=ProjectMeta(name="test_proj"))
    dialog = CreateFactorMapDialog(project)
    qtbot.addWidget(dialog)
    dialog.service = mock_service

    # Trigger create
    dialog._on_create_clicked()
    assert started.wait(timeout=2.0)
    assert dialog._job.is_running is True

    # Reject dialog while worker is running
    dialog.reject()
    assert not dialog._job.is_running

    release.set()

