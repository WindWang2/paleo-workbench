import numpy as np

from paleo_workbench.prediction.adapters import MockPredictionAdapter
from paleo_workbench.project.models import PredictionTask, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.seismic_view_panel import SeismicViewPanel
from paleo_workbench.viz.models import VizPayload


def test_seismic_view_panel_empty_state(qtbot):
    panel = SeismicViewPanel()
    qtbot.addWidget(panel)

    panel.update_state(None)

    assert panel.objectName() == "SeismicViewPanel"
    assert panel.empty_label.text() == "未选择预测任务"
    assert panel.volume_shape is None


def test_seismic_view_panel_loads_demo_volume(qtbot):
    project = ProjectDocument.new("Test")
    task = MockPredictionAdapter().run(project, [], seed=3)
    panel = SeismicViewPanel()
    qtbot.addWidget(panel)

    panel.update_state(task)

    assert panel.empty_label.isHidden()
    assert panel.volume_shape == (8, 10, 12)
    assert panel.view.is_ready()


def test_seismic_view_unbound_uses_mock(qtbot):
    task = PredictionTask(
        name="m",
        status="complete",
        result_summary={"predicted_regions": [{"facies": "砂", "probability": 0.8}]},
    )
    panel = SeismicViewPanel()
    qtbot.addWidget(panel)

    panel.update_state(task, project=None)

    assert panel.volume_shape == (8, 10, 12)
    assert panel.stack.currentWidget() is panel.view
    assert panel.view.is_ready()


def test_seismic_view_uses_bound_segy(qtbot, monkeypatch):
    project = ProjectDocument.new("Bound")
    resource = ResourceItem(
        name="demo.sgy",
        path="/fake/demo.sgy",
        type="seismic",
        format="sgy",
    )
    project.resources.append(resource)
    task = PredictionTask(
        name="bound-task",
        status="complete",
        input_refs={"seismic_resource_ids": [resource.id]},
    )
    known = np.ones((4, 5, 6), dtype=np.float32)

    def _fake_resolve(self, ref, project_arg):
        assert ref.kind == "seismic"
        assert ref.id == resource.id
        return VizPayload(kind="seismic", label="from-adapter", seismic_volume=known)

    # Patch class method (string path breaks when pages lazy __getattr__ is active).
    from paleo_workbench.viz.adapter import VizAdapter

    monkeypatch.setattr(VizAdapter, "resolve", _fake_resolve)

    panel = SeismicViewPanel()
    qtbot.addWidget(panel)
    panel.update_state(task, project=project)

    assert panel.volume_shape == (4, 5, 6)
    assert panel.stack.currentWidget() is panel.view
    assert panel.empty_label.isHidden()
    assert panel.view.is_ready()


def test_seismic_view_bound_failure_shows_message(qtbot, monkeypatch):
    project = ProjectDocument.new("BoundFail")
    resource = ResourceItem(
        name="bad.sgy",
        path="/missing/bad.sgy",
        type="seismic",
        format="sgy",
    )
    project.resources.append(resource)
    task = PredictionTask(
        name="bound-fail",
        status="complete",
        input_refs={"seismic_resource_ids": [resource.id]},
    )

    def _fake_resolve(self, ref, project_arg):
        return VizPayload(
            kind="message",
            label="bad.sgy",
            message="地震数据文件不存在或不可读",
        )

    from paleo_workbench.viz.adapter import VizAdapter

    monkeypatch.setattr(VizAdapter, "resolve", _fake_resolve)

    panel = SeismicViewPanel()
    qtbot.addWidget(panel)
    panel.update_state(task, project=project)

    assert panel.volume_shape is None
    assert panel.stack.currentWidget() is panel.empty_label
    assert panel.empty_label.text() == "地震数据文件不存在或不可读"
