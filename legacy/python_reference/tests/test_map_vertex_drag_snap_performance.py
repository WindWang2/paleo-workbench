"""Regression tests for #417: vertex drags must not rebuild scene snap caches.

Structural assertions only: a drag session with snapping enabled must reuse
the snap-candidate cache and the spatial index across all mouse moves, and
rebuild them exactly once when the vertex edit is committed.
"""

from __future__ import annotations

import pytest

from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QGraphicsSceneMouseEvent


def _big_facies_polygons(count: int) -> list[dict]:
    polygons = []
    for i in range(count):
        x0 = float((i % 20) * 100)
        y0 = float((i // 20) * 100)
        ring = [[x0, y0], [x0 + 10, y0], [x0 + 10, y0 + 10], [x0, y0 + 10], [x0, y0]]
        polygons.append({"id": f"f{i}", "name": f"p{i}", "coordinates": ring})
    return polygons


def _drag_vertex(scene, handle, steps: int = 30, *, dx: float, dy: float) -> None:
    """Press the handle, move ``steps`` times, release (the real event path)."""
    start = handle.sceneBoundingRect().center()
    press = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMousePress)
    press.setScenePos(start)
    press.setButton(Qt.MouseButton.LeftButton)
    press.setButtons(Qt.MouseButton.LeftButton)
    scene.mousePressEvent(press)

    for index in range(1, steps + 1):
        move = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMouseMove)
        move.setScenePos(QPointF(start.x() + dx * index / steps, start.y() + dy * index / steps))
        move.setButtons(Qt.MouseButton.LeftButton)
        scene.mouseMoveEvent(move)

    release = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMouseRelease)
    release.setScenePos(QPointF(start.x() + dx, start.y() + dy))
    release.setButton(Qt.MouseButton.LeftButton)
    release.setButtons(Qt.MouseButton.NoButton)
    scene.mouseReleaseEvent(release)


@pytest.mark.parametrize("count", [100, 2_000])
def test_vertex_drag_session_reuses_snap_candidates_and_index(qtbot, count: int) -> None:
    """N moves rebuild nothing; the commit rebuilds each cache exactly once."""
    scene = MapEditScene()
    scene.load_document(
        PaleoMapDocument(
            name="big",
            linked_target_horizon="H",
            facies_polygons=_big_facies_polygons(count),
        )
    )
    scene.set_snap_enabled(True)
    scene.set_snap_tolerance(1.0)
    item = scene.item_by_id("f0")
    item.setSelected(True)
    scene.set_tool("vertex")

    # Warm the snap-candidate cache and the spatial index.
    scene._snap_xy(0.4, 0.4)
    builds_before = scene.snap_candidate_build_count()
    records_before = scene.hit_query_diagnostics()["record_build_count"]
    assert builds_before == 1

    handle = next(h for h in scene.vertex_handles() if h.vertex_index == 1)
    _drag_vertex(scene, handle, steps=30, dx=50.0, dy=50.0)

    # The commit invalidated the candidate cache; the next snap builds exactly
    # one fresh generation (one per drag session, never one per mouse move).
    scene._snap_xy(0.4, 0.4)
    assert scene.snap_candidate_build_count() == builds_before + 1
    # The spatial index serialized only on commit (restore + command apply),
    # never once per move.
    assert scene.hit_query_diagnostics()["record_build_count"] - records_before <= 2
    # The dragged vertex landed at the release position.
    assert item.to_record()["coordinates"][1] == [60.0, 50.0]


def test_vertex_drag_cancel_restores_cache_consistency(qtbot) -> None:
    """Cancelling a drag restores geometry and invalidates caches once."""
    scene = MapEditScene()
    scene.load_document(
        PaleoMapDocument(
            name="M",
            linked_target_horizon="H",
            facies_polygons=[{"id": "f0", "name": "A", "coordinates": [[0, 0], [10, 0], [10, 10], [0, 0]]}],
        )
    )
    scene.set_snap_enabled(True)
    item = scene.item_by_id("f0")
    item.setSelected(True)
    scene.set_tool("vertex")

    handle = next(h for h in scene.vertex_handles() if h.vertex_index == 1)
    start = handle.sceneBoundingRect().center()
    press = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMousePress)
    press.setScenePos(start)
    press.setButton(Qt.MouseButton.LeftButton)
    press.setButtons(Qt.MouseButton.LeftButton)
    scene.mousePressEvent(press)
    for index in range(1, 11):
        move = QGraphicsSceneMouseEvent(QGraphicsSceneMouseEvent.Type.GraphicsSceneMouseMove)
        move.setScenePos(QPointF(start.x() + 3.0 * index, start.y()))
        move.setButtons(Qt.MouseButton.LeftButton)
        scene.mouseMoveEvent(move)

    builds_after_moves = scene.snap_candidate_build_count()
    scene._cancel_vertex_drag()
    # Geometry restored after cancel; the commit path never ran.
    assert item.to_record()["coordinates"][1] == [10.0, 0.0]
    # The next snap builds one fresh generation (cancel invalidated once).
    scene._snap_xy(0.4, 0.4)
    assert scene.snap_candidate_build_count() == builds_after_moves + 1
