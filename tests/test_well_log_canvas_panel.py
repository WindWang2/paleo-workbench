from geoviz import CurveData, WellLogData

from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import PredictionTask, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
from paleo_workbench.viz.models import VizPayload
from paleo_workbench.viz import welllog_engine_adapter as engine_adapter

def test_well_log_canvas_panel_empty_state(qtbot):
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)

    panel.update_state(None)

    assert panel.objectName() == "WellLogCanvasPanel"
    assert panel.empty_label.text() == "未选择预测任务"
    assert panel.canvas.tracks == []


def test_well_log_canvas_panel_loads_tracks(qtbot, monkeypatch):
    # Legacy QPainter canvas is the target of this test; the default engine
    # backend would hand the data to WellLogEngine instead (when the binding is
    # installed), leaving the canvas empty. Opt out explicitly for determinism.
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=1)
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)

    panel.update_state(task)

    assert panel.empty_label.isHidden()
    assert panel.well_log_data.well_name == task.name
    assert len(panel.canvas.tracks) > 0


def test_well_log_canvas_unbound_uses_mock(qtbot, monkeypatch):
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    task = PredictionTask(
        name="m",
        status="complete",
        result_summary={"predicted_regions": [{"facies": "砂", "probability": 0.8}]},
    )
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)

    panel.update_state(task, project=None)

    assert panel.well_log_data is not None
    assert panel.stack.currentWidget() is panel.canvas_scroll
    assert panel.well_log_data.well_name == "m"


def test_well_log_canvas_uses_bound_las(qtbot, monkeypatch):
    project = ProjectDocument.new("Bound")
    resource = ResourceItem(
        name="demo.las",
        path="/fake/demo.las",
        type="well_log",
        format="las",
    )
    project.resources.append(resource)
    task = PredictionTask(
        name="bound-task",
        status="complete",
        input_refs={"well_log_resource_ids": [resource.id]},
        result_summary={"predicted_regions": [{"facies": "砂", "probability": 0.9}]},
    )
    known = WellLogData(
        well_name="from-adapter",
        top_depth=0.0,
        bottom_depth=1.0,
        curves=[CurveData(name="GR", unit="GAPI", depth=[0.0, 1.0], values=[10.0, 20.0])],
        facies_intervals=[],
    )

    def _fake_resolve(self, ref, project_arg):
        assert ref.kind == "well_log"
        assert ref.id == resource.id
        return VizPayload(kind="well_log", label="from-adapter", well_log=known)

    # Patch class method (string path breaks when pages lazy __getattr__ is active).
    from paleo_workbench.viz.adapter import VizAdapter

    monkeypatch.setattr(VizAdapter, "resolve", _fake_resolve)
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")

    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    panel.update_state(task, project=project)

    # Merge prediction facies onto a copy of LAS data (identity not preserved).
    assert panel.well_log_data is not None
    assert panel.well_log_data.well_name == "from-adapter"
    assert panel.has_bound_las() is True
    assert len(panel.well_log_data.lithology) >= 1
    assert panel.stack.currentWidget() is panel.canvas_scroll
    assert panel.empty_label.isHidden()


def test_well_log_canvas_bound_failure_shows_message(qtbot, monkeypatch):
    project = ProjectDocument.new("BoundFail")
    resource = ResourceItem(
        name="bad.las",
        path="/missing/bad.las",
        type="well_log",
        format="las",
    )
    project.resources.append(resource)
    task = PredictionTask(
        name="bound-fail",
        status="complete",
        input_refs={"well_log_resource_ids": [resource.id]},
    )

    def _fake_resolve(self, ref, project_arg):
        return VizPayload(
            kind="message",
            label="bad.las",
            message="井数据文件不存在或不可读",
        )

    from paleo_workbench.viz.adapter import VizAdapter

    monkeypatch.setattr(VizAdapter, "resolve", _fake_resolve)

    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    panel.update_state(task, project=project)

    assert panel.well_log_data is None
    assert panel.stack.currentWidget() is panel.empty_label
    assert panel.empty_label.text() == "井数据文件不存在或不可读"


def test_canvas_panel_default_backend_is_engine(qtbot, monkeypatch):
    # #174: default ON when env unset.
    monkeypatch.delenv("PALEO_USE_WELLLOG_ENGINE", raising=False)
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    assert panel.backend() == "engine"


def test_canvas_panel_env_opts_out_to_legacy(qtbot, monkeypatch):
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    assert panel.backend() == "legacy"


def test_canvas_panel_explicit_backend_switch_keeps_legacy(qtbot, monkeypatch):
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    task = PredictionTask(
        name="switch",
        status="complete",
        result_summary={"predicted_regions": [{"facies": "砂", "probability": 0.7}]},
    )
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    panel.update_state(task)
    assert panel.backend() == "legacy"
    assert panel.is_canvas_ready()
    assert panel.stack.currentWidget() is panel.canvas_scroll

    # Engine without binding → diagnostic host, Legacy still available.
    panel.set_backend("engine")
    assert panel.backend() == "engine"
    # Either engine view ready (binding present) or placeholder/fallback.
    if panel.engine_load_report() is None:
        # Fallback paints legacy tracks so the page remains usable.
        assert panel.stack.currentWidget() in (panel.engine_host, panel.canvas_scroll)
    panel.set_backend("legacy")
    assert panel.backend() == "legacy"
    assert panel.stack.currentWidget() is panel.canvas_scroll
    assert panel.is_canvas_ready()


def test_canvas_panel_engine_path_with_fake_view(qtbot, monkeypatch):
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "1")

    from PySide6.QtWidgets import QWidget

    class FakeView(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.submit_calls = 0

        def submit_multi_track(self, payload):
            self.submit_calls += 1
            return {
                "depth": {"access_mode": "zero_copy"},
                "curve_count": len(payload["curves"]),
                "track_count": len(payload["tracks"]),
                "render_prepared": True,
            }

    def _fake_import():
        return object(), FakeView, object()

    monkeypatch.setattr(engine_adapter, "try_import_welllog", _fake_import)

    task = PredictionTask(
        name="engine-task",
        status="complete",
        result_summary={"predicted_regions": [{"facies": "砂", "probability": 0.8}]},
    )
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    assert panel.backend() == "engine"
    panel.update_state(task)

    assert panel.engine_load_report() is not None
    assert panel.engine_load_report()["sample_count"] > 0
    assert panel.engine_load_report()["curve_count"] >= 1
    assert panel.is_canvas_ready()
    assert "WellLogEngine" in panel.track_kinds()
    assert panel._engine_view is not None
    assert panel._engine_view.submit_calls == 1

    # Engine → Legacy detaches the native widget/session rather than retaining
    # an invisible document and its pinned NumPy buffers.
    view = panel._engine_view
    panel.set_backend("legacy")
    assert panel._engine_view is None
    assert view.parent() is None
    assert panel.stack.currentWidget() is panel.canvas_scroll

    # Project/task clear releases load (no stale document report).
    panel.update_state(None)
    assert panel.engine_load_report() is None
    assert panel.well_log_data is None
