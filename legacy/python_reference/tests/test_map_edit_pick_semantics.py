"""Regression tests for #416: legacy sketch hit order and pixel tolerances.

Overlapping features must pick the visible top-most one on every path, and
pick/snap tolerances are screen pixels converted by the current view scale so
degree-CRS documents do not hit within tens of kilometers.
"""

from __future__ import annotations

from paleo_workbench.mapping.feature_query_index import FeatureQueryIndex
from paleo_workbench.mapping.map_interaction import FeatureSpatialIndex
from paleo_workbench.mapping.vector_layer import VectorFeature, VectorLayer
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from PySide6.QtCore import QPointF, Qt


def _overlap_document() -> PaleoMapDocument:
    """Two overlapping facies: B added after A, both z=10, B visible on top."""
    return PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[
            {"id": "A", "name": "A", "coordinates": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]},
            {"id": "B", "name": "B", "coordinates": [[5, 0], [15, 0], [15, 10], [5, 10], [5, 0]]},
        ],
    )


def test_overlapping_facies_pick_the_top_most_on_every_path(qtbot) -> None:
    scene = MapEditScene()
    scene.load_document(_overlap_document())
    overlap = QPointF(7.5, 5.0)

    # Geometry hit path (index + api.hit_test) now returns top-most first.
    assert scene.hit_test_at(overlap.x(), overlap.y()) == "B"
    # Qt item stack path used by move/vertex tools.
    item = scene._feature_item_at(overlap)
    assert item is not None and item.feature_id == "B"
    # Select tool press selects B.
    scene.set_tool("select")
    press = _scene_mouse_event(Qt.MouseButton.LeftButton, overlap)
    scene.mousePressEvent(press)
    assert scene.selected_feature_ids() == ["B"]
    # Move tool press picks B.
    scene.set_tool("move")
    move = scene._feature_item_at(overlap)
    assert move is not None and move.feature_id == "B"
    # Unified canvas index: reverse draw order, top-most found first.
    layer = VectorLayer(
        id="unified:facies",
        name="Facies",
        features=[
            VectorFeature("A", {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}),
            VectorFeature("B", {"type": "Polygon", "coordinates": [[[5, 0], [15, 0], [15, 10], [5, 10], [5, 0]]]}),
        ],
    )
    index = FeatureSpatialIndex(layer)
    assert index.identify((7.5, 5.0), tolerance=0.0) == "B"


def test_feature_query_index_returns_top_most_first() -> None:
    index = FeatureQueryIndex()

    class Item:
        def __init__(self, feature_id, kind, coordinates):
            self.feature_id = feature_id
            self.kind = kind
            self.coordinates = coordinates

        def to_record(self):
            return {"id": self.feature_id, "kind": self.kind, "coordinates": self.coordinates}

    index.rebuild(
        [
            Item("A", "facies", [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]),
            Item("B", "facies", [[5, 0], [15, 0], [15, 10], [5, 10], [5, 0]]),
        ],
        record_for_item=lambda item: item.to_record(),
    )
    records = index.query(7.5, 5.0, 0.0, visible=lambda _kind: True)
    assert [record["id"] for record in records] == ["B", "A"]


def _degree_document() -> PaleoMapDocument:
    """A 0.04-degree polygon near the demo compiler origin (114, 22.5)."""
    x, y = 114.0, 22.5
    return PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[
            {
                "id": "f1",
                "name": "A",
                "coordinates": [[x, y], [x + 0.04, y], [x + 0.04, y + 0.04], [x, y + 0.04], [x, y]],
            }
        ],
    )


def _scene_with_zoom(zoom: float, qtbot) -> tuple[MapEditScene, MapEditView]:
    scene = MapEditScene()
    view = MapEditView()
    qtbot.addWidget(view)
    view.setScene(scene)
    view.resetTransform()
    view.scale(zoom, zoom)
    return scene, view


def test_pick_tolerance_is_pixels_converted_by_view_scale(qtbot) -> None:
    """A fixed world offset must hit when below 8 px and miss above it."""
    scene, view = _scene_with_zoom(800.0, qtbot)  # 8 px = 0.01 deg
    scene.load_document(_degree_document())
    edge_x = 114.0 + 0.04
    near_y = 22.5 + 0.02

    assert scene._units_per_pixel() == 1.0 / 800.0
    # The select tool picks with the scene snap tolerance (8 px by default).
    assert scene.hit_test_at(edge_x + 0.005, near_y, tolerance=8.0) == "f1"
    # 0.02 deg is 16 px: beyond the tolerance -> miss.
    assert scene.hit_test_at(edge_x + 0.02, near_y, tolerance=8.0) is None

    # Ten times deeper zoom: 8 px is now 0.001 deg, so the same 0.005 deg
    # offset is 40 px and must no longer hit.
    view.resetTransform()
    view.scale(8000.0, 8000.0)
    assert scene.hit_test_at(edge_x + 0.005, near_y, tolerance=8.0) is None
    # 0.0005 deg is 4 px at this zoom -> hits again.
    assert scene.hit_test_at(edge_x + 0.0005, near_y, tolerance=8.0) == "f1"


def test_snap_distance_is_pixels_converted_by_view_scale(qtbot) -> None:
    scene, view = _scene_with_zoom(800.0, qtbot)
    scene.load_document(
        PaleoMapDocument(
            name="M",
            linked_target_horizon="H",
            well_overlays=[{"id": "w1", "name": "A", "x": 0.0, "y": 0.0}],
        )
    )
    scene.set_snap_enabled(True)

    # 0.005 is 4 px at 800 px/unit: snaps to the well vertex.
    assert scene._snap_xy(0.005, 0.0) == (0.0, 0.0)
    # 0.02 is 16 px: beyond the 8 px tolerance.
    assert scene._snap_xy(0.02, 0.0) == (0.02, 0.0)

    # Deeper zoom makes the same world offsets behave differently.
    view.resetTransform()
    view.scale(8000.0, 8000.0)
    assert scene._snap_xy(0.005, 0.0) == (0.005, 0.0)  # now 40 px
    assert scene._snap_xy(0.0005, 0.0) == (0.0, 0.0)  # now 4 px


def test_vertex_handle_pick_radius_is_pixels(qtbot) -> None:
    scene, view = _scene_with_zoom(8000.0, qtbot)  # 4 px = 0.0005 deg
    scene.load_document(
        PaleoMapDocument(
            name="M",
            linked_target_horizon="H",
            facies_polygons=[
                {"id": "f1", "name": "A", "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]]}
            ],
        )
    )
    scene.item_by_id("f1").setSelected(True)
    scene.set_tool("vertex")
    assert scene.vertex_handle_count() == 3

    # 0.0004 deg from the (0,0) handle is 3.2 px: within the 4 px radius.
    assert scene._handle_at(QPointF(0.0004, 0.0)) is not None
    # 0.01 deg is 80 px: far outside.
    assert scene._handle_at(QPointF(0.01, 0.0)) is None


def _scene_mouse_event(button, pos: QPointF):
    from PySide6.QtWidgets import QGraphicsSceneMouseEvent

    event = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMousePress)
    event.setScenePos(pos)
    event.setButton(button)
    event.setButtons(button)
    return event
