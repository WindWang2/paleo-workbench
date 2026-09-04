"""Regression tests for #389: tool operations must not recompose the document.

Behavioral (counter-based) assertions only: measure-tool drags and selection
clicks never build a render snapshot, while each digitize commit builds exactly
one snapshot and bumps only the edited layer's data revision.
"""

from __future__ import annotations

import pytest

from paleo_workbench.mapping.map_document_snapshot import document_render_snapshot
from paleo_workbench.mapping.map_scene_adapter import document_render_snapshot as adapter_snapshot
from paleo_workbench.mapping.vector_layer import VectorFeature
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.ui.qgis_stack.display_canvas import QgisDisplayCanvas
from PySide6.QtCore import QPoint, Qt


def _document(*, with_facies: bool = True) -> PaleoMapDocument:
    facies = (
        [
            {
                "id": "f1",
                "name": "delta",
                "coordinates": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            }
        ]
        if with_facies
        else []
    )
    return PaleoMapDocument(
        id="map-tool-perf",
        name="Map",
        linked_target_horizon="H1",
        facies_polygons=facies,
    )


def _spy_snapshots(monkeypatch):
    calls = {"n": 0}

    def spy(*args, **kwargs):
        calls["n"] += 1
        return adapter_snapshot(*args, **kwargs)

    monkeypatch.setattr("paleo_workbench.mapping.map_scene_adapter.document_render_snapshot", spy)
    return calls


def _show_page(qtbot, page) -> None:
    qtbot.addWidget(page)
    page.resize(900, 640)
    page.show()
    qtbot.waitUntil(lambda: page.unified_canvas.width() > 100 and page.unified_canvas.height() > 100)


def _native_scene_available() -> bool:
    try:
        from paleo_workbench.viz.native_factor_map import MapScene

        MapScene()
        return True
    except Exception:
        return False


HAS_NATIVE_SCENE = _native_scene_available()


def test_measure_drag_moves_build_zero_render_snapshots(qtbot, monkeypatch) -> None:
    """A measure-tool drag is pure pointer feedback: no document recomposition."""
    page = MappingPage()
    _show_page(qtbot, page)
    page.update_state([_document()], project_crs="EPSG:3857")
    canvas = page.unified_canvas
    center = canvas.map_to_screen((5.0, 5.0)).toPoint()
    calls = _spy_snapshots(monkeypatch)

    page.action_controller.actions["measure_distance"].trigger()
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=center)
    for index in range(1, 21):
        qtbot.mouseMove(canvas, pos=center + QPoint(index, index))
    qtbot.wait(10)

    assert calls["n"] == 0


def test_select_click_updates_selection_without_recomposing(qtbot, monkeypatch) -> None:
    """Selection changes are overlay state: the composition is not rebuilt."""
    page = MappingPage()
    _show_page(qtbot, page)
    if isinstance(page.unified_canvas, QgisDisplayCanvas):
        pytest.skip("QGIS preview canvas is read-only")
    page.update_state([_document()], project_crs="EPSG:3857")
    canvas = page.unified_canvas
    center = canvas.map_to_screen((5.0, 5.0)).toPoint()
    calls = _spy_snapshots(monkeypatch)

    page.action_controller.actions["select"].trigger()
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=center)

    assert page._authoring_document.active_layer.selection == {"f1"}
    assert calls["n"] == 0
    # The attribute selector still reflects the selection (cheap overlay sync).
    assert page.attribute_table.feature_combo.currentData() == "f1"


@pytest.mark.skipif(not HAS_NATIVE_SCENE, reason="native scene modules (layer_model_core/grid_render_core) not installed")
def test_digitize_commits_build_one_snapshot_and_touch_only_the_edited_layer(qtbot, monkeypatch) -> None:
    """Each digitized vertex commits one snapshot and only the layer revision."""
    page = MappingPage()
    _show_page(qtbot, page)
    page.update_state([_document()], project_crs="EPSG:3857")
    canvas = page.unified_canvas
    page.action_controller.actions["toggle_editing"].trigger()
    page.action_controller.actions["add_point"].trigger()
    authoring = page._authoring_document
    assert authoring.active_kind == "well"
    # Count only click-driven snapshots; tool activation already refreshed once.
    calls = _spy_snapshots(monkeypatch)

    scene = page.unified_scene
    updates: dict[str, int] = {}
    original_set = scene.set_vector_features

    def tracked_set(layer_id, features, **kwargs):
        updates[str(layer_id)] = updates.get(str(layer_id), 0) + 1
        return original_set(layer_id, features, **kwargs)

    scene.set_vector_features = tracked_set
    before = authoring.data_revisions()
    points = [canvas.map_to_screen((float(x), float(x))).toPoint() for x in (2.0, 4.0, 6.0)]
    for point in points:
        qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=point)

    after = authoring.data_revisions()
    assert calls["n"] == 3  # one snapshot per committed vertex
    assert after["map-tool-perf:well"] == before["map-tool-perf:well"] + 3
    assert after["map-tool-perf:facies"] == before["map-tool-perf:facies"]
    assert updates == {"map-tool-perf:well": 3}  # sync touched only the edited layer


def test_authoring_data_revisions_ignore_selection_and_stay_distinct_across_commits(qtbot) -> None:
    """Selection never bumps revisions; every edit/commit yields a new revision."""
    page = MappingPage()
    _show_page(qtbot, page)
    page.update_state([_document()], project_crs="EPSG:3857")
    authoring = page._authoring_document

    layer = authoring.layer("facies")
    session = authoring.start_editing("facies")
    before = authoring.data_revisions()

    layer.set_selection(("f1",))
    assert authoring.data_revisions() == before  # selection is not data

    session.add_feature(VectorFeature("f2", {"type": "Point", "coordinates": [1.0, 1.0]}))
    edited = authoring.data_revisions()
    assert edited["map-tool-perf:facies"] > before["map-tool-perf:facies"]

    session.commit_changes()
    committed = authoring.data_revisions()
    assert committed["map-tool-perf:facies"] > edited["map-tool-perf:facies"]
    assert committed["map-tool-perf:well"] == before["map-tool-perf:well"]


def test_document_snapshot_honors_provided_layer_revisions(qtbot) -> None:
    """Provided counters replace full-content hashing; hashing remains the fallback."""
    document = _document()
    records = [{"id": "f1", "kind": "facies", "name": "delta", "coordinates": [[0, 0], [2, 0], [0, 2]]}]
    revisions = {"map-tool-perf:facies": 7, "map-tool-perf:well": 3}

    snapshot = document_render_snapshot(
        document, project_crs="EPSG:3857", records=records, layer_revisions=revisions
    )
    by_id = {layer.id: layer for layer in snapshot.layers}
    assert by_id["map-tool-perf:facies"].data_revision == 7
    assert by_id["map-tool-perf:well"].data_revision == 3

    # Without counters the content hash is deterministic for identical features.
    first = document_render_snapshot(document, project_crs="EPSG:3857", records=records)
    second = document_render_snapshot(document, project_crs="EPSG:3857", records=records)
    assert first.layers[0].data_revision == second.layers[0].data_revision
    assert first.layers[0].data_revision != 7
