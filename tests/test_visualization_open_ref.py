from pathlib import Path

from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.visualization_page import VisualizationPage
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


def test_open_ref_well_log_selects_well_tab(qtbot, tmp_path: Path):
    path = tmp_path / "w.las"
    _minimal_las(path)
    project = ProjectDocument.new("P")
    res = ResourceItem(name="w.las", path=str(path), type="well_log", format="las")
    project.resources.append(res)

    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state(project.resources, [], [])

    ref = VizAdapter().ref_from_resource(res)
    page.open_ref(ref)

    assert page.composite_panel.tabs.currentIndex() == 0  # 测井
    assert page.composite_panel.well_canvas is not None
    assert len(page.composite_panel.well_canvas.tracks) > 0
    # Cross-well primary canvas also receives a well via package API
    assert page.composite_panel.cross_well_widget.canvas_count >= 1

def test_open_ref_map_selects_map_tab(qtbot):
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[
            {
                "id": "f1",
                "name": "A",
                "coordinates": [[0, 0], [2, 0], [2, 2], [0, 0]],
            }
        ],
    )
    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state([], [], [doc])
    ref = VizAdapter().ref_from_map_document(doc)
    page.open_ref(ref)
    assert page.composite_panel.tabs.tabText(page.composite_panel.tabs.currentIndex()) == "古地理"


def test_summary_asset_selected_opens_ref(qtbot, tmp_path: Path):
    path = tmp_path / "w.las"
    _minimal_las(path)
    res = ResourceItem(name="w.las", path=str(path), type="well_log", format="las")
    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state([res], [], [])

    assert page.summary_panel.asset_list.count() >= 1
    page.summary_panel.asset_list.setCurrentRow(0)
    page.summary_panel.asset_list.itemActivated.emit(page.summary_panel.asset_list.item(0))

    assert page.composite_panel.tabs.tabText(page.composite_panel.tabs.currentIndex()) == "测井"
    assert page._current_ref is not None
    assert page._current_ref.kind == "well_log"


def test_trace_refresh_reloads_current(qtbot, tmp_path: Path):
    path = tmp_path / "w.las"
    _minimal_las(path)
    res = ResourceItem(name="w.las", path=str(path), type="well_log", format="las")
    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state([res], [], [])
    ref = VizAdapter().ref_from_resource(res)
    page.open_ref(ref)

    page.trace_panel.refresh_btn.click()
    assert page.trace_panel.kind_value.text() == "well_log"
    assert page.trace_panel.label_value.text()


def test_message_payload_clears_prior_well_tracks(qtbot, tmp_path: Path):
    path = tmp_path / "w.las"
    _minimal_las(path)
    res = ResourceItem(name="w.las", path=str(path), type="well_log", format="las")
    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state([res], [], [])
    page.open_ref(VizAdapter().ref_from_resource(res))
    assert len(page.composite_panel.well_canvas.tracks) > 0

    missing = ResourceItem(
        name="gone.las",
        path="/no/such/gone.las",
        type="well_log",
        format="las",
        status="missing",
    )
    page.update_state([res, missing], [], [])
    page.open_ref(VizAdapter().ref_from_resource(missing))

    assert page.composite_panel.well_canvas.tracks == []
    assert "不存在" in page.trace_panel.path_value.text() or "不可读" in page.trace_panel.path_value.text()


def test_refresh_without_ref_uses_prediction_fallback(qtbot):
    from paleo_workbench.project.models import PredictionTask

    task = PredictionTask(
        name="P1",
        seed=2,
        result_summary={"predicted_regions": [{"facies": "砂", "probability": 0.7}]},
    )
    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state([], [task], [])
    assert page._current_ref is None
    assert len(page.composite_panel.well_canvas.tracks) > 0

    page.trace_panel.refresh_btn.click()
    assert page._current_ref is None
    assert len(page.composite_panel.well_canvas.tracks) > 0
