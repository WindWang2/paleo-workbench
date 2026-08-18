"""#842: well-log LAS resolution must run off the GUI thread on a cold cache.

The #659 async-LAS fix only covered the correlation page. The visualization
page and the well-log prediction panel still resolved ``well_log`` refs
synchronously on the GUI thread (``VizAdapter.resolve`` →
``load_well_log_from_path``), freezing the event loop for seconds on multi-MB
LAS files. The LRU-hit path stays synchronous (fast), the cold path must parse
on a worker thread and deliver the payload back via a queued signal.
"""

from __future__ import annotations

import threading
from pathlib import Path

from paleo_workbench.project.models import PredictionTask, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.visualization_page import VisualizationPage
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
from paleo_workbench.viz.adapter import VizAdapter


def _minimal_las(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                " WRAP. NO:",
                "~WELL INFORMATION",
                " STRT.M 0.0:",
                " STOP.M 10.0:",
                " STEP.M 1.0:",
                " NULL. -999.25:",
                " WELL. TEST:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                "~ASCII",
                "0.0 10.0",
                "1.0 20.0",
                "2.0 30.0",
            ]
        ),
        encoding="utf-8",
    )


def _cold_project(tmp_path: Path) -> tuple[ProjectDocument, ResourceItem, Path]:
    project = ProjectDocument.new("P")
    path = tmp_path / "w.las"
    _minimal_las(path)
    res = ResourceItem(name="w.las", path=str(path), type="well_log", format="las")
    project.resources.append(res)
    return project, res, path


def test_visualization_page_parses_las_off_gui_thread(qtbot, tmp_path: Path, monkeypatch):
    """#842: cold-cache open_ref must not parse inside the click slot."""
    import paleo_workbench.viz.adapter as adapter_mod

    project, _res, _path = _cold_project(tmp_path)
    started = threading.Event()
    release = threading.Event()
    threads: list[str] = []

    def _slow_load(p):
        threads.append(threading.current_thread().name)
        started.set()
        release.wait(timeout=5)
        from paleo_workbench.viz.well_log_load import load_well_log_from_path

        return load_well_log_from_path(p)

    monkeypatch.setattr(adapter_mod, "load_well_log_from_path", _slow_load)

    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state(project.resources, [], [])  # auto-opens the first well_log ref

    # The parse must not have started on the GUI thread.
    assert threads == []
    assert "正在加载" in page.composite_panel.status_label.text()

    gui_thread = threading.current_thread().name
    qtbot.waitUntil(started.is_set, timeout=5_000)
    assert threads[0] != gui_thread

    release.set()
    qtbot.waitUntil(
        lambda: len(page.composite_panel.well_canvas.tracks) > 0, timeout=10_000
    )
    assert page.trace_panel.kind_value.text() == "well_log"
    page.shutdown_workers(2_000)


def test_visualization_page_well_log_cache_hit_stays_sync(qtbot, tmp_path: Path, monkeypatch):
    """#842: an LRU-warm ref must keep the synchronous fast path."""
    project, res, _path = _cold_project(tmp_path)
    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state(project.resources, [], [])
    ref = VizAdapter().ref_from_resource(res)
    qtbot.waitUntil(
        lambda: len(page.composite_panel.well_canvas.tracks) > 0, timeout=10_000
    )

    threads: list[str] = []
    real_resolve = VizAdapter.resolve

    def _spy_resolve(self, ref, project_arg):
        threads.append(threading.current_thread().name)
        return real_resolve(self, ref, project_arg)

    monkeypatch.setattr(VizAdapter, "resolve", _spy_resolve)
    page.open_ref(ref)

    # Warm cache → synchronous on the GUI thread, no worker spawned.
    assert threads == [threading.current_thread().name]
    assert len(page.composite_panel.well_canvas.tracks) > 0
    page.shutdown_workers(2_000)


def test_well_log_canvas_panel_parses_bound_las_off_gui_thread(qtbot, tmp_path: Path, monkeypatch):
    """#842: the prediction panel's bound-LAS resolve must run off the GUI thread."""
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    import paleo_workbench.viz.adapter as adapter_mod

    project, res, _path = _cold_project(tmp_path)
    task = PredictionTask(
        name="bound-task",
        status="complete",
        input_refs={"well_log_resource_ids": [res.id]},
        result_summary={"predicted_regions": [{"facies": "砂", "probability": 0.9}]},
    )
    started = threading.Event()
    release = threading.Event()
    threads: list[str] = []

    def _slow_load(p):
        threads.append(threading.current_thread().name)
        started.set()
        release.wait(timeout=5)
        from paleo_workbench.viz.well_log_load import load_well_log_from_path

        return load_well_log_from_path(p)

    monkeypatch.setattr(adapter_mod, "load_well_log_from_path", _slow_load)

    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    gui_thread = threading.current_thread().name
    panel.update_state(task, project=project)

    assert threads == []
    qtbot.waitUntil(started.is_set, timeout=5_000)
    assert threads[0] != gui_thread

    release.set()
    qtbot.waitUntil(
        lambda: panel.well_log_data is not None and panel.has_bound_las(),
        timeout=10_000,
    )
    assert panel.well_log_data.well_name is not None
    panel.shutdown()