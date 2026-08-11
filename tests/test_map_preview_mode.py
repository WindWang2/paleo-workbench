from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_canvas_panel import MapCanvasPanel
from paleo_workbench.ui.pages.map_chrome_panel import MapChromePanel
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar
from paleo_workbench.viz.mapping_helpers import (
    facies_to_geojson,
    preview_payload_from_document,
    preview_payload_from_features,
    well_to_lnglat,
)
from paleo_workbench.ui.pages.mapping_page import MappingPage


def test_facies_to_geojson_from_editor_ring():
    feat = facies_to_geojson({
        "id": "f1",
        "name": "三角洲",
        "coordinates": [[0, 0], [2, 0], [2, 2], [0, 2]],
    })
    assert feat is not None
    assert feat["type"] == "Feature"
    assert feat["properties"]["name"] == "三角洲"
    ring = feat["geometry"]["coordinates"][0]
    assert ring[0] == ring[-1]
    assert len(ring) == 5


def test_facies_to_geojson_passthrough_feature():
    raw = {
        "type": "Feature",
        "properties": {"name": "A", "facies": "A"},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[10, 20], [11, 20], [11, 21], [10, 20]]],
        },
    }
    feat = facies_to_geojson(raw)
    assert feat["geometry"] == raw["geometry"]
    assert feat["properties"]["facies"] == "A"


def test_facies_to_geojson_prefers_complete_editor_geometry():
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [8, 0], [8, 8], [0, 8], [0, 0]],
            [[2, 2], [2, 6], [6, 6], [6, 2], [2, 2]],
        ],
    }
    multipolygon = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[10, 0], [12, 0], [12, 2], [10, 0]]],
            [[[20, 0], [22, 0], [22, 2], [20, 0]]],
        ],
    }

    for geometry in (polygon, multipolygon):
        feat = facies_to_geojson({
            "id": "complex",
            "kind": "facies",
            "name": "复合相带",
            # Compatibility field is deliberately incomplete.
            "coordinates": geometry["coordinates"][0],
            "geometry": geometry,
        })

        assert feat is not None
        assert feat["geometry"] == geometry
        assert feat["properties"] == {"name": "复合相带", "facies": "复合相带"}


def test_well_to_lnglat_from_xy_and_coordinates():
    assert well_to_lnglat({"name": "W1", "x": 1.0, "y": 2.0}) == {
        "name": "W1", "lng": 1.0, "lat": 2.0,
    }
    assert well_to_lnglat({"name": "W2", "coordinates": [3.0, 4.0]}) == {
        "name": "W2", "lng": 3.0, "lat": 4.0,
    }
    assert well_to_lnglat({"name": "W3", "lng": 5.0, "lat": 6.0}) == {
        "name": "W3", "lng": 5.0, "lat": 6.0,
    }


def test_preview_payload_from_document_and_features():
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H1",
        facies_polygons=[{
            "id": "f1",
            "name": "相A",
            "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]],
        }],
        well_overlays=[{"name": "HZ", "x": 0.5, "y": 0.5}],
    )
    features, wells, period = preview_payload_from_document(doc)
    assert period == "H1"
    assert len(features) == 1
    assert features[0]["properties"]["name"] == "相A"
    assert wells == [{"name": "HZ", "lng": 0.5, "lat": 0.5}]

    features2, wells2, period2 = preview_payload_from_features(
        [
            {
                "id": "f1",
                "kind": "facies",
                "name": "相B",
                "coordinates": [[0, 0], [2, 0], [2, 2], [0, 0]],
            },
            {"id": "w1", "kind": "well", "name": "W", "coordinates": [1, 1]},
            {"id": "ln", "kind": "line", "name": "L", "coordinates": [[0, 0], [1, 1]]},
        ],
        period_name="H2",
    )
    assert period2 == "H2"
    assert len(features2) == 1
    assert features2[0]["properties"]["name"] == "相B"
    assert wells2 == [{"name": "W", "lng": 1.0, "lat": 1.0}]


def test_toolbar_preview_signal(qtbot):
    bar = MapEditToolbar()
    qtbot.addWidget(bar)
    flags: list[bool] = []
    bar.preview_toggled.connect(flags.append)

    assert bar.preview_btn is not None
    assert bar.is_preview_mode() is False
    bar.preview_btn.click()
    assert flags == [True]
    bar.set_preview_mode(True)
    assert bar.select_btn.isEnabled() is False
    assert bar.snap_btn.isEnabled() is False
    bar.set_preview_mode(False)
    assert bar.select_btn.isEnabled() is True


def test_mapping_page_preview_mode_switch(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    doc = PaleoMapDocument(
        name="Delta",
        linked_target_horizon="ZJ2",
        facies_polygons=[{
            "id": "f1",
            "name": "三角洲",
            "coordinates": [[110, 20], [120, 20], [120, 30], [110, 30], [110, 20]],
        }],
        well_overlays=[{"name": "HZ26", "x": 115.0, "y": 25.0}],
        map_chrome={"title": "Delta 图", "elements": ["图例", "比例尺"]},
    )
    page.update_state([doc])

    assert page.is_preview_mode() is False
    # The unified QGIS/fallback canvas is now the normal authoring surface;
    # preview mode changes decorations/workbench state rather than swapping back
    # to the legacy QGraphics editor.
    assert page.center_stack.currentIndex() == 1
    assert page.bottom_workbench.isHidden() is False
    assert isinstance(page.canvas_panel, MapCanvasPanel)
    assert isinstance(page.chrome_panel, MapChromePanel)

    page.set_preview_mode(True)
    assert page.is_preview_mode() is True
    assert page.center_stack.currentIndex() == 1
    assert page.bottom_workbench.isHidden() is True
    assert page.toolbar.preview_btn.isChecked() is True
    assert page.toolbar.select_btn.isEnabled() is False

    assert page.canvas_panel.empty_label.isHidden() is True
    loaded = page.canvas_panel.canvas._loaded_features
    assert len(loaded) == 1
    assert loaded[0]["properties"]["name"] == "三角洲"
    assert page.canvas_panel.canvas._period_name == "ZJ2"
    assert page.canvas_panel.canvas._wells_data == [
        {"name": "HZ26", "lng": 115.0, "lat": 25.0},
    ]
    assert page.chrome_panel.title_value.text() == "Delta 图"
    assert "图例" in page.chrome_panel.elements_value.text()

    ctx = page.mapping_context()
    assert ctx["preview"] is True
    assert ctx["map_name"] == "Delta"

    page.set_preview_mode(False)
    assert page.center_stack.currentIndex() == 1
    assert page.bottom_workbench.isHidden() is False
    assert page.toolbar.select_btn.isEnabled() is True


def test_preview_shows_unsaved_scene_edits(qtbot):
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [5, 0], [5, 5], [0, 0]],
        }],
    )
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([doc])
    page.edit_view.scene().translate_features(["f1"], 10.0, 0.0)
    assert page.is_dirty()

    page.set_preview_mode(True)
    ring = page.canvas_panel.canvas._loaded_features[0]["geometry"]["coordinates"][0]
    # First vertex shifted by +10 on x
    assert ring[0][0] == 10.0
    # Document still holds original until save
    assert doc.facies_polygons[0]["coordinates"][0][0] == 0


def test_preview_btn_toggles_page_mode(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([PaleoMapDocument(name="M", linked_target_horizon="H")])
    page.toolbar.preview_btn.click()
    assert page.is_preview_mode() is True
    page.toolbar.preview_btn.click()
    assert page.is_preview_mode() is False
