from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QGraphicsSceneMouseEvent

from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_commands import (
    CreateFeatureCommand,
    EditCommandStack,
    PropertyChangeCommand,
)
from paleo_workbench.ui.pages.map_edit_items import LabelItem, LineItem
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.mapping_page import MappingPage


def _press(scene: MapEditScene, x: float, y: float) -> None:
    event = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMousePress)
    event.setScenePos(QPointF(x, y))
    event.setButton(Qt.MouseButton.LeftButton)
    event.setButtons(Qt.MouseButton.LeftButton)
    scene.mousePressEvent(event)


def _double_click(scene: MapEditScene, x: float, y: float) -> None:
    event = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMouseDoubleClick)
    event.setScenePos(QPointF(x, y))
    event.setButton(Qt.MouseButton.LeftButton)
    event.setButtons(Qt.MouseButton.LeftButton)
    scene.mouseDoubleClickEvent(event)


def test_load_document_creates_line_and_label_items(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        line_features=[{
            "id": "ln1",
            "name": "F1",
            "coordinates": [[0, 0], [3, 3], [6, 1]],
        }],
        label_features=[{
            "id": "lb1",
            "text": "注记A",
            "anchor": [1.0, 2.0],
        }],
    )
    scene.load_document(doc)
    assert scene.feature_count() == 2
    line = scene.item_by_id("ln1")
    label = scene.item_by_id("lb1")
    assert isinstance(line, LineItem)
    assert isinstance(label, LabelItem)
    assert line.kind == "line"
    assert label.kind == "label"
    assert line.to_record()["coordinates"] == [[0.0, 0.0], [3.0, 3.0], [6.0, 1.0]]
    assert label.to_record()["text"] == "注记A"
    assert label.to_record()["coordinates"] == [1.0, 2.0]


def test_line_tool_click_points_double_click_finish(qtbot):
    scene = MapEditScene()
    scene.set_tool("line")
    _press(scene, 0.0, 0.0)
    _press(scene, 2.0, 0.0)
    _press(scene, 2.0, 2.0)
    assert scene.draft_point_count() == 3
    _double_click(scene, 2.0, 2.0)

    assert scene.draft_point_count() == 0
    assert scene.feature_count() == 1
    assert scene.is_dirty() is True
    records = scene.features_to_records()
    assert len(records) == 1
    assert records[0]["kind"] == "line"
    assert len(records[0]["coordinates"]) >= 2
    assert records[0]["coordinates"][0] == [0.0, 0.0]

    # Undo removes the created line
    assert scene.undo() is True
    assert scene.feature_count() == 0


def test_line_tool_enter_finishes_draft(qtbot):
    scene = MapEditScene()
    scene.set_tool("line")
    _press(scene, 1.0, 1.0)
    _press(scene, 4.0, 5.0)
    key = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
    scene.keyPressEvent(key)
    assert scene.feature_count() == 1
    rec = scene.features_to_records()[0]
    assert rec["kind"] == "line"
    assert rec["coordinates"] == [[1.0, 1.0], [4.0, 5.0]]


def test_label_tool_click_places_label(qtbot):
    scene = MapEditScene()
    scene.set_tool("label")
    _press(scene, 7.5, 3.25)
    assert scene.feature_count() == 1
    rec = scene.features_to_records()[0]
    assert rec["kind"] == "label"
    assert rec["coordinates"] == [7.5, 3.25]
    assert rec["text"]
    assert isinstance(scene.item_by_id(rec["id"]), LabelItem)


def test_layer_visibility_for_line_and_label(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        line_features=[{"id": "ln1", "name": "L", "coordinates": [[0, 0], [1, 1]]}],
        label_features=[{"id": "lb1", "text": "T", "anchor": [2, 2]}],
    )
    scene.load_document(doc)
    line = scene.item_by_id("ln1")
    label = scene.item_by_id("lb1")
    assert line is not None and label is not None
    assert line.isVisible() is True
    assert label.isVisible() is True

    scene.set_layer_visible("line", False)
    assert line.isVisible() is False
    assert label.isVisible() is True

    scene.set_layer_visible("label", False)
    assert label.isVisible() is False


def test_property_change_name_and_text_via_command(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        line_features=[{"id": "ln1", "name": "old", "coordinates": [[0, 0], [1, 1]]}],
        label_features=[{"id": "lb1", "text": "oldtext", "anchor": [1, 1]}],
    )
    scene.load_document(doc)

    assert scene.apply_property_change("ln1", "name", "fault-A") is True
    assert scene.item_by_id("ln1").to_record()["name"] == "fault-A"
    assert scene.is_dirty() is True

    assert scene.apply_property_change("lb1", "text", "new-label") is True
    assert scene.item_by_id("lb1").to_record()["text"] == "new-label"

    scene.undo()
    assert scene.item_by_id("lb1").to_record()["text"] == "oldtext"
    scene.undo()
    assert scene.item_by_id("ln1").to_record()["name"] == "old"


def test_create_and_property_commands_unit():
    store: dict[str, dict] = {}

    def add(rec):
        store[rec["id"]] = dict(rec)

    def remove(fid):
        store.pop(fid, None)

    def apply_prop(fid, key, value):
        store[fid][key] = value

    stack = EditCommandStack()
    stack.push(CreateFeatureCommand(
        {"id": "ln1", "kind": "line", "name": "", "coordinates": [[0, 0], [1, 1]]},
        add_feature=add,
        remove_feature=remove,
    ))
    assert "ln1" in store
    stack.undo()
    assert "ln1" not in store
    stack.redo()
    assert "ln1" in store

    stack.push(PropertyChangeCommand("ln1", "name", "", "F1", apply_prop))
    assert store["ln1"]["name"] == "F1"
    stack.undo()
    assert store["ln1"]["name"] == ""


def test_mapping_page_wires_layer_visibility_and_property(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        line_features=[{"id": "ln1", "name": "L", "coordinates": [[0, 0], [2, 2]]}],
        label_features=[{"id": "lb1", "text": "T", "anchor": [1, 1]}],
    )
    page.update_state([doc])
    scene = page.edit_view.scene()
    assert isinstance(scene, MapEditScene)
    assert scene.feature_count() == 2

    # Toggle line visibility via layer tree signal path
    page.layer_tree.layer_visibility_changed.emit("line", False)
    assert scene.item_by_id("ln1").isVisible() is False

    # Property change from attribute table path
    page.attribute_table.property_changed.emit("ln1", "name", "renamed")
    assert scene.item_by_id("ln1").to_record()["name"] == "renamed"
