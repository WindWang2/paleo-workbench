from paleo_workbench.project.models import MapReferenceLayer, PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_items import FaciesPolygonItem, WellPointItem
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.map_edit_view import MapEditView
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.mapping.map_edit_api import HAS_CPP, hit_test
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QWheelEvent


def test_has_cpp_is_bool():
    assert isinstance(HAS_CPP, bool)


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


def test_hit_test_python_path():
    """Pure Python hit_test works without map_edit_core (default CI path)."""
    assert isinstance(HAS_CPP, bool)
    assert hit_test([], 0.0, 0.0) is None
    # No coordinates → miss
    assert hit_test([{"id": "f1"}], 1.0, 2.0, tolerance=5.0) is None
    # Point hit
    assert hit_test(
        [{"id": "w1", "coordinates": [1.0, 2.0]}],
        1.0,
        2.0,
        tolerance=0.5,
    ) == "w1"
    # Point miss outside tolerance
    assert hit_test(
        [{"id": "w1", "coordinates": [1.0, 2.0]}],
        5.0,
        5.0,
        tolerance=0.5,
    ) is None
    # Polygon interior
    ring = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    assert hit_test([{"id": "f1", "coordinates": ring}], 5.0, 5.0) == "f1"
    assert hit_test([{"id": "f1", "coordinates": ring}], 50.0, 50.0) is None


def test_scene_hit_test_at(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
        }],
        well_overlays=[{"id": "w1", "name": "A1", "x": 20, "y": 20}],
    )
    scene.load_document(doc)
    assert scene.hit_test_at(5.0, 5.0) == "f1"
    assert scene.hit_test_at(20.0, 20.0, tolerance=0.5) == "w1"
    assert scene.hit_test_at(100.0, 100.0, tolerance=0.1) is None


def test_scene_hit_test_ignores_hidden_layers(qtbot):
    """Hidden layers must not be pickable via geometry hit-test."""
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
        }],
        well_overlays=[{"id": "w1", "name": "A1", "x": 5, "y": 5}],
    )
    scene.load_document(doc)
    # Well sits inside the facies polygon; both layers visible → well wins if
    # it is listed first... order is insertion order; either id is fine.
    # After hiding wells, only facies should hit at the shared location.
    scene.set_layer_visible("well", False)
    assert scene.layer_is_visible("well") is False
    assert scene.hit_test_at(5.0, 5.0, tolerance=0.5) == "f1"
    assert scene.hit_test_at(20.0, 20.0, tolerance=0.5) is None  # no well there anyway

    scene.set_layer_visible("facies", False)
    assert scene.hit_test_at(5.0, 5.0, tolerance=0.5) is None

    scene.set_layer_visible("well", True)
    assert scene.hit_test_at(5.0, 5.0, tolerance=0.5) == "w1"
    # export still includes hidden features
    ids = {r["id"] for r in scene.features_to_records()}
    assert ids == {"f1", "w1"}


def test_select_item_emits_selection_ids(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [10, 0], [10, 10], [0, 0]],
        }],
    )
    scene.load_document(doc)
    received: list[list[str]] = []
    scene.selection_ids_changed.connect(received.append)

    item = scene.item_by_id("f1")
    assert item is not None
    item.setSelected(True)

    assert scene.selected_feature_ids() == ["f1"]
    assert received
    assert received[-1] == ["f1"]


def test_translate_features_and_undo_restores_position(qtbot):
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
    f_item = scene.item_by_id("f1")
    w_item = scene.item_by_id("w1")
    assert f_item is not None and w_item is not None

    f_before = f_item.to_record()["coordinates"][0][:]
    w_before = w_item.to_record()["coordinates"][:]

    scene.translate_features(["f1", "w1"], 1.0, 2.0)
    assert scene.is_dirty() is True
    assert f_item.to_record()["coordinates"][0] == [f_before[0] + 1.0, f_before[1] + 2.0]
    assert w_item.to_record()["coordinates"] == [w_before[0] + 1.0, w_before[1] + 2.0]
    assert scene.command_stack().can_undo() is True

    scene.undo()
    assert f_item.to_record()["coordinates"][0] == f_before
    assert w_item.to_record()["coordinates"] == w_before
    assert scene.command_stack().can_redo() is True

    scene.redo()
    assert f_item.to_record()["coordinates"][0] == [f_before[0] + 1.0, f_before[1] + 2.0]


def test_polygon_hole_is_not_filled_and_move_undo_preserves_all_rings(qtbot):
    coordinates = [
        [[0, 0], [8, 0], [8, 8], [0, 8], [0, 0]],
        [[2, 2], [2, 6], [6, 6], [6, 2], [2, 2]],
    ]
    scene = MapEditScene()
    scene.load_document(
        PaleoMapDocument(
            name="holes",
            linked_target_horizon="H",
            facies_polygons=[
                {
                    "id": "f-hole",
                    "geometry": {"type": "Polygon", "coordinates": coordinates},
                }
            ],
        )
    )
    item = scene.item_by_id("f-hole")

    assert item.contains(QPointF(1.0, 1.0))
    assert not item.contains(QPointF(4.0, 4.0))
    assert scene.hit_test_at(1.0, 1.0) == "f-hole"
    assert scene.hit_test_at(4.0, 4.0) is None
    assert item.to_record()["coordinates"] == coordinates

    scene.translate_features(["f-hole"], 3.0, -1.0)
    moved = item.to_record()["coordinates"]
    assert moved[0][0] == [3.0, -1.0]
    assert moved[1][0] == [5.0, 1.0]

    scene.undo()
    assert item.to_record()["coordinates"] == coordinates


def test_mapping_page_tool_and_undo_wiring(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    docs = [
        PaleoMapDocument(
            name="Active",
            linked_target_horizon="H1",
            facies_polygons=[{
                "id": "f1",
                "name": "A",
                "coordinates": [[0, 0], [4, 0], [4, 4], [0, 0]],
            }],
        ),
    ]
    page.update_state(docs)
    scene = page.edit_view.scene()
    assert isinstance(scene, MapEditScene)

    page.toolbar.set_tool("move")
    assert scene.current_tool() == "move"

    scene.translate_features(["f1"], 2.0, 0.0)
    assert page.is_dirty() is True
    assert page.toolbar.undo_btn.isEnabled() is True

    page.toolbar.undo_btn.click()
    item = scene.item_by_id("f1")
    assert item is not None
    assert item.to_record()["coordinates"][0] == [0.0, 0.0]
    assert page.toolbar.redo_btn.isEnabled() is True

    page.toolbar.redo_btn.click()
    assert item.to_record()["coordinates"][0] == [2.0, 0.0]


def test_edit_history_appended_on_command_push(qtbot):
    """ISS-MAP-02: bound document receives compact edit_history rows."""
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
        }],
    )
    scene.load_document(doc)
    assert doc.edit_history == []
    scene.translate_features(["f1"], 1.0, 0.5)
    assert len(doc.edit_history) == 1
    entry = doc.edit_history[0]
    assert entry["op"] == "MoveCommand"
    assert entry["action"] == "do"
    assert entry["feature_ids"] == ["f1"]
    assert entry["dx"] == 1.0
    assert entry["dy"] == 0.5
    assert "ts" in entry
    scene.undo()
    assert doc.edit_history[-1]["action"] == "undo"
    scene.redo()
    assert doc.edit_history[-1]["action"] == "redo"


def _big_facies_polygons(count: int = 200, vertices: int = 100) -> list[dict]:
    """Generate ``count`` polygons with ``vertices`` points each (20,000 total)."""
    polygons = []
    for i in range(count):
        x0 = float((i % 20) * 100)
        y0 = float((i // 20) * 100)
        ring = [[x0 + j, y0 + (j % 7)] for j in range(vertices - 1)]
        ring.append(list(ring[0]))
        polygons.append({"id": f"f{i}", "name": f"p{i}", "coordinates": ring})
    return polygons


def test_snap_candidate_preparation_once_per_scene_generation(qtbot):
    """200 features / 20,000 vertices: snap candidates (and the grid index) are
    prepared once per scene generation, not once per mouse move."""
    scene = MapEditScene()
    scene.load_document(
        PaleoMapDocument(
            name="big",
            linked_target_horizon="H",
            facies_polygons=_big_facies_polygons(),
        )
    )
    assert scene.feature_count() == 200
    scene.set_snap_enabled(True)
    scene.set_snap_tolerance(1.0)

    snapped = None
    for _ in range(50):  # simulated mouse moves
        snapped = scene._snap_xy(0.4, 0.4)
    assert scene.snap_candidate_build_count() == 1
    assert scene._snap_index is not None  # grid index built with the same generation
    assert snapped == (0.0, 0.0)
    # Far from every vertex: no snap, still no rebuild.
    assert scene._snap_xy(37.5, 41.5) == (37.5, 41.5)
    assert scene.snap_candidate_build_count() == 1

    # A geometry change starts a new generation.
    scene.translate_features(["f0"], 1000.0, 1000.0)
    scene._snap_xy(0.4, 0.4)
    assert scene.snap_candidate_build_count() == 2


def test_reference_snap_points_follow_layer_snap_opt_in(qtbot, tmp_path, monkeypatch):
    """A vector reference point is used for snapping only when its layer opts in."""
    page = MappingPage()
    qtbot.addWidget(page)
    source = tmp_path / "ref.geojson"
    source.write_text("{}")  # must exist so refresh_status keeps "ready"
    opt_in = MapReferenceLayer(
        name="snap-on",
        source_path=str(source),
        source_kind="vector",
        source_crs="EPSG:3857",
        project_crs="EPSG:3857",
        cache_key="k1",
        participates_in_snap=True,
    )
    opt_out = MapReferenceLayer(
        name="snap-off",
        source_path=str(source),
        source_kind="vector",
        source_crs="EPSG:3857",
        project_crs="EPSG:3857",
        cache_key="k2",
        participates_in_snap=False,
    )

    class StubReferenceService:
        def vector_snap_points(self, layer):
            return [(0.0, 0.0)] if layer.name == "snap-on" else [(50.0, 50.0)]

    monkeypatch.setattr(page, "_reference_service", StubReferenceService())
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        reference_layers=[opt_in, opt_out],
    )
    page.update_state([doc])
    scene = page.edit_view.scene()
    assert isinstance(scene, MapEditScene)
    scene.set_snap_enabled(True)
    scene.set_snap_tolerance(0.5)
    # Opt-in layer contributes its snap point...
    assert scene._snap_xy(0.2, 0.1) == (0.0, 0.0)
    # ...the opt-out layer's point is never offered to the scene.
    assert scene._snap_xy(50.1, 50.1) == (50.1, 50.1)


def _wheel_up(view, pos=QPointF(100.0, 100.0)) -> None:
    event = QWheelEvent(
        pos,
        pos,
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    view.wheelEvent(event)


def test_navigation_lod_engages_on_wheel_and_restores_after_idle(qtbot):
    view = MapEditView()
    qtbot.addWidget(view)
    scene = view.scene()
    assert isinstance(scene, MapEditScene)
    scene.load_document(
        PaleoMapDocument(
            name="M",
            linked_target_horizon="H",
            facies_polygons=[{
                "id": "f1",
                "name": "A",
                "coordinates": [[0, 0], [10, 0], [10, 10], [0, 0]],
            }],
        )
    )
    before = scene.item_by_id("f1").to_record()["coordinates"]
    assert view.navigation_lod_active() is False

    _wheel_up(view)
    assert view.navigation_lod_active() is True
    assert scene.navigation_lod() is True
    # LOD is display-only: stored coordinates and the undo stack are untouched.
    assert scene.item_by_id("f1").to_record()["coordinates"] == before
    assert scene.command_stack().can_undo() is False

    qtbot.waitUntil(lambda: not view.navigation_lod_active(), timeout=3000)
    assert scene.navigation_lod() is False
    assert scene.item_by_id("f1").to_record()["coordinates"] == before


def test_navigation_lod_paints_simplified_geometry(qtbot):
    view = MapEditView()
    qtbot.addWidget(view)
    scene = view.scene()
    assert isinstance(scene, MapEditScene)
    scene.load_document(
        PaleoMapDocument(
            name="M",
            linked_target_horizon="H",
            facies_polygons=[{
                "id": "f1",
                "name": "A",
                "coordinates": [[0, 0], [10, 0], [10, 10], [0, 0]],
            }],
            well_overlays=[{"id": "w1", "name": "W", "x": 5, "y": 5}],
        )
    )
    before = scene.item_by_id("f1").to_record()["coordinates"]
    view.resize(320, 240)
    view._begin_navigation_lod()
    assert view.navigation_lod_active() is True
    # Force a repaint through the low-detail draw path (bounding-rect culling
    # plus simplified geometry for path items).
    pixmap = view.grab()
    assert not pixmap.isNull()
    view._end_navigation_lod()
    assert view.navigation_lod_active() is False
    assert scene.item_by_id("f1").to_record()["coordinates"] == before


def test_view_emits_cursor_position_on_mouse_move(qtbot):
    view = MapEditView()
    qtbot.addWidget(view)
    assert view.hasMouseTracking()
    seen: list[tuple] = []
    view.cursor_position_changed.connect(seen.append)
    move = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(10.0, 20.0),
        QPointF(10.0, 20.0),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.mouseMoveEvent(move)
    # Identity transform: viewport coordinates map 1:1 to scene (project CRS).
    assert seen == [(10.0, 20.0)]


def _bowtie_doc():
    return PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "bowtie",
            "name": "A",
            "coordinates": [[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]],
        }],
    )


def test_topology_issues_changed_emitted_on_refresh(qtbot):
    scene = MapEditScene()
    scene.load_document(_bowtie_doc())
    seen: list[list] = []
    scene.topology_issues_changed.connect(seen.append)
    scene.refresh_topology()
    assert len(seen) == 1
    assert any(issue["feature_id"] == "bowtie" for issue in seen[0])
    # Unchanged content must not re-emit.
    scene.refresh_topology()
    assert len(seen) == 1


def test_topology_issues_changed_emits_when_issues_cleared(qtbot):
    scene = MapEditScene()
    scene.load_document(_bowtie_doc())
    scene.refresh_topology()
    seen: list[list] = []
    scene.topology_issues_changed.connect(seen.append)
    item = scene.item_by_id("bowtie")
    square = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    assert scene._push_vertex_edit("bowtie", item.coordinates(), square) is True
    assert seen[-1] == []
