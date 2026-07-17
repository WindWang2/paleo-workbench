import pytest

from paleo_workbench.mapping.map_edit_api import (
    HAS_SHAPELY,
    merge_rings,
    rebuild_topology,
    snap_shared_nodes,
    split_ring_by_line,
)
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene
from paleo_workbench.ui.pages.mapping_page import MappingPage

requires_shapely = pytest.mark.skipif(
    not HAS_SHAPELY,
    reason="shapely required for polygon merge/split",
)


def test_snap_shared_nodes_merges_nearby_vertices():
    a = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]
    b = [[1.05, 0.02], [2.0, 0.0], [2.0, 1.0], [1.05, 0.02]]
    out = snap_shared_nodes([a, b], tol=0.1)
    # Shared near-corner should be identical after snap.
    assert out[0][1] == out[1][0]


def test_rebuild_topology_report():
    rings = [
        [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
        [[2.05, 0], [4, 0], [4, 2], [2.05, 2], [2.05, 0]],
    ]
    report = rebuild_topology(rings, snap_tol=0.1)
    assert "rings" in report
    assert report["changed"] is True
    assert report["rings"][0][1] == report["rings"][1][0]


@requires_shapely
def test_merge_rings_with_shapely():
    a = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    b = [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]
    merged = merge_rings(a, b)
    assert merged is not None
    assert len(merged) >= 4


@requires_shapely
def test_split_ring_by_line_with_shapely():
    ring = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]
    line = [[2, -1], [2, 5]]
    parts = split_ring_by_line(ring, line)
    assert parts is not None
    assert len(parts) == 2


def test_scene_rebuild_topology_forced_snaps_and_is_undoable(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[
            {
                "id": "f1",
                "name": "A",
                "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]],
            },
            {
                "id": "f2",
                "name": "B",
                "coordinates": [[1.05, 0.02], [2, 0], [2, 1], [1.05, 0.02]],
            },
        ],
    )
    scene.load_document(doc)
    scene.set_snap_tolerance(0.1)
    report = scene.rebuild_topology_forced()
    assert report["snapped_count"] >= 1
    assert scene.is_dirty()
    f1 = scene.item_by_id("f1")
    f2 = scene.item_by_id("f2")
    assert f1 is not None and f2 is not None
    # Shared node aligned
    assert f1.coordinates()[1] == f2.coordinates()[0]
    assert scene.undo() is True


@requires_shapely
def test_scene_merge_and_split_facies(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[
            {
                "id": "f1",
                "name": "A",
                "coordinates": [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
            },
            {
                "id": "f2",
                "name": "B",
                "coordinates": [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]],
            },
        ],
        line_features=[
            {
                "id": "ln1",
                "name": "cut",
                "coordinates": [[1.5, -1], [1.5, 5]],
            },
        ],
    )
    scene.load_document(doc)
    a = scene.item_by_id("f1")
    b = scene.item_by_id("f2")
    assert a is not None and b is not None
    a.setSelected(True)
    b.setSelected(True)
    new_id = scene.merge_selected_facies()
    assert new_id is not None
    assert scene.item_by_id("f1") is None
    assert scene.item_by_id("f2") is None
    merged = scene.item_by_id(new_id)
    assert merged is not None

    # Split merged poly by the line feature.
    line = scene.item_by_id("ln1")
    assert line is not None
    merged.setSelected(True)
    line.setSelected(True)
    parts = scene.split_selected_facies_by_line()
    assert parts is not None
    assert len(parts) >= 2
    assert scene.item_by_id(new_id) is None


@requires_shapely
def test_legacy_merge_and_split_reject_complex_geometry_without_data_loss(qtbot):
    hole_geometry = {
        "type": "Polygon",
        "coordinates": [
            [[0, 0], [8, 0], [8, 8], [0, 8], [0, 0]],
            [[2, 2], [2, 6], [6, 6], [6, 2], [2, 2]],
        ],
    }
    multi_geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[10, 0], [14, 0], [14, 4], [10, 0]]],
            [[[20, 0], [24, 0], [24, 4], [20, 0]]],
        ],
    }
    scene = MapEditScene()
    scene.load_document(PaleoMapDocument(
        name="complex",
        linked_target_horizon="H",
        facies_polygons=[
            {"id": "hole", "name": "hole", "geometry": hole_geometry},
            {
                "id": "simple",
                "name": "simple",
                "coordinates": [[7, 0], [10, 0], [10, 3], [7, 0]],
            },
            {"id": "multi", "name": "multi", "geometry": multi_geometry},
        ],
        line_features=[{
            "id": "cut",
            "name": "cut",
            "coordinates": [[12, -1], [12, 5]],
        }],
    ))

    hole = scene.item_by_id("hole")
    simple = scene.item_by_id("simple")
    assert hole is not None and simple is not None
    hole.setSelected(True)
    simple.setSelected(True)
    assert scene.merge_selected_facies() is None
    assert scene.item_by_id("hole").to_record()["geometry"] == hole_geometry
    assert scene.item_by_id("simple") is simple

    scene.clearSelection()
    multi = scene.item_by_id("multi")
    cut = scene.item_by_id("cut")
    assert multi is not None and cut is not None
    multi.setSelected(True)
    cut.setSelected(True)
    assert scene.split_selected_facies_by_line() is None
    assert scene.item_by_id("multi").to_record()["geometry"] == multi_geometry
    assert scene.item_by_id("cut") is cut


def test_mapping_page_topology_toolbar(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [1.0, 0], [1, 1], [0, 0]],
        }, {
            "id": "f2",
            "name": "B",
            "coordinates": [[1.04, 0.01], [2, 0], [2, 1], [1.04, 0.01]],
        }],
    )
    page.update_state([doc])
    assert page.toolbar.topology_btn is not None
    report = page.rebuild_topology()
    assert report["snapped_count"] >= 1
