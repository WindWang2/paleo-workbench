"""Unit tests for FeatureEditor deep module (Issue #35)."""
from __future__ import annotations

import pytest

from paleo_workbench.mapping.feature_editor import FeatureEditor, TopologyError


@pytest.fixture
def sample_feature_collection():
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "poly1",
                "properties": {"name": "Delta Front"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]
                    ],
                },
            },
            {
                "type": "Feature",
                "id": "poly2",
                "properties": {"name": "Prodelta"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[10.0, 0.0], [20.0, 0.0], [20.0, 10.0], [10.0, 10.0], [10.0, 0.0]]
                    ],
                },
            },
        ],
    }


def test_feature_editor_load_layer(sample_feature_collection):
    editor = FeatureEditor()
    editor.load_layer(sample_feature_collection)
    assert len(editor.features) == 2
    assert "poly1" in editor.features
    assert "poly2" in editor.features


def test_feature_editor_select_at(sample_feature_collection):
    editor = FeatureEditor()
    editor.load_layer(sample_feature_collection)

    # Click near vertex (10.0, 10.0)
    selection = editor.select_at(10.1, 9.9, tolerance=5.0)
    assert selection is not None
    assert selection["feature_id"] in {"poly1", "poly2"}
    assert selection["vertex_index"] is not None

    # Click far away
    no_selection = editor.select_at(100.0, 100.0, tolerance=5.0)
    assert no_selection is None


def test_feature_editor_move_vertex_valid(sample_feature_collection):
    editor = FeatureEditor()
    editor.load_layer(sample_feature_collection)
    editor.select_at(0.0, 0.0, tolerance=5.0)

    # Move vertex (0, 0) to (-2.0, -2.0)
    success = editor.move_selected_vertex(-2.0, -2.0)
    assert success is True
    feat = editor.features["poly1"]
    ring = feat["geometry"]["coordinates"][0]
    # Verify ring closure: first and last vertices are both (-2.0, -2.0)
    assert ring[0] == [-2.0, -2.0]
    assert ring[-1] == [-2.0, -2.0]


def test_feature_editor_move_vertex_topology_error(sample_feature_collection):
    editor = FeatureEditor()
    editor.load_layer(sample_feature_collection)
    editor.select_at(0.0, 0.0, tolerance=5.0)

    # Move vertex to create self-intersecting invalid polygon (e.g. 15.0, 5.0)
    with pytest.raises(TopologyError):
        editor.move_selected_vertex(15.0, 5.0)

    # Verify state rolled back automatically to (0.0, 0.0)
    feat = editor.features["poly1"]
    ring = feat["geometry"]["coordinates"][0]
    assert ring[0] == [0.0, 0.0]
    assert ring[-1] == [0.0, 0.0]


def test_feature_editor_coincident_shared_nodes_sync(sample_feature_collection):
    editor = FeatureEditor()
    editor.load_layer(sample_feature_collection)

    # poly1 and poly2 share vertex (10.0, 0.0) and (10.0, 10.0)
    # Select vertex at (10.0, 0.0) on poly1
    selection = editor.select_at(10.0, 0.0, tolerance=1.0)
    assert selection is not None

    # Move shared vertex (10.0, 0.0) to (12.0, -1.0)
    success = editor.move_selected_vertex(12.0, -1.0)
    assert success is True

    # Verify poly1 updated
    ring1 = editor.features["poly1"]["geometry"]["coordinates"][0]
    assert [12.0, -1.0] in ring1

    # Verify poly2 updated simultaneously (shared node sync)
    ring2 = editor.features["poly2"]["geometry"]["coordinates"][0]
    assert [12.0, -1.0] in ring2


def test_feature_editor_add_and_delete_vertex(sample_feature_collection):
    editor = FeatureEditor()
    editor.load_layer(sample_feature_collection)

    # Add vertex (5.0, -2.0) to poly1 ring
    success = editor.add_vertex("poly1", 5.0, -2.0, insert_index=1)
    assert success is True
    ring = editor.features["poly1"]["geometry"]["coordinates"][0]
    assert ring[1] == [5.0, -2.0]
    assert len(ring) == 6

    # Delete vertex at index 1
    del_success = editor.delete_vertex("poly1", 1)
    assert del_success is True
    ring_after = editor.features["poly1"]["geometry"]["coordinates"][0]
    assert len(ring_after) == 5

    # Attempting to delete down to < 3 unique vertices raises TopologyError
    editor.delete_vertex("poly1", 1)  # now 4 points (3 unique)
    with pytest.raises(TopologyError):
        editor.delete_vertex("poly1", 1)  # would become < 3 unique vertices


def test_feature_editor_transaction_commit_undo_redo(sample_feature_collection):
    editor = FeatureEditor()
    editor.load_layer(sample_feature_collection)
    assert editor.can_undo is False
    assert editor.can_redo is False

    # Perform move and commit transaction
    editor.select_at(0.0, 0.0, tolerance=5.0)
    editor.move_selected_vertex(-1.0, -1.0)
    editor.commit()

    assert editor.can_undo is True
    ring_modified = editor.features["poly1"]["geometry"]["coordinates"][0]
    assert ring_modified[0] == [-1.0, -1.0]

    # Test Undo
    editor.undo()
    assert editor.can_redo is True
    ring_restored = editor.features["poly1"]["geometry"]["coordinates"][0]
    assert ring_restored[0] == [0.0, 0.0]

    # Test Redo
    editor.redo()
    ring_redo = editor.features["poly1"]["geometry"]["coordinates"][0]
    assert ring_redo[0] == [-1.0, -1.0]




