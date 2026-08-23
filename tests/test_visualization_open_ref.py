import json
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
        page.composite_panel.has_well_log_loaded, timeout=10_000
    )
    assert page.composite_panel.tabs.currentIndex() == 0  # 测井
    assert page.composite_panel.has_well_log_loaded()
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


def test_open_ref_geojson_resource_selects_map_tab(qtbot, tmp_path: Path):
    path = tmp_path / "facies_map.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "name": "H2 相图",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"name": "三角洲", "facies": "三角洲"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
                        },
                    },
                    {
                        "type": "Feature",
                        "properties": {"name": "W1"},
                        "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    res = ResourceItem(
        name="facies_map.geojson",
        path=str(path),
        type="geojson",
        format="geojson",
    )
    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state([res], [], [])
    ref = VizAdapter().ref_from_resource(res)
    assert ref is not None and ref.kind == "map"

    page.open_ref(ref)
    assert page.composite_panel.tabs.tabText(page.composite_panel.tabs.currentIndex()) == "古地理"
    payload_features = page.composite_panel.map_host._current_features
    assert len(payload_features) == 1
    assert payload_features[0]["properties"]["name"] == "三角洲"


def test_open_ref_geojson_missing_file_shows_message(qtbot):
    res = ResourceItem(
        name="gone.geojson",
        path="/no/such/gone.geojson",
        type="geojson",
        format="geojson",
    )
    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state([res], [], [])
    page.open_ref(VizAdapter().ref_from_resource(res))
    assert "不存在" in page.composite_panel.status_label.text()


def _facies_collection(name: str, polygon: list, wells: list | None = None) -> str:
    features = [
        {
            "type": "Feature",
            "properties": {"name": name, "facies": name},
            "geometry": {"type": "Polygon", "coordinates": [polygon]},
        }
    ]
    for well_name, lng, lat in wells or []:
        features.append(
            {
                "type": "Feature",
                "properties": {"name": well_name},
                "geometry": {"type": "Point", "coordinates": [lng, lat]},
            }
        )
    return json.dumps({"type": "FeatureCollection", "name": name, "features": features})


def test_open_ref_geojson_opens_sibling_facies_group(qtbot, tmp_path: Path):
    """打开相图其中一层时自动合并同组 相/亚相/微相 并进入层级显示。"""
    ring = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
    files = {
        "facies": ("h2_相.geojson", _facies_collection("三角洲", ring, [("W1", 1.0, 1.0)])),
        "subfacies": ("h2_亚相.geojson", _facies_collection("三角洲前缘", ring, [("W1", 1.0, 1.0)])),
        "microfacies": ("h2_微相.geojson", _facies_collection("远砂坝", ring)),
    }
    resources = []
    for _role, (fname, content) in files.items():
        path = tmp_path / fname
        path.write_text(content, encoding="utf-8")
        resources.append(
            ResourceItem(name=fname, path=str(path), type="geojson", format="geojson")
        )
    # A different-stem group must not be pulled in.
    other = tmp_path / "other_相.geojson"
    other.write_text(_facies_collection("别的相", ring), encoding="utf-8")
    resources.append(
        ResourceItem(name="other_相.geojson", path=str(other), type="geojson", format="geojson")
    )

    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state(resources, [], [])
    # Open the 亚相 layer — the 相 and 微相 siblings should come along.
    ref = VizAdapter().ref_from_resource(resources[1])
    assert ref is not None and ref.kind == "map"
    page.open_ref(ref)

    panel = page.composite_panel
    assert panel.tabs.tabText(panel.tabs.currentIndex()) == "古地理"
    features = panel.map_host._current_features
    assert len(features) == 3  # 相 + 亚相 + 微相（不含 other_相）
    levels = sorted(f["properties"]["level"] for f in features)
    assert levels == ["facies", "micro_facies", "sub_facies"]
    assert panel.map_host.hierarchy_active is True
    # Level selector shows 自动 + 3 levels.
    assert not panel.level_bar.isHidden()
    assert panel.level_combo.count() == 4
    # Wells deduplicated across layers.
    payload = VizAdapter().resolve(ref, page._project_stub())
    assert len(payload.map_wells) == 1


def test_open_ref_geojson_single_layer_stays_flat(qtbot, tmp_path: Path):
    ring = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    path = tmp_path / "plain_map.geojson"
    path.write_text(_facies_collection("平原相", ring), encoding="utf-8")
    res = ResourceItem(
        name="plain_map.geojson", path=str(path), type="geojson", format="geojson"
    )
    page = VisualizationPage()
    qtbot.addWidget(page)
    page.update_state([res], [], [])
    page.open_ref(VizAdapter().ref_from_resource(res))
    panel = page.composite_panel
    assert panel.tabs.tabText(panel.tabs.currentIndex()) == "古地理"
    assert panel.map_host.hierarchy_active is False
    assert len(panel.map_host._current_features) == 1


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
        page.composite_panel.has_well_log_loaded, timeout=10_000
    )
    assert page.composite_panel.has_well_log_loaded()

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
        lambda: not page.composite_panel.has_well_log_loaded(), timeout=10_000
    )
    assert not page.composite_panel.has_well_log_loaded()
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
    assert page.composite_panel.has_well_log_loaded()

    page.trace_panel.refresh_btn.click()
    assert page._current_ref is None
    assert page.composite_panel.has_well_log_loaded()
