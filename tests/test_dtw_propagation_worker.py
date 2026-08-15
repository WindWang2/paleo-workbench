"""DTW propagation: bounded band, off-thread execution, cooperative cancel (C10)."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from geoviz import CurveData, WellLogData

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.dtw_propagation_worker import (
    DtwPropagationWorker,
    bounded_dtw_band,
)
from paleo_workbench.ui.pages.stratigraphy_correlation_page import (
    StratigraphyCorrelationPage,
)

DAT = (
    "#WellTops File From SMI\n"
    "A1 X 850.0 0 0 0 850.0 0\n"
    "A1 C1 1164.0 0 0 0 1164.0 0\n"
    "A2 C1 1200.0 0 0 0 1200.0 0\n"
)


def _log(name: str, n_samples: int = 81) -> WellLogData:
    return WellLogData(
        well_name=name,
        top_depth=800.0,
        bottom_depth=1600.0,
        curves=[
            CurveData(
                name="GR",
                unit="API",
                depth=[float(d) for d in range(800, 800 + n_samples, 1)],
                values=[float(d % 100) for d in range(800, 800 + n_samples, 1)],
                display_range=(0.0, 100.0),
            )
        ],
    )


def _project(tmp_path: Path) -> ProjectDocument:
    dat = tmp_path / "DC.dat"
    dat.write_text(DAT, encoding="utf-8")
    project = ProjectDocument.new("UI")
    project.resources.extend(
        [
            ResourceItem(name="A1.las", path="/a1.las", type="well_log", format="las"),
            ResourceItem(name="A2.las", path="/a2.las", type="well_log", format="las"),
            ResourceItem(name="DC.dat", path=str(dat), type="well_stratification", format="dat"),
        ]
    )
    return project


def _load_page(qtbot, tmp_path, monkeypatch) -> StratigraphyCorrelationPage:
    import paleo_workbench.ui.pages.stratigraphy_correlation_page as mod

    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    monkeypatch.setattr(
        mod,
        "load_correlation_wells",
        lambda project, resource_ids=None, max_wells=8: (
            [_log("A1"), _log("A2")],
            ["A1", "A2"],
            [],
        ),
    )
    page = StratigraphyCorrelationPage()
    qtbot.addWidget(page)
    page.set_project(_project(tmp_path))
    page.update_state()
    page.load_section()
    return page


# --------------------------------------------------------------------------- band cap


def test_bounded_dtw_band_caps_memory_for_large_curves():
    """50k-sample wells must not allocate the ~10 GB default-band matrix."""
    band = bounded_dtw_band(50_000)
    cells = 50_000 * (2 * band + 1)
    assert cells <= 4_100_000  # ~33 MB float64 ceiling
    band_100k = bounded_dtw_band(100_000)
    assert 100_000 * (2 * band_100k + 1) <= 4_100_000
    # Typical wells keep the original engine band (numerics preserved).
    assert bounded_dtw_band(2_000) == 500
    assert bounded_dtw_band(81) == 20
    # An explicit band below the cap is respected.
    assert bounded_dtw_band(50_000, band_radius=8) == 8


# --------------------------------------------------------------------------- worker


class _FakeCanvas:
    """Records the propagate call; returns a canned pick list."""

    def __init__(self):
        self.calls = []
        self.picks = ["p1"]

    def propagate_pick_via_dtw(
        self,
        ref_well,
        ref_depth,
        formation,
        band_radius=None,
        progress_callback=None,
    ):
        self.calls.append(
            {
                "ref_well": ref_well,
                "ref_depth": ref_depth,
                "formation": formation,
                "band_radius": band_radius,
                "thread": threading.current_thread().name,
            }
        )
        if progress_callback is not None:
            progress_callback(1, 1)
        return list(self.picks)


def test_worker_runs_propagation_with_bounded_band(qtbot):
    canvas = _FakeCanvas()
    worker = DtwPropagationWorker(
        canvas,
        ref_well="A1",
        ref_depth=1164.0,
        formation="C1",
        n_samples=50_000,
    )
    with qtbot.waitSignal(worker.finished, timeout=5_000) as sig:
        worker.run()
    assert sig.args[0] == ["p1"]
    assert len(canvas.calls) == 1
    call = canvas.calls[0]
    assert call["ref_well"] == "A1"
    assert call["band_radius"] == bounded_dtw_band(50_000)
    assert call["band_radius"] <= 40


def test_worker_precancel_emits_cancelled(qtbot):
    worker = DtwPropagationWorker(
        _FakeCanvas(),
        ref_well="A1",
        ref_depth=1164.0,
        formation="C1",
        n_samples=100,
    )
    worker.cancel()
    with qtbot.waitSignal(worker.cancelled, timeout=2_000):
        worker.run()


def test_worker_midrun_cancel_raises_jobcancelled(qtbot):
    """Cancelling during a well boundary surfaces as a clean cancelled signal."""

    class _BlockingCanvas:
        def propagate_pick_via_dtw(
            self, ref_well, ref_depth, formation, band_radius=None, progress_callback=None
        ):
            if progress_callback is not None:
                progress_callback(1, 1)  # cancel flag is set → JobCancelled
            return []

    worker = DtwPropagationWorker(
        _BlockingCanvas(),
        ref_well="A1",
        ref_depth=1164.0,
        formation="C1",
        n_samples=100,
    )
    worker.cancel()
    with qtbot.waitSignal(worker.cancelled, timeout=2_000):
        worker.run()


# --------------------------------------------------------------------------- page wiring


def test_run_dtw_executes_off_gui_thread_with_capped_band(qtbot, tmp_path, monkeypatch):
    """_run_dtw must not call propagate synchronously in the slot (C10)."""
    page = _load_page(qtbot, tmp_path, monkeypatch)
    canvas = page.cross_host.widget
    canvas.picks_model.add_pick("C1", "A1", 1164.0)

    recorder = _FakeCanvas()
    monkeypatch.setattr(canvas, "propagate_pick_via_dtw", recorder.propagate_pick_via_dtw)

    page._run_dtw()
    assert recorder.calls == []  # nothing ran synchronously in the slot
    assert page.dtw_btn.isEnabled() is False  # busy state

    def _done():
        return bool(recorder.calls) and "建议拾取" in page.status_label.text()

    qtbot.waitUntil(_done, timeout=10_000)
    call = recorder.calls[0]
    # Executed on the owned worker thread, not the GUI thread.
    assert call["thread"] != threading.current_thread().name
    # Band capped to the loaded curves' sample count (81 samples → 20).
    assert call["band_radius"] == 20
    qtbot.waitUntil(lambda: page.dtw_btn.isEnabled(), timeout=5_000)
    page.shutdown_workers(2_000)


def test_run_dtw_requires_pick_first(qtbot, tmp_path, monkeypatch):
    page = _load_page(qtbot, tmp_path, monkeypatch)
    page._run_dtw()
    assert "参考拾取点" in page.status_label.text()
    assert not page._dtw_job.is_running


def test_run_dtw_shutdown_cancels_inflight_job(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.ui.thread_keeper import detached_job_keeper

    page = _load_page(qtbot, tmp_path, monkeypatch)
    canvas = page.cross_host.widget
    canvas.picks_model.add_pick("C1", "A1", 1164.0)

    started = threading.Event()
    release = threading.Event()

    class _SlowCanvas(_FakeCanvas):
        def propagate_pick_via_dtw(
            self, ref_well, ref_depth, formation, band_radius=None, progress_callback=None
        ):
            self.calls.append({"thread": threading.current_thread().name})
            started.set()
            # Block until the test releases the worker after shutdown.
            release.wait(timeout=10)
            return []

    monkeypatch.setattr(
        canvas, "propagate_pick_via_dtw", _SlowCanvas().propagate_pick_via_dtw
    )
    page._run_dtw()
    qtbot.waitUntil(lambda: started.is_set(), timeout=5_000)
    page.shutdown_workers(1_000)
    assert not page._dtw_job.is_running
    # Release the detached worker so its thread exits before teardown.
    release.set()
    qtbot.waitUntil(lambda: detached_job_keeper().job_count() == 0, timeout=5_000)
