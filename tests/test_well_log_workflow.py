"""T-WELL-01: single-well facies — LAS bind, lithology/facies tracks, export/run/send."""

from __future__ import annotations

from pathlib import Path

from geoviz import CurveData, WellLogData

from paleo_workbench.app import PaleoWorkbenchWindow
from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage
from paleo_workbench.workflow.well_log_prediction import (
    export_well_canvas,
    merge_prediction_onto_well_log,
    run_well_log_facies_prediction,
)


def test_run_well_log_facies_prediction_binds_las_and_horizon():
    project = ProjectDocument.new("Well")
    project.stratigraphy.target_horizon = "ZJ2"
    project.resources.append(
        ResourceItem(name="A1.las", path="/tmp/A1.las", type="well_log", format="las")
    )
    task = run_well_log_facies_prediction(project, seed=3)
    assert task.status == "complete"
    assert task.model_metadata.get("workflow") == "well_log_facies"
    assert task.model_metadata.get("target_horizon") == "ZJ2"
    assert task.input_refs.get("well_log_resource_ids") == [project.resources[0].id]
    assert "ZJ2" in task.name


def test_merge_prediction_adds_lithology_and_facies_tracks():
    base = WellLogData(
        well_name="from-las",
        top_depth=1000.0,
        bottom_depth=1100.0,
        curves=[
            CurveData(
                name="GR",
                unit="GAPI",
                depth=[1000.0, 1050.0, 1100.0],
                values=[40.0, 60.0, 50.0],
            )
        ],
    )
    task = type(
        "T",
        (),
        {
            "result_summary": {
                "predicted_regions": [
                    {"facies": "三角洲前缘砂体", "probability": 0.9},
                    {"facies": "分流间湾泥", "probability": 0.6},
                ]
            }
        },
    )()
    merged = merge_prediction_onto_well_log(base, task)
    assert len(merged.lithology) == 2
    assert merged.lithology[0].top == 1000.0
    assert "砂" in merged.lithology[0].lithology or merged.lithology[0].lithology == "砂岩"
    assert merged.intervals is not None
    assert len(merged.intervals.facies.phase) == 2
    assert merged.intervals.facies.phase[0].name == "三角洲前缘砂体"
    # Original curves preserved
    assert merged.curves[0].name == "GR"
    assert merged.well_name == "from-las"


def test_canvas_builds_lithology_track_for_synthetic(qtbot, monkeypatch):
    from paleo_workbench.prediction.adapters import MockPredictionAdapter
    from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel

    # Legacy QPainter canvas is the target; keep the engine backend out so the
    # track kinds come from the legacy canvas regardless of binding presence.
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    project = ProjectDocument.new("Tracks")
    task = MockPredictionAdapter().run(project, [], seed=1)
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    panel.update_state(task)
    kinds = panel.track_kinds()
    assert "LithologyTrack" in kinds
    assert "FaciesTrack" in kinds or "CurveTrack" in kinds


def test_canvas_merges_facies_onto_bound_las(qtbot, monkeypatch):
    from paleo_workbench.project.models import PredictionTask
    from paleo_workbench.ui.pages.well_log_canvas_panel import WellLogCanvasPanel
    from paleo_workbench.viz.adapter import VizAdapter
    from paleo_workbench.viz.models import VizPayload

    project = ProjectDocument.new("BoundLas")
    resource = ResourceItem(
        name="demo.las", path="/fake/demo.las", type="well_log", format="las"
    )
    project.resources.append(resource)
    task = PredictionTask(
        name="bound",
        status="complete",
        input_refs={"well_log_resource_ids": [resource.id]},
        result_summary={
            "predicted_regions": [
                {"facies": "滨岸砂体", "probability": 0.85},
                {"facies": "分流间湾泥", "probability": 0.55},
            ]
        },
    )
    known = WellLogData(
        well_name="from-adapter",
        top_depth=0.0,
        bottom_depth=100.0,
        curves=[
            CurveData(name="GR", unit="GAPI", depth=[0.0, 50.0, 100.0], values=[10, 20, 15])
        ],
    )

    def _fake_resolve(self, ref, project_arg):
        return VizPayload(kind="well_log", label="from-adapter", well_log=known)

    monkeypatch.setattr(VizAdapter, "resolve", _fake_resolve)
    # Legacy QPainter canvas is the target (see test above for rationale).
    monkeypatch.setenv("PALEO_USE_WELLLOG_ENGINE", "0")
    panel = WellLogCanvasPanel()
    qtbot.addWidget(panel)
    panel.update_state(task, project=project)

    assert panel.has_bound_las() is True
    assert panel.well_log_data.well_name == "from-adapter"
    assert len(panel.well_log_data.lithology) == 2
    assert "LithologyTrack" in panel.track_kinds()


def test_page_run_and_export_png(qtbot, tmp_path, monkeypatch):
    project = ProjectDocument.new("RunExport")
    project.stratigraphy.target_horizon = "H1"
    page = WellLogPredictionPage()
    qtbot.addWidget(page)
    page.set_project(project)
    page.update_state([], project=project)

    page.evidence_panel.run_btn.click()
    assert len(project.prediction_tasks) == 1
    assert page.canvas_panel.is_canvas_ready()
    assert page.evidence_panel.horizon_value.text() == "H1"

    out = tmp_path / "well.png"
    # Patch on the page module's imported symbols (not nested dotted class attrs).
    import paleo_workbench.ui.pages.well_log_prediction_page as wlp_mod

    monkeypatch.setattr(
        wlp_mod.QFileDialog,
        "getSaveFileName",
        lambda *a, **k: (str(out), "PNG (*.png)"),
    )
    # Avoid modal information dialog hanging tests
    monkeypatch.setattr(
        wlp_mod.QMessageBox,
        "information",
        lambda *a, **k: None,
    )
    # Avoid modal warning dialog hanging tests (export failure path)
    monkeypatch.setattr(
        wlp_mod.QMessageBox,
        "warning",
        lambda *a, **k: None,
    )
    page.evidence_panel.export_btn.click()
    assert out.exists()
    assert out.stat().st_size > 0


def test_app_send_to_preparation_builds_factor_maps(qtbot):
    project = ProjectDocument.new("SendPrep")
    project.stratigraphy.target_horizon = "C6"
    run_well_log_facies_prediction(project, seed=1)

    window = PaleoWorkbenchWindow(project=project)
    qtbot.addWidget(window)
    page = window.app_shell.well_log_prediction_page_widget()
    assert isinstance(page, WellLogPredictionPage)

    page.evidence_panel.send_btn.click()
    assert len(window.project.factor_map_tasks) >= 1
    assert all(t.status == "complete" for t in window.project.factor_map_tasks)
