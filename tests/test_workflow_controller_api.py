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

    state = {"snapshot": 0, "batch_calls": 0, "run_thread": None, "generation": None}

    class _FakeSnapshot:
        tasks = [object()]

    class _FakeResult:
        clean_count = 0
        executed_count = 0
        task_results = ()
        cancelled = False
        created_default_tasks = False

        @property
        def generation(self):
            # The process-global prepare generation counter is monotonic and
            # shared with every earlier test, so a hardcoded value only
            # matches when this test happens to run first. Echo the real
            # generation captured by the snapshot fake instead.
            return state["generation"]

    def _fake_snapshot(project, *, generation, method):
        state["snapshot"] += 1
        state["generation"] = generation
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




def _run_with_output(cat, *, operation, inputs, name, domain_task_id=None):
    """Mirror of tests/test_dependency_freshness.py helper (InMemoryCatalog)."""
    run = cat.begin_run(
        operation=operation,
        input_version_ids=list(inputs),
        parameters={},
        generator_version="gen-v1",
        domain_task_id=domain_task_id,
        input_snapshot_hash=None,
    )
    out = cat.register_derived(
        run_id=run.run_id,
        name=name,
        path=f"/tmp/{name}.npz",
        checksum=f"sha-{name}",
        kind="product",
        format="npz",
    )
    cat.complete_run(run.run_id)
    return run.run_id, out.version_id


def _recompute_catalog_with_stale_factor() -> "tuple[InMemoryCatalog, str]":

    """Catalog with raw -> h1 -> factor(t1), plus h2 superseding h1 (same asset).

    Returns (catalog, h2_version_id); the factor run consuming h1 is STALE.
    """
    from tests.fakes.inmemory_catalog import InMemoryCatalog

    cat = InMemoryCatalog()
    raw = cat.register_input(
        name="raw", path="/tmp/raw", checksum="sha-raw",
        kind="seismic", format="sgy", legacy_resource_id="res-raw",
    ).version_id
    _, h1 = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw],
        name="h1", domain_task_id="interp",
    )
    _, h2 = _run_with_output(
        cat, operation="horizon_interpretation", inputs=[raw],
        name="h2", domain_task_id="interp",
    )
    first = cat.resolve_version(h1)
    second = cat.resolve_version(h2)
    second.asset_id = first.asset_id  # same asset: h2 supersedes h1
    _run_with_output(
        cat, operation="factor_map", inputs=[h1],
        name="Fa", domain_task_id="t1",
    )
    return cat, h2


def test_recompute_requested_is_consumed_and_executes_plan(qtbot, monkeypatch):
    """#537: 更新受影响成果 must reach a controller action, run the minimal
    recompute plan off the GUI thread and refresh home steps.

    UI v2: the workflow-progress strip (and its button) is gone from the home
    page; the completion summary is shown in a dialog. Drive the controller
    entry point directly and capture that dialog's text."""
    import paleo_workbench.catalog.runtime as catalog_runtime
    from paleo_workbench.app import PaleoWorkbenchWindow
    from paleo_workbench.project.models import (
        FactorMapTask,
        HorizonInterpretationRef,
    )

    cat, h2 = _recompute_catalog_with_stale_factor()

    window = PaleoWorkbenchWindow()
    qtbot.addWidget(window)
    project = window.project
    project.factor_map_tasks.append(
        FactorMapTask(
            id="t1",
            name="H1 孔隙度",
            target_horizon="H1",
            factor_type="孔隙度",
            method="IDW",
            status="pending",
            parameters={
                "sample_points": [
                    {"x": 0.0, "y": 0.0, "value": 0.0},
                    {"x": 1.0, "y": 0.0, "value": 0.3},
                    {"x": 0.0, "y": 1.0, "value": 0.7},
                    {"x": 1.0, "y": 1.0, "value": 1.0},
                ]
            },
        )
    )
    project.horizon_interpretations.append(
        HorizonInterpretationRef(
            name="h2", horizon_key="H1", current_version_id=h2
        )
    )

    summaries: list[str] = []
    from paleo_workbench.ui import workflow_controller as wc_module

    monkeypatch.setattr(
        wc_module.QMessageBox, "information",
        lambda *args: summaries.append(str(args[-1])),
    )
    catalog_runtime.set_catalog(cat)
    try:
        window.workflow_controller._on_recompute_requested()
        qtbot.waitUntil(lambda: bool(summaries), timeout=20_000)
    finally:
        catalog_runtime.reset_catalog()

    text = summaries[-1]
    assert "需要更新" in text, f"plan summary should describe the stale step: {text}"
    # The factor_map step was executed (production interpolation path), so the
    # executor reported an 'ok' outcome rather than 'no handler'.
    assert "ok" in text.lower() or "执行结果" in text
    # The staged task copy was committed to the live project on the GUI thread.
    assert project.factor_map_tasks[0].status == "complete"
