"""Authoritative vector edit-buffer and reversible command contracts."""

from __future__ import annotations

from paleo_workbench.mapping.vector_layer import (
    AddFeatureCommand,
    ChangeAttributeCommand,
    DeleteFeatureCommand,
    MoveFeatureCommand,
    SetGeometryCommand,
    SetVertexCommand,
    VectorEditSession,
    VectorFeature,
    VectorLayer,
)


def _layer() -> VectorLayer:
    return VectorLayer(
        id="facies",
        name="Facies",
        crs="EPSG:3857",
        source_ref="catalog:raw:facies-v1",
        features=[
            VectorFeature(
                "f1",
                {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [4, 0], [4, 4], [0, 0]]],
                },
                {"name": "delta"},
            )
        ],
    )


def test_vector_edit_session_keeps_committed_state_immutable_until_commit() -> None:
    layer = _layer()
    session = layer.start_editing()
    session.move_feature("f1", 10.0, 0.0)

    assert layer.feature("f1").geometry["coordinates"][0][0] == (0.0, 0.0)
    assert session.feature("f1").geometry["coordinates"][0][0] == (10.0, 0.0)
    assert session.is_dirty
    assert layer.source_ref == "catalog:raw:facies-v1"

    session.commit_changes()

    assert layer.feature("f1").geometry["coordinates"][0][0] == (10.0, 0.0)
    assert layer.data_revision == 2
    assert layer.edit_session is None


def test_vector_edit_session_undo_redo_and_rollback_are_reversible() -> None:
    layer = _layer()
    session = layer.start_editing()
    session.add_feature(VectorFeature("f2", {"type": "Point", "coordinates": [2, 2]}))
    session.change_attribute("f1", "name", "shoreface")
    session.set_vertex("f1", (0, 1), (5, 0))

    assert isinstance(session.undo_stack[-1], SetVertexCommand)
    assert session.feature("f1").geometry["coordinates"][0][1] == (5.0, 0.0)
    assert session.undo()
    assert session.feature("f1").geometry["coordinates"][0][1] == (4.0, 0.0)
    assert session.redo()
    assert session.feature("f1").geometry["coordinates"][0][1] == (5.0, 0.0)
    assert {command.command_type for command in session.undo_stack} == {
        "add_feature", "change_attribute", "set_vertex"
    }

    session.rollback_changes()

    assert layer.edit_session is None
    assert layer.feature_ids() == ("f1",)
    assert layer.feature("f1").attributes["name"] == "delta"


def test_vector_edit_command_types_are_deterministic_and_auditable() -> None:
    layer = _layer()
    session = layer.start_editing()
    session.add_feature(VectorFeature("f2", {"type": "Point", "coordinates": [2, 2]}))
    session.delete_feature("f2")
    session.move_feature("f1", 1, 0)
    session.set_geometry("f1", {"type": "Point", "coordinates": [1, 1]})
    session.change_attribute("f1", "name", "point")

    assert isinstance(session.undo_stack[0], AddFeatureCommand)
    assert isinstance(session.undo_stack[1], DeleteFeatureCommand)
    assert isinstance(session.undo_stack[2], MoveFeatureCommand)
    assert isinstance(session.undo_stack[3], SetGeometryCommand)
    assert isinstance(session.undo_stack[4], ChangeAttributeCommand)
    audit = session.audit_history()
    assert [entry["command_type"] for entry in audit] == [
        "add_feature", "delete_feature", "move_feature", "set_geometry", "change_attribute"
    ]
    assert audit[-1]["feature_ids"] == ["f1"]


def test_vector_layer_selection_is_feature_id_state_not_ui_item_state() -> None:
    layer = _layer()

    assert layer.set_selection(["f1", "missing"]) == {"f1"}
    assert layer.toggle_selection("f1") == set()
    assert layer.select_all() == {"f1"}
    assert layer.invert_selection() == set()


def test_working_feature_selection_includes_new_buffered_features() -> None:
    layer = _layer()
    session = layer.start_editing()
    session.add_feature(VectorFeature("f2", {"type": "Point", "coordinates": [2, 2]}))

    assert layer.set_selection(["f2"]) == {"f2"}
    assert layer.select_all() == {"f1", "f2"}
    session.rollback_changes()
    assert layer.selection == {"f1"}


def test_vector_session_ring_split_and_merge_commands_are_reversible() -> None:
    layer = _layer()
    session: VectorEditSession = layer.start_editing()
    session.add_ring("f1", [[1, 1], [2, 1], [1, 2]])
    assert len(session.feature("f1").geometry["coordinates"]) == 2
    session.delete_ring("f1", 1)
    assert len(session.feature("f1").geometry["coordinates"]) == 1

    first = VectorFeature("split-a", {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [0, 2], [0, 0]]]})
    second = VectorFeature("split-b", {"type": "Polygon", "coordinates": [[[2, 0], [4, 0], [2, 2], [2, 0]]]})
    session.split_feature("f1", [first, second])
    assert {feature.feature_id for feature in session.features()} == {"split-a", "split-b"}
    session.undo()
    assert session.feature("f1").feature_id == "f1"
    session.redo()

    session.merge_features(
        ["split-a", "split-b"],
        VectorFeature("merged", {"type": "MultiPolygon", "coordinates": [
            first.geometry["coordinates"], second.geometry["coordinates"],
        ]}),
    )
    assert session.feature("merged").geometry["type"] == "MultiPolygon"
    assert session.undo_stack[-1].command_type == "merge_features"
