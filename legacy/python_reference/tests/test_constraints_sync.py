"""Goal §11 P0-3: constraint geometry sync-back (vector layer → ConstraintLine).

Covers harvest of digitized features into the linked ``ConstraintLine``
(matched by ``properties.layer_id`` with a kind+name fallback), ring closure
for polygon kinds (mask / exclusion), one line per feature with replace
semantics (no accumulation across re-syncs), and content-fingerprint
stability (same coordinates → same sha256; changed coordinates → new hash).
"""
from __future__ import annotations

import pytest

from paleo_workbench.mapping_workspace.constraints_sync import (
    constraint_content_fingerprint,
    sync_constraint_geometry,
)
from paleo_workbench.project.models import (
    ConstraintLayers,
    ConstraintLine,
    ProjectDocument,
    UserVectorFeature,
    UserVectorLayer,
)


def _document() -> ProjectDocument:
    return ProjectDocument.new("Constraint sync")


def _fault_layer(features: list[UserVectorFeature]) -> UserVectorLayer:
    return UserVectorLayer(
        id="uvl-fault-1",
        name="断层 1",
        geometry_kind="line",
        template="fault",
        features=features,
    )


def _line_feature(points: list[list[float]], fid: str = "f1") -> UserVectorFeature:
    return UserVectorFeature(
        id=fid,
        geometry={"type": "LineString", "coordinates": points},
        properties={},
    )


def _stamped_group(layer: UserVectorLayer, kind_value: str, role: str,
                   layer_id: str = "") -> ConstraintLayers:
    group = ConstraintLayers(name="约束层")
    group.lines.append(ConstraintLine(
        name=layer.name,
        role=role,
        properties={"layer_id": layer_id or layer.id, "constraint_kind": kind_value},
    ))
    return group


# ---------------------------------------------------------------------------
# Line-kind constraints
# ---------------------------------------------------------------------------


def test_harvest_line_geometry_by_layer_id_stamp():
    document = _document()
    layer = _fault_layer([_line_feature([[0, 0], [1, 1], [2, 0.5]])])
    document.user_vector_layers.append(layer)
    document.constraint_layers.append(_stamped_group(layer, "fault", "break"))

    report = sync_constraint_geometry(document, layer.id)
    assert report["ok"] is True
    assert report["matched_by"] == "layer_id"
    assert report["lines_synced"] == 1
    assert report["features_harvested"] == 1
    line = document.constraint_layers[0].lines[0]
    assert line.role == "break"
    assert line.coordinates == [[0, 0], [1, 1], [2, 0.5]]
    assert line.properties["layer_id"] == layer.id
    assert line.properties["constraint_kind"] == "fault"
    fingerprint = line.properties["content_fingerprint"]
    assert fingerprint and fingerprint == report["content_fingerprint"]


def test_fingerprint_stability_and_change():
    coords = [[0.0, 0.0], [1.0, 1.0]]
    assert constraint_content_fingerprint(coords) == constraint_content_fingerprint(
        [[0, 0], [1, 1]])  # int/float encoding must not churn the hash
    assert constraint_content_fingerprint(coords) != constraint_content_fingerprint(
        [[0.0, 0.0], [1.0, 2.0]])

    document = _document()
    layer = _fault_layer([_line_feature(coords)])
    document.user_vector_layers.append(layer)
    document.constraint_layers.append(_stamped_group(layer, "fault", "break"))
    first = sync_constraint_geometry(document, layer.id)["content_fingerprint"]
    second = sync_constraint_geometry(document, layer.id)["content_fingerprint"]
    assert first == second  # same coords → same hash

    layer.features = [_line_feature([[0.0, 0.0], [3.0, 3.0]])]
    third = sync_constraint_geometry(document, layer.id)["content_fingerprint"]
    assert third != first


def test_fallback_match_by_kind_and_name_for_legacy_lines():
    document = _document()
    layer = _fault_layer([_line_feature([[0, 0], [5, 5]])])
    document.user_vector_layers.append(layer)
    group = ConstraintLayers(name="约束层")
    # Legacy line: no layer_id stamp, empty coordinates, same name+kind.
    group.lines.append(ConstraintLine(
        name="断层 1", role="break",
        properties={"constraint_kind": "fault"}))
    document.constraint_layers.append(group)

    report = sync_constraint_geometry(document, layer.id)
    assert report["ok"] is True
    assert report["matched_by"] == "constraint_kind+name"
    assert group.lines[0].coordinates == [[0, 0], [5, 5]]
    assert group.lines[0].properties["layer_id"] == layer.id


def test_multilinestring_parts_are_joined():
    document = _document()
    layer = _fault_layer([UserVectorFeature(
        id="f1",
        geometry={"type": "MultiLineString",
                  "coordinates": [[[0, 0], [1, 1]], [[1, 1], [2, 2]]]},
    )])
    document.user_vector_layers.append(layer)
    document.constraint_layers.append(_stamped_group(layer, "fault", "break"))
    report = sync_constraint_geometry(document, layer.id)
    assert report["ok"] is True
    line = document.constraint_layers[0].lines[0]
    assert line.coordinates == [[0, 0], [1, 1], [2, 2]]  # joint deduped


# ---------------------------------------------------------------------------
# Polygon-kind constraints (mask / exclusion)
# ---------------------------------------------------------------------------


def test_mask_ring_closure_and_hole_skip():
    document = _document()
    layer = UserVectorLayer(
        id="uvl-mask-1",
        name="掩膜 1",
        geometry_kind="polygon",
        template="mask",
        features=[UserVectorFeature(
            id="f1",
            geometry={
                "type": "Polygon",
                "coordinates": [
                    [[0, 0], [4, 0], [4, 4], [0, 4]],   # unclosed exterior
                    [[1, 1], [2, 1], [2, 2], [1, 2]],   # hole
                ],
            },
        )],
    )
    document.user_vector_layers.append(layer)
    document.constraint_layers.append(_stamped_group(layer, "mask", "boundary"))

    report = sync_constraint_geometry(document, layer.id)
    assert report["ok"] is True
    line = document.constraint_layers[0].lines[0]
    # Ring closure: first vertex appended; ≥4 points for the ring consumer.
    assert line.coordinates[0] == line.coordinates[-1] == [0, 0]
    assert len(line.coordinates) == 5
    assert report["interior_rings_skipped"] == 1


def test_multi_feature_polygon_layer_syncs_one_line_per_feature():
    document = _document()
    layer = UserVectorLayer(
        id="uvl-mask-2",
        name="掩膜 2",
        geometry_kind="polygon",
        template="exclusion_area",
        features=[
            UserVectorFeature(
                id="f1",
                geometry={"type": "Polygon",
                          "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
            ),
            UserVectorFeature(
                id="f2",
                geometry={"type": "Polygon",
                          "coordinates": [[[2, 2], [3, 2], [3, 3], [2, 3]]]},
            ),
        ],
    )
    document.user_vector_layers.append(layer)
    document.constraint_layers.append(_stamped_group(layer, "exclusion_area", "boundary"))

    report = sync_constraint_geometry(document, layer.id)
    assert report["ok"] is True
    assert report["lines_synced"] == 2
    lines = document.constraint_layers[0].lines
    assert len(lines) == 2
    assert all(line.properties["layer_id"] == layer.id for line in lines)
    # Replace semantics: re-sync after dropping a feature never accumulates.
    layer.features = [layer.features[0]]
    again = sync_constraint_geometry(document, layer.id)
    assert again["lines_synced"] == 1
    assert len(document.constraint_layers[0].lines) == 1


# ---------------------------------------------------------------------------
# Honest refusal paths
# ---------------------------------------------------------------------------


def test_refuses_unknown_empty_and_non_constraint_layers():
    document = _document()
    assert sync_constraint_geometry(document, "nope")["ok"] is False

    plain = UserVectorLayer(id="uvl-plain", name="自由图层", geometry_kind="line")
    document.user_vector_layers.append(plain)
    report = sync_constraint_geometry(document, plain.id)
    assert report == {"ok": False, "reason": "not_a_constraint_layer",
                      "layer_id": "uvl-plain"}

    empty = _fault_layer([])
    document.user_vector_layers.append(empty)
    document.constraint_layers.append(_stamped_group(empty, "fault", "break"))
    # Seed a previous sync so we can prove it is NOT wiped by an empty layer.
    empty.features = [_line_feature([[0, 0], [1, 1]])]
    sync_constraint_geometry(document, empty.id)
    seeded = document.constraint_layers[0].lines[0].coordinates
    empty.features = []
    report = sync_constraint_geometry(document, empty.id)
    assert report["ok"] is False and report["reason"] == "layer_empty"
    assert document.constraint_layers[0].lines[0].coordinates == seeded


def test_creates_line_when_no_match_exists():
    document = _document()
    layer = _fault_layer([_line_feature([[0, 1], [2, 3]])])
    document.user_vector_layers.append(layer)
    document.constraint_layers.append(ConstraintLayers(name="约束层"))

    report = sync_constraint_geometry(document, layer.id)
    assert report["ok"] is True
    assert report["matched_by"] == "created_new_line"
    line = document.constraint_layers[0].lines[0]
    assert line.role == "break"  # kind.interpolation_role
    assert line.coordinates == [[0, 1], [2, 3]]
    assert line.properties["content_fingerprint"]


# ---------------------------------------------------------------------------
# Wiring — stage_save calls back the digitized geometry (fallback canvas path)
# ---------------------------------------------------------------------------


def test_stage_save_harvests_digitized_constraint(qtbot, monkeypatch):
    pytest.importorskip("PySide6")
    from paleo_workbench.mapping.vector_layer import VectorFeature
    from paleo_workbench.mapping_workspace.layer_roles import LayerRole
    from paleo_workbench.ui.workstation.composite_document import CompositeDocument

    def _no_bridge():
        raise RuntimeError("bridge disabled for test")

    monkeypatch.setattr(
        "paleo_workbench.ui.qgis_stack.canvas_shim._load_mapstack", _no_bridge)
    project = _document()
    doc = CompositeDocument(project)
    qtbot.addWidget(doc)

    doc.stage_actions.create_constraint("fault")
    fault_ids = doc.stage_controller.state.layers_with_role(
        LayerRole.FAULT_CONSTRAINT)
    assert fault_ids
    layer_id = str(fault_ids[0])
    # Engine-side line exists with EMPTY coordinates (create_constraint stamp).
    stamped = [
        line for line in project.constraint_layers[0].lines
        if line.properties.get("layer_id") == layer_id
    ]
    assert stamped and stamped[0].coordinates == []
    # Digitize a fault polyline (trusted import path, session committed).
    doc.edit_controller.import_layer_features(layer_id, [VectorFeature(
        feature_id="f1",
        geometry={"type": "LineString", "coordinates": [[0.0, 0.0], [3.0, 4.0]]},
        attributes={},
    )])
    doc.stage_actions.stage_save()

    line = next(line for line in project.constraint_layers[0].lines
                if line.properties.get("layer_id") == layer_id)
    assert line.role == "break"
    assert line.coordinates == [[0.0, 0.0], [3.0, 4.0]]
    assert line.properties["content_fingerprint"]
