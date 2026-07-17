from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QGraphicsSceneMouseEvent

from paleo_workbench.mapping import map_edit_api as api
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_commands import EditCommandStack, VertexEditCommand
from paleo_workbench.ui.pages.map_edit_items import VertexHandleItem
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene


def _facies_doc(coords, fid="f1"):
    return PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": fid,
            "name": "A",
            "coordinates": coords,
        }],
    )


def test_set_vertex_updates_ring():
    ring = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]]
    api.set_vertex(ring, 1, 3.0, 0.0)
    assert ring[1] == [3.0, 0.0]


def test_set_vertex_keeps_closed_ring_in_sync():
    ring = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]]
    api.set_vertex(ring, 0, 1.0, 1.0)
    assert ring[0] == [1.0, 1.0]
    assert ring[-1] == [1.0, 1.0]


def test_insert_vertex_into_ring():
    ring = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]]
    api.insert_vertex(ring, 1, 1.0, 0.0)
    assert ring[1] == [1.0, 0.0]
    assert len(ring) == 5
    assert ring[0] == [0.0, 0.0]
    assert ring[2] == [2.0, 0.0]


def test_delete_vertex_respects_minimum_for_closed_ring():
    triangle = [[0.0, 0.0], [2.0, 0.0], [1.0, 2.0], [0.0, 0.0]]
    assert api.delete_vertex(triangle, 1) is False
    assert len(triangle) == 4

    square = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
    assert api.delete_vertex(square, 1) is True
    assert len(square) == 4
    assert square[0] == square[-1]


def test_vertex_edit_command_undo_redo():
    store = {"f1": [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]]}

    def apply(fid, coords):
        store[fid] = [list(p) for p in coords]

    old = [list(p) for p in store["f1"]]
    new = [[0.0, 0.0], [3.0, 0.0], [2.0, 2.0], [0.0, 0.0]]
    stack = EditCommandStack(max_depth=50)
    stack.push(VertexEditCommand("f1", old, new, apply))
    assert store["f1"][1] == [3.0, 0.0]
    stack.undo()
    assert store["f1"][1] == [2.0, 0.0]
    stack.redo()
    assert store["f1"][1] == [3.0, 0.0]


def test_vertex_handles_shown_for_single_facies_when_tool_vertex(qtbot):
    scene = MapEditScene()
    scene.load_document(_facies_doc([[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]))
    item = scene.item_by_id("f1")
    assert item is not None
    item.setSelected(True)

    assert scene.vertex_handle_count() == 0
    scene.set_tool("vertex")
    # Closed ring: 5 points including close → 4 unique handles
    assert scene.vertex_handle_count() == 4
    handles = scene.vertex_handles()
    assert all(isinstance(h, VertexHandleItem) for h in handles)
    assert {h.vertex_index for h in handles} == {0, 1, 2, 3}

    scene.set_tool("select")
    assert scene.vertex_handle_count() == 0


def test_hole_handles_have_ring_addresses_and_closed_edit_is_undoable(qtbot):
    outer = [[0, 0], [8, 0], [8, 8], [0, 8], [0, 0]]
    hole = [[2, 2], [2, 6], [6, 6], [6, 2], [2, 2]]
    scene = MapEditScene()
    scene.load_document(
        PaleoMapDocument(
            name="holes",
            linked_target_horizon="H",
            facies_polygons=[
                {
                    "id": "f-hole",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [outer, hole],
                    },
                }
            ],
        )
    )
    item = scene.item_by_id("f-hole")
    item.setSelected(True)
    scene.set_tool("vertex")

    handles = scene.vertex_handles()
    assert len(handles) == 8
    assert {(h.part_index, h.ring_index) for h in handles} == {(0, 0), (0, 1)}

    assert scene.apply_set_vertex(
        "f-hole", 0, 3.0, 3.0, part_index=0, ring_index=1
    )
    edited = item.to_record()["coordinates"]
    assert edited[0] == outer
    assert edited[1][0] == [3.0, 3.0]
    assert edited[1][-1] == [3.0, 3.0]

    scene.undo()
    assert item.to_record()["coordinates"] == [outer, hole]


def test_vertex_handles_hidden_when_multi_or_none_selected(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[
            {"id": "f1", "name": "A", "coordinates": [[0, 0], [4, 0], [4, 4], [0, 0]]},
            {"id": "f2", "name": "B", "coordinates": [[5, 0], [9, 0], [9, 4], [5, 0]]},
        ],
    )
    scene.load_document(doc)
    scene.set_tool("vertex")
    assert scene.vertex_handle_count() == 0

    scene.item_by_id("f1").setSelected(True)
    scene.item_by_id("f2").setSelected(True)
    assert scene.vertex_handle_count() == 0

    scene.clearSelection()
    scene.item_by_id("f1").setSelected(True)
    assert scene.vertex_handle_count() == 3  # closed triangle: 4 pts, 3 unique


def test_set_vertex_via_scene_pushes_command_and_undo(qtbot):
    scene = MapEditScene()
    scene.load_document(_facies_doc([[0, 0], [10, 0], [10, 10], [0, 0]]))
    item = scene.item_by_id("f1")
    item.setSelected(True)
    scene.set_tool("vertex")

    scene.apply_set_vertex("f1", 1, 12.0, 1.0)
    assert item.to_record()["coordinates"][1] == [12.0, 1.0]
    assert scene.is_dirty() is True
    assert scene.command_stack().can_undo() is True

    scene.undo()
    assert item.to_record()["coordinates"][1] == [10.0, 0.0]


def test_drag_handle_commits_vertex_edit(qtbot):
    scene = MapEditScene()
    scene.load_document(_facies_doc([[0, 0], [10, 0], [10, 10], [0, 0]]))
    item = scene.item_by_id("f1")
    item.setSelected(True)
    scene.set_tool("vertex")

    handles = scene.vertex_handles()
    handle = next(h for h in handles if h.vertex_index == 1)
    start = handle.sceneBoundingRect().center()
    end = QPointF(start.x() + 5.0, start.y() + 2.0)

    press = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMousePress)
    press.setScenePos(start)
    press.setButton(Qt.MouseButton.LeftButton)
    press.setButtons(Qt.MouseButton.LeftButton)
    scene.mousePressEvent(press)

    move = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMouseMove)
    move.setScenePos(end)
    move.setButtons(Qt.MouseButton.LeftButton)
    scene.mouseMoveEvent(move)

    release = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMouseRelease)
    release.setScenePos(end)
    release.setButton(Qt.MouseButton.LeftButton)
    release.setButtons(Qt.MouseButton.NoButton)
    scene.mouseReleaseEvent(release)

    coords = item.to_record()["coordinates"]
    assert coords[1][0] == 15.0
    assert coords[1][1] == 2.0
    assert scene.command_stack().can_undo() is True

    scene.undo()
    coords = item.to_record()["coordinates"]
    assert coords[1] == [10.0, 0.0]


def test_double_click_edge_inserts_vertex(qtbot):
    scene = MapEditScene()
    scene.load_document(_facies_doc([[0, 0], [10, 0], [10, 10], [0, 0]]))
    item = scene.item_by_id("f1")
    item.setSelected(True)
    scene.set_tool("vertex")

    # Midpoint of edge from (0,0) to (10,0)
    pos = QPointF(5.0, 0.0)
    event = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMouseDoubleClick)
    event.setScenePos(pos)
    event.setButton(Qt.MouseButton.LeftButton)
    scene.mouseDoubleClickEvent(event)

    coords = item.to_record()["coordinates"]
    assert len(coords) == 5
    assert coords[1] == [5.0, 0.0]
    assert scene.command_stack().can_undo() is True
    assert scene.vertex_handle_count() == 4  # closed: 5 pts → 4 unique handles


def test_delete_key_removes_vertex_when_allowed(qtbot):
    scene = MapEditScene()
    scene.load_document(
        _facies_doc([[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]])
    )
    item = scene.item_by_id("f1")
    item.setSelected(True)
    scene.set_tool("vertex")

    handles = scene.vertex_handles()
    handle = next(h for h in handles if h.vertex_index == 1)
    handle.setSelected(True)
    scene.set_active_vertex_index(1)

    key = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    scene.keyPressEvent(key)

    coords = item.to_record()["coordinates"]
    assert len(coords) == 4
    assert coords[1] == [10.0, 10.0]
    assert scene.command_stack().can_undo() is True

    # Triangle cannot shrink further
    scene.set_active_vertex_index(1)
    key2 = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
    scene.keyPressEvent(key2)
    assert len(item.to_record()["coordinates"]) == 4


def test_drag_hole_handle_updates_only_addressed_ring_and_undoes(qtbot):
    outer = [[0, 0], [8, 0], [8, 8], [0, 8], [0, 0]]
    hole = [[2, 2], [2, 6], [6, 6], [6, 2], [2, 2]]
    scene = MapEditScene()
    scene.load_document(
        PaleoMapDocument(
            name="holes",
            linked_target_horizon="H",
            facies_polygons=[
                {
                    "id": "f-hole",
                    "geometry": {"type": "Polygon", "coordinates": [outer, hole]},
                }
            ],
        )
    )
    item = scene.item_by_id("f-hole")
    item.setSelected(True)
    scene.set_tool("vertex")
    handle = next(
        h
        for h in scene.vertex_handles()
        if h.part_index == 0 and h.ring_index == 1 and h.vertex_index == 1
    )
    start = handle.sceneBoundingRect().center()
    end = QPointF(start.x() + 1.0, start.y() + 0.5)

    press = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMousePress)
    press.setScenePos(start)
    press.setButton(Qt.MouseButton.LeftButton)
    press.setButtons(Qt.MouseButton.LeftButton)
    scene.mousePressEvent(press)
    move = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMouseMove)
    move.setScenePos(end)
    move.setButtons(Qt.MouseButton.LeftButton)
    scene.mouseMoveEvent(move)
    release = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMouseRelease)
    release.setScenePos(end)
    release.setButton(Qt.MouseButton.LeftButton)
    release.setButtons(Qt.MouseButton.NoButton)
    scene.mouseReleaseEvent(release)

    edited = item.to_record()["coordinates"]
    assert edited[0] == outer
    assert edited[1][1] == [3.0, 6.5]

    scene.undo()
    assert item.to_record()["coordinates"] == [outer, hole]
