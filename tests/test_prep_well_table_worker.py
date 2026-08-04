"""ISS-PREP-01: WellTable panel + async factor prepare worker."""

from __future__ import annotations

from threading import Event

from PySide6.QtCore import QCoreApplication

from paleo_workbench.project.models import (
    FactorMapTask,
    ProjectDocument,
    WellTable,
    WellTableRow,
)
from paleo_workbench.ui.pages.factor_prepare_worker import FactorPrepareWorker
from paleo_workbench.ui.pages.preparation_page import PreparationPage
from paleo_workbench.ui.pages.well_table_panel import WellTablePanel
from paleo_workbench.workflow.well_table import well_table_from_sample_points


def test_well_table_panel_renders_rows_and_qc(qtbot):
    panel = WellTablePanel()
    qtbot.addWidget(panel)
    table = well_table_from_sample_points(
        [
            {"well": "A1", "x": 1, "y": 2, "value": 0.3, "H_s": 3, "H_t": 10},
            {"well": "B1", "x": 2, "y": 3, "value": 0.5},
        ],
        name="Demo",
        target_horizon="C6",
        factor_type="砂地比",
    )
    table.rows[1].qc_flag = "outlier"
    panel.update_from_well_table(table)
    assert panel.table.rowCount() == 2
    assert panel.table.isHidden() is False
    assert "C6" in panel.title_label.text()
    assert "outlier" in panel.summary_label.text()


def test_well_table_panel_empty_state(qtbot):
    panel = WellTablePanel()
    qtbot.addWidget(panel)
    panel.update_from_well_table(None)
    assert panel.table.isHidden()
    assert not panel.empty_label.isHidden()


def test_preparation_page_shows_well_table_from_project(qtbot):
    project = ProjectDocument.new("W")
    project.well_tables.append(
        WellTable(
            name="wells",
            rows=[WellTableRow(name="A", x=0, y=0, z=1.0)],
        )
    )
    page = PreparationPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state([])
    assert page.well_table_panel.table.rowCount() == 1


def test_preparation_page_derives_well_table_from_factor_samples(qtbot):
    project = ProjectDocument.new("F")
    project.factor_map_tasks.append(
        FactorMapTask(
            name="厚度",
            target_horizon="H1",
            factor_type="地层厚度",
            method="IDW",
            parameters={
                "sample_points": [
                    {"well": "W1", "x": 0, "y": 0, "value": 10},
                    {"well": "W2", "x": 1, "y": 1, "value": 12},
                ]
            },
            status="pending",
        )
    )
    page = PreparationPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state(project.factor_map_tasks)
    assert page.well_table_panel.table.rowCount() == 2


def test_factor_prepare_worker_runs_batch(qtbot):
    project = ProjectDocument.new("Worker")
    project.stratigraphy.target_horizon = "H1"
    # empty tasks → worker creates defaults
    worker = FactorPrepareWorker(project, method="IDW")
    results: list[int] = []
    completed: list[object] = []
    errors: list[str] = []
    worker.finished.connect(results.append)
    worker.completed.connect(completed.append)
    worker.failed.connect(errors.append)
    worker.run()
    assert errors == []
    assert results and results[0] >= 1
    assert project.factor_map_tasks == []
    assert all(t.status == "complete" for t in completed[0].factor_map_tasks)


def test_factor_prepare_worker_returns_snapshot_result_without_mutating_live_project(qtbot):
    project = ProjectDocument.new("Snapshot")
    project.stratigraphy.target_horizon = "H1"
    worker = FactorPrepareWorker(project, method="IDW")
    completed: list[object] = []
    worker.completed.connect(completed.append)

    worker.run()

    assert project.factor_map_tasks == []
    assert completed
    result = completed[0]
    assert result.count >= 1
    assert result.factor_map_tasks


def test_preparation_page_async_generate(qtbot, monkeypatch):
    """Generate starts a QThread and emits factor_maps_updated when done."""
    project = ProjectDocument.new("Async")
    project.stratigraphy.target_horizon = "C6"
    page = PreparationPage()
    qtbot.addWidget(page)
    page.set_project(project)

    events: list[str] = []
    page.factor_maps_updated.connect(lambda: events.append("updated"))

    page.task_panel.generate_btn.click()
    # Wait for background prepare (default tasks + IDW).
    qtbot.waitUntil(lambda: not page.is_prepare_running(), timeout=15000)
    # Process queued finished slot
    QCoreApplication.processEvents()
    qtbot.waitUntil(lambda: "updated" in events, timeout=5000)

    assert project.factor_map_tasks
    assert all(t.status == "complete" for t in project.factor_map_tasks)
    assert page.task_panel.generate_btn.isEnabled()


def test_shutdown_workers_is_safe(qtbot):
    page = PreparationPage()
    qtbot.addWidget(page)
    page.shutdown_workers()  # no-op when idle
    assert page.is_prepare_running() is False


def test_preparation_factor_uses_owned_worker_job_lifecycle(qtbot):
    from paleo_workbench.ui.owned_worker_job import OwnedWorkerJob

    page = PreparationPage()
    qtbot.addWidget(page)

    assert isinstance(page._prepare_job, OwnedWorkerJob)
    assert not hasattr(page, "_prepare_thread")
    assert not hasattr(page, "_prepare_worker")
    assert not hasattr(page, "_prepare_token")
    assert not hasattr(page, "_prepare_target_project")


def test_running_prepare_shutdown_is_kept_and_stale_snapshot_never_commits(
    qtbot,
    monkeypatch,
):
    from paleo_workbench.ui.thread_keeper import detached_job_keeper

    project = ProjectDocument.new("Shutdown")
    page = PreparationPage()
    qtbot.addWidget(page)
    page.set_project(project)
    started = Event()
    release = Event()

    def blocked_prepare(snapshot, method="IDW", **_kwargs):
        started.set()
        release.wait(timeout=5.0)
        snapshot.factor_map_tasks = [
            FactorMapTask(
                name="stale",
                target_horizon="H",
                factor_type="地层厚度",
                status="complete",
            )
        ]
        return snapshot.factor_map_tasks

    monkeypatch.setattr(
        # FactorPrepareWorker imports batch_prepare_factor_maps into its own
        # module namespace, so the blocker must be patched there (patching the
        # workflow module cannot intercept the worker-thread call).
        "paleo_workbench.ui.pages.factor_prepare_worker.batch_prepare_factor_maps",
        blocked_prepare,
    )
    page._start_prepare_worker("IDW")
    assert started.wait(timeout=2.0)
    thread = page._prepare_job.thread
    assert thread is not None

    page.shutdown_workers(wait_ms=1)

    keeper = detached_job_keeper()
    assert keeper.owns(thread)
    assert project.factor_map_tasks == []
    release.set()
    qtbot.waitUntil(lambda: not keeper.owns(thread), timeout=3000)
    QCoreApplication.processEvents()
    assert project.factor_map_tasks == []
