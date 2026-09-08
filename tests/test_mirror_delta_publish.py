"""§9 incremental mirror publish — ledger semantics (pure Python, fakes).

The C++ delta application is covered by qgis-marked tests once the bridge is
built; these tests verify the HOST side: tokens, no-op skips, delta
computation, and honest fallbacks.
"""

from __future__ import annotations

import json

from dataclasses import replace

import pytest

import paleo_workbench.mapping.qgis_mirror as qgis_mirror
from paleo_workbench.mapping.map_render_backend import MapLayerSnapshot
from paleo_workbench.mapping.qgis_mirror import (
    _MIRROR_LEDGER,
    mirror_snapshot_to_stack,
    reset_publish_ledger,
)


class _DeltaCapableStack:
    def __init__(self):
        self.calls: list[dict] = []
        self.removed_except = None
        self.order = None

    def set_destination_crs(self, canvas, crs):
        pass

    def upsert_mirror_layer(self, doc_id, name, geom, crs, geojson,
                            renderer_xml="", labeling_xml="",
                            legacy_style=None, visible=True, opacity=1.0,
                            is_reference=False, is_editable=False,
                            reference_snap=False, data_revision=0, delta="",
                            fields_json=""):
        """upsert_mirror_layer(..., data_revision: int, delta: str) -> str"""
        self.calls.append({
            "doc_id": doc_id, "geojson": json.loads(geojson),
            "data_revision": data_revision,
            "delta": json.loads(delta) if delta else None,
        })
        return f"qgis-{doc_id}"

    def remove_mirror_layers_except(self, seen):
        self.removed_except = list(seen)

    def set_mirror_layer_order(self, order):
        self.order = list(order)

    def refresh_canvas(self, canvas):
        pass


class _LegacyStack(_DeltaCapableStack):
    """Bridge without the delta channel (older build)."""

    def upsert_mirror_layer(self, doc_id, name, geom, crs, geojson,
                            renderer_xml="", labeling_xml="",
                            legacy_style=None, visible=True, opacity=1.0,
                            is_reference=False, is_editable=False,
                            reference_snap=False, data_revision=0, delta=""):
        if delta:
            raise TypeError(
                "upsert_mirror_layer() got an unexpected keyword argument 'delta'")
        return super().upsert_mirror_layer(
            doc_id, name, geom, crs, geojson, renderer_xml, labeling_xml,
            legacy_style, visible, opacity, is_reference, is_editable,
            reference_snap, data_revision)


def _vector_layer(features, revision=1, visible=True, opacity=1.0):
    return MapLayerSnapshot(
        id="draft-1", name="草稿", layer_type="vector",
        extent=(0, 0, 10, 10), crs="EPSG:32650",
        data_revision=revision, style_revision=1,
        features=tuple(features), style={}, visible=visible, opacity=opacity,
        renderer_payload=None,
    )


def _feature(fid, x=0.0, y=0.0, name="f"):
    return {
        "id": fid,
        "geometry": {"type": "Point", "coordinates": [x, y]},
        "properties": {"name": name},
    }


class _Snap:
    def __init__(self, layers, project_crs="EPSG:32650"):
        self.layers = tuple(layers)
        self.project_crs = project_crs


@pytest.fixture(autouse=True)
def _clean_ledger():
    reset_publish_ledger()
    yield
    reset_publish_ledger()


def test_first_publish_ships_full_collection():
    stack = _DeltaCapableStack()
    features = [_feature("a"), _feature("b")]
    mirror_snapshot_to_stack(stack, 0x1, _Snap([_vector_layer(features)]))
    assert len(stack.calls) == 1
    assert stack.calls[0]["delta"] is None
    assert len(stack.calls[0]["geojson"]["features"]) == 2


def test_noop_publish_ships_nothing():
    stack = _DeltaCapableStack()
    layer = _vector_layer([_feature("a"), _feature("b")])
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer]))
    assert len(stack.calls) == 1
    # same tokens, same content: second publish must not re-ship the layer
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer]))
    assert len(stack.calls) == 1


def test_visibility_only_change_skips_feature_payload():
    stack = _DeltaCapableStack()
    features = [_feature("a"), _feature("b")]
    mirror_snapshot_to_stack(stack, 0x1, _Snap([_vector_layer(features)]))
    flipped = _vector_layer(features, visible=False)
    mirror_snapshot_to_stack(stack, 0x1, _Snap([flipped]))
    assert len(stack.calls) == 2
    assert stack.calls[1]["delta"] is None
    assert stack.calls[1]["geojson"]["features"]  # full ship, no delta
    # data/style/visibility tokens recorded — third no-op stays cheap
    mirror_snapshot_to_stack(stack, 0x1, _Snap([flipped]))
    assert len(stack.calls) == 2


def test_single_feature_edit_ships_delta_not_full_collection():
    stack = _DeltaCapableStack()
    features = [_feature(f"p{i}", x=i) for i in range(50)]
    mirror_snapshot_to_stack(stack, 0x1, _Snap([_vector_layer(features, revision=1)]))
    edited = list(features)
    edited[7] = _feature("p7", x=7, name="edited")
    layer = _vector_layer(edited, revision=2)
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer]))
    assert len(stack.calls) == 2
    delta = stack.calls[1]["delta"]
    assert delta is not None
    assert delta["base_revision"] == 1
    assert len(delta["changed"]) == 1
    assert delta["changed"][0]["properties"]["__pwb_fid"] == "p7"
    assert delta["removed_ids"] == []


def test_feature_removal_ships_removed_ids():
    stack = _DeltaCapableStack()
    features = [_feature("a"), _feature("b"), _feature("c")]
    mirror_snapshot_to_stack(stack, 0x1, _Snap([_vector_layer(features)]))
    layer = _vector_layer([features[0], features[2]], revision=2)
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer]))
    delta = stack.calls[1]["delta"]
    assert delta["removed_ids"] == ["b"]
    assert delta["changed"] == []


def test_stale_base_falls_back_to_full_ship():
    stack = _DeltaCapableStack()
    mirror_snapshot_to_stack(stack, 0x1, _Snap([
        _vector_layer([_feature("a")], revision=5)]))
    # ledger reset underneath (project reload): base 5 unknown → full ship
    from paleo_workbench.mapping.qgis_mirror import reset_publish_ledger

    reset_publish_ledger()
    layer = _vector_layer([_feature("a"), _feature("b")], revision=6)
    mirror_snapshot_to_stack(stack, 0x1, _Snap([layer]))
    assert stack.calls[1]["delta"] is None
    assert len(stack.calls[1]["geojson"]["features"]) == 2


def test_legacy_bridge_without_delta_channel():
    stack = _LegacyStack()
    features = [_feature(f"p{i}") for i in range(10)]
    mirror_snapshot_to_stack(stack, 0x1, _Snap([_vector_layer(features, revision=1)]))
    edited = list(features)
    edited[3] = _feature("p3", name="moved")
    mirror_snapshot_to_stack(stack, 0x1, _Snap([_vector_layer(edited, revision=2)]))
    # TypeError fallback: full ship still succeeds
    assert len(stack.calls) == 2
    assert len(stack.calls[1]["geojson"]["features"]) == 10


def test_geometry_kind_drift_forces_full_path():
    stack = _DeltaCapableStack()
    points = [_feature("a"), _feature("b")]
    mirror_snapshot_to_stack(stack, 0x1, _Snap([_vector_layer(points, revision=1)]))
    polygons = [{
        "id": "a",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
        "properties": {"name": "f"},
    }, {
        "id": "b",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]]},
        "properties": {"name": "f"},
    }]
    mirror_snapshot_to_stack(stack, 0x1, _Snap([_vector_layer(polygons, revision=2)]))
    # geom-kind token mismatch ⇒ no delta attempted
    assert stack.calls[1]["delta"] is None


def test_removed_layer_drops_ledger():
    stack = _DeltaCapableStack()
    mirror_snapshot_to_stack(stack, 0x1, _Snap([
        _vector_layer([_feature("a")], revision=1)]))
    mirror_snapshot_to_stack(stack, 0x1, _Snap([]))
    assert stack.removed_except == []
    from paleo_workbench.mapping.qgis_mirror import _ledger_key

    assert _ledger_key(stack, "draft-1") not in _MIRROR_LEDGER


class _StrictSignatureStack(_DeltaCapableStack):
    """Fake mirroring the REAL bridge signature: rejects unknown kwargs
    (R3-1 regression: mocks accepting **kwargs hid the fields_json break)."""

    def __init__(self):
        super().__init__()
        self.received_fields: list = []

    def upsert_mirror_layer(self, doc_id, name, geom, crs, geojson,
                            renderer_xml="", labeling_xml="",
                            legacy_style=None, visible=True, opacity=1.0,
                            is_reference=False, is_editable=False,
                            reference_snap=False, data_revision=0, delta="",
                            fields_json=""):
        self.received_fields.append(fields_json)
        return super().upsert_mirror_layer(
            doc_id, name, geom, crs, geojson, renderer_xml, labeling_xml,
            legacy_style, visible, opacity, is_reference, is_editable,
            reference_snap, data_revision, delta, fields_json)


def test_strict_signature_stack_single_upsert_per_publish():
    """R3-1: with a bridge-shaped signature, one publish performs exactly one
    upsert per changed layer — no blind second full upsert."""
    stack = _StrictSignatureStack()
    features = [_feature("a"), _feature("b")]
    mirror_snapshot_to_stack(stack, 0x1, _Snap([_vector_layer(features)]))
    assert len(stack.calls) == 1
    edited = [_feature("a"), _feature("b", name="changed")]
    mirror_snapshot_to_stack(stack, 0x1, _Snap([_vector_layer(edited, revision=2)]))
    assert len(stack.calls) == 2
    assert stack.calls[1]["delta"] is not None  # delta consumed, not retried


def test_fields_json_flows_from_role_metadata():
    """R2-F4: layers declaring a role carry the spec's fields_json."""
    stack = _StrictSignatureStack()
    layer = _vector_layer([_feature("a")])
    roled = replace(layer, metadata={"role": "fault_constraint"})
    mirror_snapshot_to_stack(stack, 0x1, _Snap([roled]))
    assert len(stack.calls) == 1
    assert stack.received_fields and "fault_type" in stack.received_fields[0]
