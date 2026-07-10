from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_canvas_panel import MapCanvasPanel


SAMPLE_FEATURE = {
    "type": "Feature",
    "properties": {"name": "三角洲前缘", "facies": "三角洲"},
    "geometry": {
        "type": "Polygon",
        "coordinates": [[
            [110.0, 20.0], [120.0, 20.0], [120.0, 30.0],
            [110.0, 30.0], [110.0, 20.0],
        ]],
    },
}


def test_map_canvas_panel_empty_state(qtbot):
    panel = MapCanvasPanel()
    qtbot.addWidget(panel)

    panel.update_state(None)

    assert panel.objectName() == "MapCanvasPanel"
    assert panel.empty_label.text() == "未选择古地理图"
    assert panel.canvas._loaded_features == []


def test_map_canvas_panel_loads_document_features(qtbot):
    panel = MapCanvasPanel()
    qtbot.addWidget(panel)
    doc = PaleoMapDocument(
        name="ZJ2 Map",
        linked_target_horizon="ZJ2",
        facies_polygons=[SAMPLE_FEATURE],
        well_overlays=[{"name": "HZ26-7", "lng": 115.0, "lat": 25.0}],
    )

    panel.update_state(doc)

    assert panel.empty_label.isHidden()
    assert len(panel.canvas._loaded_features) == 1
    assert panel.canvas._loaded_features[0]["properties"]["name"] == "三角洲前缘"
    assert panel.canvas._period_name == "ZJ2"
    assert panel.canvas._wells_data == [{"name": "HZ26-7", "lng": 115.0, "lat": 25.0}]


def test_map_canvas_panel_load_preview_direct(qtbot):
    panel = MapCanvasPanel()
    qtbot.addWidget(panel)
    panel.load_preview(
        [SAMPLE_FEATURE],
        wells=[{"name": "W", "lng": 1.0, "lat": 2.0}],
        period_name="P1",
    )
    assert panel.empty_label.isHidden()
    assert panel.canvas._loaded_features == [SAMPLE_FEATURE]
    assert panel.canvas._period_name == "P1"
    assert panel.canvas._wells_data == [{"name": "W", "lng": 1.0, "lat": 2.0}]
