from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_items import FaciesPolygonItem, WellPointItem
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.mapping.map_edit_api import hit_test


def test_scene_loads_facies_and_wells(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [10, 0], [10, 10], [0, 0]],
        }],
        well_overlays=[{"id": "w1", "name": "A1", "x": 5, "y": 5}],
    )
    scene.load_document(doc)
    assert scene.feature_count() == 2
    f_item = scene.item_by_id("f1")
    w_item = scene.item_by_id("w1")
    assert f_item is not None
    assert w_item is not None
    assert isinstance(f_item, FaciesPolygonItem)
    assert isinstance(w_item, WellPointItem)
    assert f_item.kind == "facies"
    assert w_item.kind == "well"
    assert f_item.to_record()["id"] == "f1"
    assert w_item.to_record()["coordinates"] == [5.0, 5.0]


def test_feature_count_and_item_by_id(qtbot):
    scene = MapEditScene()
    assert scene.feature_count() == 0
    assert scene.item_by_id("missing") is None

    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]],
        }],
        well_overlays=[{"id": "w1", "name": "W", "x": 0.5, "y": 0.5}],
    )
    scene.load_document(doc)
    assert scene.feature_count() == 2
    assert scene.item_by_id("f1").feature_id == "f1"
    assert scene.item_by_id("w1").feature_id == "w1"

    scene.clear_features()
    assert scene.feature_count() == 0
    assert scene.item_by_id("f1") is None


def test_bad_geometry_skipped_without_crash(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[
            {
                "id": "good",
                "name": "A",
                "coordinates": [[0, 0], [2, 0], [2, 2], [0, 0]],
            },
            {"id": "empty", "name": "E", "coordinates": []},
            {"id": "short", "name": "S", "coordinates": [[0, 0], [1, 1]]},
            {"id": "broken", "name": "B", "coordinates": "not-a-ring"},
        ],
        well_overlays=[
            {"id": "w_good", "name": "OK", "x": 1.0, "y": 1.0},
            {"id": "w_bad", "name": "X", "x": "nope", "y": 1},
        ],
    )
    scene.load_document(doc)
    assert scene.item_by_id("good") is not None
    assert scene.item_by_id("w_good") is not None
    assert scene.item_by_id("empty") is None
    assert scene.item_by_id("short") is None
    assert scene.item_by_id("broken") is None
    assert scene.item_by_id("w_bad") is None
    assert scene.feature_count() == 2


def test_map_edit_view_uses_map_edit_scene(qtbot):
    view = MapEditView()
    qtbot.addWidget(view)
    assert isinstance(view.scene(), MapEditScene)


def test_mapping_page_loads_active_document_into_scene(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    docs = [
        PaleoMapDocument(name="Empty", linked_target_horizon="H0"),
        PaleoMapDocument(
            name="Active",
            linked_target_horizon="H1",
            facies_polygons=[{
                "id": "f9",
                "name": "delta",
                "coordinates": [[0, 0], [3, 0], [3, 3], [0, 0]],
            }],
            well_overlays=[{"id": "w9", "name": "B1", "x": 1.5, "y": 1.5}],
        ),
    ]
    page.update_state(docs)
    scene = page.edit_view.scene()
    assert isinstance(scene, MapEditScene)
    assert scene.feature_count() == 2
    assert scene.item_by_id("f9") is not None
    assert scene.item_by_id("w9") is not None


def test_hit_test_stub_returns_none():
    assert hit_test([], 0.0, 0.0) is None
    assert hit_test([{"id": "f1"}], 1.0, 2.0, tolerance=5.0) is None
