import threading
from pathlib import Path

import numpy as np
from geoviz import PreparedPreview, PreviewKind
from geoviz.previews.dat import XYPreviewPayload

from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument, ResourceItem
from paleo_workbench.ui.pages.geoviz_preview_provider import LocalVisualizationProvider
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

    # #842: cold-cache LAS opens resolve on a worker thread; wait for the
    # payload to land instead of asserting mid-load.
    qtbot.waitUntil(
        lambda: len(page.composite_panel.well_canvas.tracks) > 0, timeout=10_000
    )
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


def test_open_ref_engine_preview_prepares_off_the_ui_thread(qtbot, tmp_path: Path):
    path = tmp_path / "wells.dat"
    path.write_text(
        "#WellHead File From SMI\n#Name X Y\nA1 10 20\n",
        encoding="utf-8",
    )
    resource = ResourceItem(
        name="wells.dat",
        path=str(path),
        type="well_head",
        format="dat",
    )
    prepare_started = threading.Event()
    release_prepare = threading.Event()
    prepare_requests = []

    class BlockingEngine:
        def prepare(self, request, _options):
            prepare_requests.append(request)
            prepare_started.set()
            assert release_prepare.wait(timeout=3.0)
            return PreparedPreview(
                kind=PreviewKind.XY_SCATTER,
                title="wells.dat",
                payload=XYPreviewPayload(
                    names=("A1",),
                    x=np.asarray([10.0]),
                    y=np.asarray([20.0]),
                    resource_id=resource.id,
                    record_ids=(0,),
                    source_rows=(3,),
                    source_version="version-1",
                ),
            )

    page = VisualizationPage(
        preview_provider=LocalVisualizationProvider(BlockingEngine())
    )
    qtbot.addWidget(page)
    project = ProjectDocument.new("P")
    project.coordinate.project_crs = "EPSG:3857"
    project.resources.append(resource)
    page.update_state([resource], [], [], project)

    page.open_ref(VizAdapter().ref_from_resource(resource))

    assert prepare_started.wait(timeout=2.0)
    assert page.composite_panel.status_label.text() == "正在加载: wells.dat"

    release_prepare.set()
    qtbot.waitUntil(
        lambda: page.composite_panel.tabs.tabText(
            page.composite_panel.tabs.currentIndex()
        )
        == "引擎预览",
        timeout=5_000,
    )
    assert page.composite_panel.tabs.tabText(
        page.composite_panel.tabs.currentIndex()
    ) == "引擎预览"
    assert prepare_requests[0].comparison_crs == "EPSG:3857"


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

    # #842: cold-cache LAS opens are asynchronous — wait for the tab to land.
    qtbot.waitUntil(
        lambda: page.composite_panel.tabs.tabText(
            page.composite_panel.tabs.currentIndex()
        )
        == "测井",
        timeout=10_000,
    )
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
    # #842: cold-cache LAS opens are asynchronous; wait before refreshing.
    qtbot.waitUntil(
        lambda: page.trace_panel.kind_value.text() == "well_log", timeout=10_000
    )

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
    # #842: cold-cache opens are asynchronous — wait for the payload to land.
    qtbot.waitUntil(
        lambda: len(page.composite_panel.well_canvas.tracks) > 0, timeout=10_000
    )
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

    qtbot.waitUntil(
        lambda: page.composite_panel.well_canvas.tracks == [], timeout=10_000
    )
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
