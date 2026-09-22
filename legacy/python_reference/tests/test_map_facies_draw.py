"""Facies polygon draft tool tests."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QGraphicsSceneMouseEvent

from paleo_workbench.ui.pages.map_edit_items import FaciesPolygonItem, LineItem
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar, TOOL_IDS
from paleo_workbench.project.models import PaleoMapDocument


def _press(scene: MapEditScene, x: float, y: float) -> None:
    event = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMousePress)
    event.setScenePos(QPointF(x, y))
    event.setButton(Qt.MouseButton.LeftButton)
    event.setButtons(Qt.MouseButton.LeftButton)
    scene.mousePressEvent(event)


def _double_click(scene: MapEditScene, x: float, y: float) -> None:
    event = QGraphicsSceneMouseEvent(
        QGraphicsSceneMouseEvent.Type.GraphicsSceneMouseDoubleClick
    )
    event.setScenePos(QPointF(x, y))
    event.setButton(Qt.MouseButton.LeftButton)
    event.setButtons(Qt.MouseButton.LeftButton)
    scene.mouseDoubleClickEvent(event)


def test_toolbar_includes_facies_tool(qtbot):
    bar = MapEditToolbar()
    qtbot.addWidget(bar)
    assert "facies" in TOOL_IDS
    assert bar.facies_btn is not None
    bar.facies_btn.click()
    assert bar.current_tool() == "facies"


def test_facies_tool_draws_closed_polygon(qtbot):
    scene = MapEditScene()
    scene.set_tool("facies")
    _press(scene, 0.0, 0.0)
    _press(scene, 4.0, 0.0)
    _press(scene, 4.0, 3.0)
    assert scene.draft_point_count() == 3
    assert scene.draft_kind() == "facies"
    _double_click(scene, 4.0, 3.0)

    assert scene.draft_point_count() == 0
    assert scene.feature_count() == 1
    rec = scene.features_to_records()[0]
    assert rec["kind"] == "facies"
    assert rec["name"] == "新相带"
    ring = rec["coordinates"]
    assert len(ring) >= 4  # closed
    assert ring[0] == ring[-1]
    assert isinstance(scene.item_by_id(rec["id"]), FaciesPolygonItem)
    assert scene.is_dirty() is True
    assert scene.undo() is True
    assert scene.feature_count() == 0


def test_facies_tool_enter_finishes(qtbot):
    scene = MapEditScene()
    scene.set_tool("facies")
    _press(scene, 1.0, 1.0)
    _press(scene, 2.0, 1.0)
    _press(scene, 2.0, 2.0)
    key = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    scene.keyPressEvent(key)
    assert scene.feature_count() == 1
    assert scene.features_to_records()[0]["kind"] == "facies"


def test_facies_tool_requires_three_points(qtbot):
    scene = MapEditScene()
    scene.set_tool("facies")
    _press(scene, 0.0, 0.0)
    _press(scene, 1.0, 0.0)
    assert scene.finish_facies_draft() is None
    assert scene.feature_count() == 0


def test_line_vertex_handles_and_edit(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        line_features=[{
            "id": "ln1",
            "name": "F1",
            "coordinates": [[0.0, 0.0], [5.0, 0.0], [5.0, 5.0]],
        }],
    )
    scene.load_document(doc)
    item = scene.item_by_id("ln1")
    assert isinstance(item, LineItem)
    item.setSelected(True)
    scene.set_tool("vertex")
    # Three open vertices → three handles
    assert len(scene._vertex_handles) == 3
    assert scene.apply_set_vertex("ln1", 1, 6.0, 0.0) is True
    coords = scene.item_by_id("ln1").coordinates()
    assert coords[1] == [6.0, 0.0]
    assert scene.undo() is True
    assert scene.item_by_id("ln1").coordinates()[1] == [5.0, 0.0]


def test_select_tool_uses_hit_test(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        well_overlays=[{"id": "w1", "name": "A1", "x": 2.0, "y": 3.0}],
    )
    scene.load_document(doc)
    scene.set_tool("select")
    _press(scene, 2.0, 3.0)
    assert scene.selected_feature_ids() == ["w1"]
