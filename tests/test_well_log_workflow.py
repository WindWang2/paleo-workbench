"""T-WELL-01: single-well facies — LAS bind, lithology/facies tracks, export/run/send."""

from __future__ import annotations

from pathlib import Path

from geoviz import CurveData, WellLogData

from paleo_workbench.project.models import ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.well_log_prediction_page import WellLogPredictionPage
from paleo_workbench.viz.prediction_helpers import (
    build_ai_prediction_tracks,
    export_well_canvas,
    merge_prediction_onto_well_log,
)


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


def test_prediction_tracks_show_facies_and_percentage_confidence(qtbot):
    from geoviz_well_log.renderer import IntervalTrack

    base = WellLogData(
        well_name="from-las",
        top_depth=1000.0,
        bottom_depth=1100.0,
        curves=[
            CurveData(
                name="GR",
                unit="GAPI",
                depth=[1000.0, 1100.0],
                values=[40.0, 60.0],
            )
        ],
    )
    task = type(
        "T",
        (),
        {
            "result_summary": {
                "predicted_regions": [
                    {"top": 1000.0, "bottom": 1050.0, "facies": "砂体", "probability": 0.87},
                    {"top": 1050.0, "bottom": 1100.0, "facies": "泥岩", "probability": 0.62},
                ]
            }
        },
    )()

    tracks = build_ai_prediction_tracks(base, task)

    assert all(isinstance(track, IntervalTrack) for track in tracks)
    assert [track.label for track in tracks] == ["AI预测相", "AI预测置信度"]
    assert [item.name for item in tracks[0].intervals] == ["砂体", "泥岩"]
    assert [item.name for item in tracks[1].intervals] == ["87%", "62%"]


def test_prediction_tracks_keep_facies_categorical_and_confidence_continuous(qtbot):
    """Facies colours are stable; probability uses its own ordered heatmap."""
    base = WellLogData(
        well_name="from-las",
        top_depth=1000.0,
        bottom_depth=1100.0,
        curves=[
            CurveData(
                name="GR",
                unit="GAPI",
                depth=[1000.0, 1100.0],
                values=[40.0, 60.0],
            )
        ],
    )
    task = type(
        "T",
        (),
        {
            "result_summary": {
                "predicted_regions": [
                    {
                        "top": 1000.0,
                        "bottom": 1050.0,
                        "facies": "分流间湾",
                        "probability": 0.12,
                    },
                    {
                        "top": 1050.0,
                        "bottom": 1100.0,
                        "facies": "河道砂体",
                        "probability": 0.91,
                    },
                ]
            }
        },
    )()

    facies_track, confidence_track = build_ai_prediction_tracks(base, task)

    assert type(facies_track).__name__ == "FaciesTextureTrack"
    assert facies_track._colors["分流间湾"] == "#d4c5a9"
    assert facies_track._colors["河道砂体"] == "#ebd2b0"
    assert facies_track.texture_path_for("分流间湾").name == "tex_mudstone.svg"
    assert facies_track.texture_path_for("河道砂体").name == "tex_sandstone_medium.svg"
    assert not facies_track._texture_cache.brush_for("tex_mudstone").texture().isNull()
    assert type(confidence_track).__name__ == "ConfidenceHeatmapTrack"
    assert confidence_track.color_for_probability(0.12) != confidence_track.color_for_probability(0.91)
    assert (
        confidence_track.color_for_probability(0.12).lightness()
        > confidence_track.color_for_probability(0.91).lightness()
    )


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


def test_canvas_renders_prediction_in_dedicated_tracks_without_altering_bound_las(qtbot, monkeypatch):
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

    # Since #842 cold LAS loads bind asynchronously (worker thread); wait for
    # the deferred bind instead of asserting synchronously.
    qtbot.waitUntil(
        lambda: panel.well_log_data is not None and panel.has_bound_las(),
        timeout=10_000,
    )
    assert panel.well_log_data.well_name == "from-adapter"
    assert list(panel.well_log_data.lithology) == []
    assert "FaciesTextureTrack" in panel.track_kinds()
    assert "ConfidenceHeatmapTrack" in panel.track_kinds()
    panel.shutdown()


def test_page_run_and_export_png(qtbot, tmp_path, monkeypatch):
    from paleo_workbench.catalog import (
        CoreCatalogAdapter,
        DataCatalogService,
        reset_catalog,
        set_catalog,
    )
    from paleo_workbench.prediction.providers import ensure_default_models

    project = ProjectDocument.new("RunExport")
    project.stratigraphy.target_horizon = "H1"
    well_path = tmp_path / "run.las"
    well_path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                "~WELL INFORMATION",
                " WELL. RUN-1:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                "~ASCII",
                "1000.0 40.0",
                "1010.0 50.0",
            ]
        ),
        encoding="utf-8",
    )
    resource = ResourceItem(
        id="well-run",
        name="run.las",
        path=str(well_path),
        type="well_log",
        format="las",
    )
    project.resources.append(resource)
    project_path = tmp_path / "proj" / "demo.paleo.json"
    project_path.parent.mkdir(parents=True, exist_ok=True)
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    service.migrate_legacy_resources(project.resources)
    ensure_default_models(service)
    try:
        page = WellLogPredictionPage()
        qtbot.addWidget(page)
        page.set_project(project)
        page.update_state([], project=project)
        assert page.select_well_resource(resource.id)
        qtbot.waitUntil(page.canvas_panel.has_bound_las, timeout=10_000)

        # Explicit demo mode operates on the selected Data Management well.
        # The inference runs on a worker thread.
        with qtbot.waitSignal(page.prediction_updated, timeout=5000):
            page.evidence_panel.demo_btn.click()
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
    finally:
        reset_catalog()
        service.close()


def test_page_online_run_uses_geoviz_engine_provider(qtbot, tmp_path, monkeypatch):
    """The primary well-log action is the explicit GeoVizEngine online path."""
    from paleo_workbench.catalog import (
        CoreCatalogAdapter,
        DataCatalogService,
        reset_catalog,
        set_catalog,
    )

    project = ProjectDocument.new("OnlineRun")
    well_path = tmp_path / "online.las"
    well_path.write_text(
        "\n".join(
            [
                "~VERSION INFORMATION",
                " VERS. 2.0:",
                "~WELL INFORMATION",
                " WELL. ONLINE-1:",
                "~CURVE INFORMATION",
                " DEPT.M :",
                " GR.GAPI :",
                "~ASCII",
                "1000.0 40.0",
                "1010.0 50.0",
            ]
        ),
        encoding="utf-8",
    )
    resource = ResourceItem(
        id="well-online",
        name=well_path.name,
        path=str(well_path),
        type="well_log",
        format="las",
    )
    project.resources.append(resource)
    project_path = tmp_path / "online.paleo.json"
    project_path.write_text("{}", encoding="utf-8")
    service = DataCatalogService.open(project_path)
    set_catalog(CoreCatalogAdapter(service))
    service.migrate_legacy_resources(project.resources)
    try:
        monkeypatch.setenv("PALEO_GEOVIZ_API_KEY", "ak_test")
        monkeypatch.setattr(
            "paleo_workbench.prediction.geoviz_online.run_single_well_prediction",
            lambda well_name, well_log, **kwargs: {
                "endpoint": kwargs["base_url"],
                "request_row_count": 2,
                "remote_model_version": kwargs["model_version_id"],
                "predicted_regions": [
                    {
                        "region_id": "inference_api_1",
                        "top": 999.5,
                        "bottom": 1000.5,
                        "facies": "河道砂体",
                        "probability": 0.87,
                    }
                ],
            },
        )
        page = WellLogPredictionPage()
        qtbot.addWidget(page)
        page.update_state([], project=project)
        assert page.select_well_resource(resource.id)
        qtbot.waitUntil(page.canvas_panel.has_bound_las, timeout=10_000)

        assert page.evidence_panel.run_btn.text() == "运行线上测井预测"
        with qtbot.waitSignal(page.prediction_updated, timeout=5_000):
            page.evidence_panel.run_btn.click()

        task = project.prediction_tasks[-1]
        assert task.model_metadata["model_id"] == "geoviz-online-single-well"
        assert task.result_summary["model_type"] == "inference_api_online"
        assert task.input_refs["well_log_resource_ids"] == [resource.id]
        assert "线上测井预测完成" in page.evidence_panel.status_value.text()
    finally:
        reset_catalog()
        service.close()
