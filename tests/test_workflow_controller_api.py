"""WorkflowController public API surface (P1 refactor)."""


def test_workflow_controller_exposes_public_wiring_methods():
    from paleo_workbench.ui.workflow_controller import WorkflowController

    for name in (
        "wire_home_page",
        "wire_data_visualization_jump",
        "wire_mapping_page",
        "wire_preparation_page",
        "wire_sequence_page",
        "wire_seismic_page",
        "wire_well_log_page",
        "wire_review_page",
        "show_preview_settings",
        "apply_preview_settings",
    ):
        assert callable(getattr(WorkflowController, name, None)), name


def test_window_delegates_preview_settings_dialog_to_controller(qtbot):
    from paleo_workbench.app import PaleoWorkbenchWindow

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    assert window._preview_settings_dialog is None
    window.workflow_controller.preview_settings_dialog = object()
    assert window._preview_settings_dialog is window.workflow_controller.preview_settings_dialog


def test_send_to_prep_starts_worker_off_gui_thread(qtbot, monkeypatch):
    """发送制备 must run via FactorPrepareWorker, never the sync batch (C05)."""
    import threading

    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.project.models import PredictionTask
    from paleo_workbench.ui import workflow_controller as wc_mod
    from paleo_workbench.ui.pages.factor_prepare_worker import FactorPrepareWorker

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    window.project.prediction_tasks.append(
        PredictionTask(name="p1", status="complete")
    )

    state = {"snapshot": 0, "batch_calls": 0, "run_thread": None}

    class _FakeSnapshot:
        tasks = [object()]

    class _FakeResult:
        generation = 1
        clean_count = 0
        executed_count = 0
        task_results = ()
        cancelled = False
        created_default_tasks = False

    def _fake_snapshot(project, *, generation, method):
        state["snapshot"] += 1
        return _FakeSnapshot()

    monkeypatch.setattr(wc_mod, "build_prepare_snapshot", _fake_snapshot)

    # Subclass with run defined in the class body: PySide delivers class-body
    # methods directly on the owned QThread (monkeypatched plain functions are
    # delivered queued to the main thread).
    class _TestPrepareWorker(FactorPrepareWorker):
        created = 0

        def __init__(self, *args, **kwargs):
            _TestPrepareWorker.created += 1
            super().__init__(*args, **kwargs)

        def run(self):
            state["run_thread"] = threading.current_thread().name
            self.completed.emit(_FakeResult())
            self.finished.emit(1)

    monkeypatch.setattr(wc_mod, "FactorPrepareWorker", _TestPrepareWorker)

    def _recording_batch(*args, **kwargs):
        state["batch_calls"] += 1

    monkeypatch.setattr(
        "paleo_workbench.workflow.factor_interpolation.batch_prepare_factor_maps",
        _recording_batch,
    )

    page = window.app_shell.preparation_page_widget()
    controller = window.workflow_controller
    controller._on_well_log_send_to_prep()

    assert state["snapshot"] == 1
    assert _TestPrepareWorker.created == 1
    assert state["batch_calls"] == 0  # sync API never called from the slot
    assert controller._prepare_job.is_running
    qtbot.waitUntil(lambda: state["run_thread"] is not None, timeout=5_000)
    # Executed on the owned worker thread, not the GUI thread.
    assert state["run_thread"] != threading.current_thread().name
    # Fingerprint-guarded commit path reports through the preparation page.
    qtbot.waitUntil(
        lambda: "已制备" in page.task_panel.summary_label.text(), timeout=5_000
    )
    assert not controller._prepare_job.is_running
    controller._prepare_job.shutdown(1_000)
