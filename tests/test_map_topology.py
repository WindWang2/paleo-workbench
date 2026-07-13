from paleo_workbench.mapping.map_edit_api import (
    snap_point,
    validate_adjacency,
    validate_ring,
)
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene


def test_self_intersection_detected():
    # bowtie
    ring = [[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]
    issues = validate_ring(ring)
    assert any(i["code"] == "self_intersection" for i in issues)


def test_scene_exposes_blocking_topology_issue(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M", linked_target_horizon="H",
        facies_polygons=[{"id": "bowtie", "name": "A", "coordinates": [[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]}],
    )
    scene.load_document(doc)
    scene.refresh_topology()
    ok, issues = scene.validate_for_save()
    assert ok is False
    assert issues[0]["feature_id"] == "bowtie"
    assert issues[0]["severity"] == "error"


def test_simple_ring_has_no_issues():
    ring = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    assert validate_ring(ring) == []


def test_snap_to_vertex():
    pts = [(0.0, 0.0), (10.0, 0.0)]
    x, y = snap_point(pts, 0.2, 0.1, tol=0.5)
    assert (x, y) == (0.0, 0.0)


def test_snap_outside_tolerance_keeps_point():
    pts = [(0.0, 0.0), (10.0, 0.0)]
    x, y = snap_point(pts, 2.0, 2.0, tol=0.5)
    assert (x, y) == (2.0, 2.0)


def test_scene_snap_when_enabled(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        well_overlays=[{"id": "w1", "name": "A", "x": 0.0, "y": 0.0}],
    )
    scene.load_document(doc)
    scene.set_snap_enabled(True)
    scene.set_snap_tolerance(0.5)
    sx, sy = scene._snap_xy(0.2, 0.1)
    assert (sx, sy) == (0.0, 0.0)
    scene.set_snap_enabled(False)
    sx2, sy2 = scene._snap_xy(0.2, 0.1)
    assert (sx2, sy2) == (0.2, 0.1)


def test_scene_caches_snap_candidates_until_geometry_changes(qtbot):
    scene = MapEditScene()
    scene.load_document(PaleoMapDocument(name="M", linked_target_horizon="H", well_overlays=[{"id": "w1", "name": "A", "x": 0, "y": 0}]))
    scene._snap_candidates()
    scene._snap_candidates()
    assert scene.snap_candidate_build_count() == 1
    scene.create_feature({"id": "w2", "kind": "well", "name": "B", "coordinates": [2, 2]})
    assert (2.0, 2.0) in scene._snap_candidates()
    assert scene.snap_candidate_build_count() == 2


def test_scene_snaps_to_read_only_reference_points(qtbot):
    scene = MapEditScene()
    scene.set_snap_enabled(True)
    scene.set_reference_snap_points([(10.0, 20.0)])
    assert scene._snap_xy(10.1, 20.1) == (10.0, 20.0)
    assert scene.feature_count() == 0


def test_vertex_edit_sets_topology_status_warning(qtbot):
    scene = MapEditScene()
    # Start with a simple square
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
    item = scene.item_by_id("f1")
    assert item is not None
    assert item.topology_status == "ok"

    # Create a bowtie by moving vertices via coordinate apply path
    bowtie = [[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]
    old = item.coordinates()
    assert scene._push_vertex_edit("f1", old, bowtie) is True
    assert item.topology_status == "warning"
    assert item.to_record()["topology_status"] == "warning"


def test_refresh_topology_before_export(qtbot):
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1",
            "name": "A",
            "coordinates": [[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]],
        }],
    )
    scene.load_document(doc)
    scene.refresh_topology()
    item = scene.item_by_id("f1")
    assert item is not None
    assert item.topology_status == "warning"
    recs = scene.export_features()
    assert recs[0]["topology_status"] == "warning"


def test_validate_adjacency_optional():
    a = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    # Overlapping bbox, no shared vertices
    b = [[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5], [0.5, 0.5]]
    issues = validate_adjacency([a, b], gap_tol=0.1)
    assert any(i["code"] == "adjacency_overlap" for i in issues)
