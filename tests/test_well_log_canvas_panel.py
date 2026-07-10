from geoviz_well_log import CurveData, WellLogData

from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import PredictionTask, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
from paleo_workbench.viz.models import VizPayload


def test_well_log_canvas_panel_empty_state(qtbot):
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)

    panel.update_state(None)

    assert panel.objectName() == "WellLogCanvasPanel"
    assert panel.empty_label.text() == "未选择预测任务"
    assert panel.canvas.tracks == []


def test_well_log_canvas_panel_loads_tracks(qtbot):
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=1)
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)

    panel.update_state(task)

    assert panel.empty_label.isHidden()
    assert panel.well_log_data.well_name == task.name
    assert len(panel.canvas.tracks) > 0


def test_well_log_canvas_unbound_uses_mock(qtbot):
    task = PredictionTask(
        name="m",
        status="complete",
        result_summary={"predicted_regions": [{"facies": "砂", "probability": 0.8}]},
    )
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)

    panel.update_state(task, project=None)

    assert panel.well_log_data is not None
    assert panel.stack.currentWidget() is panel.canvas
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

    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    panel.update_state(task, project=project)

    assert panel.well_log_data is known
    assert panel.well_log_data.well_name == "from-adapter"
    assert panel.stack.currentWidget() is panel.canvas
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
