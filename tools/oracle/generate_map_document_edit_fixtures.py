#!/usr/bin/env python3
"""Oracle fixture generator for the CONV-27 mapping_document behavior layer.

Imports the REAL Python product code and freezes:

* ``composition_cases`` — full CompositionEditSession behavior (the Python
  session is the source of truth): op sequences replayed on a real session,
  observable state captured after every op (revision, can_undo/can_redo,
  undo/redo stack labels, document to_dict) plus every refused-command
  error class;
* ``map_document_cases`` — MapDocument kernel op behavior (Python has no
  map-document session; the document states are the source of truth): op
  sequences applied to a real MapDocument, to_dict captured per step;
* ``snapshot_cases`` — real document states at labeled points (the
  C++ snapshot *projection* is C++-contract; the document content frozen
  here is Python);
* ``io_feature_cases`` — document_io.features_from_document /
  apply_features_to_document outputs for messy legacy records.

Determinism: every uuid4 the product would call is patched to a shared
deterministic hex counter, so generated ids are stable and frozen into the
fixture (C++ replays with an equivalent generator).

Regenerate with the oracle venv (needs PySide6 for the mapping import
chain):
    /home/kevin/project/oracle-venvs/conv11/bin/python3 \
        tools/oracle/generate_map_document_edit_fixtures.py
"""

from __future__ import annotations

import copy
import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import paleo_workbench.mapping.composer.components as components  # noqa: E402
import paleo_workbench.mapping.composer.models as composer_models  # noqa: E402
import paleo_workbench.mapping.layers as layers_mod  # noqa: E402
import paleo_workbench.mapping.geometry_schema as geometry_schema  # noqa: E402
from paleo_workbench.mapping.composer.components import (  # noqa: E402
    CompositionEditSession,
    bind_template,
)
from paleo_workbench.mapping.composer.models import (  # noqa: E402
    ElementType,
    MapCompositionDocument,
)
from paleo_workbench.mapping.composer.registry import all_specs  # noqa: E402
from paleo_workbench.mapping.document_io import (  # noqa: E402
    apply_features_to_document,
    features_from_document,
)
from paleo_workbench.mapping.layers import (  # noqa: E402
    MapDocument,
    VectorMapLayer,
)

# ---------------------------------------------------------------------------
# Deterministic id generation (one shared hex counter, per-format widths)
# ---------------------------------------------------------------------------

_COUNTER = {"n": 0}


def _hex(width: int) -> str:
    _COUNTER["n"] += 1
    return f"{_COUNTER['n']:0{width}x}"


class _FakeUuid4:
    def __init__(self, width: int) -> None:
        self._width = width

    @property
    def hex(self) -> str:
        return _hex(self._width)


def install_deterministic_ids() -> None:
    _COUNTER["n"] = 0  # each case restarts the deterministic id sequence
    components.uuid = types.SimpleNamespace(
        uuid4=lambda: _FakeUuid4(10)
    )  # CompositionFactory.create
    components._new_element_id = lambda: f"el_{_hex(10)}"  # duplicate_element
    layers_mod.uuid4 = lambda: _FakeUuid4(8)  # layer/document ids
    geometry_schema.uuid4 = lambda: _FakeUuid4(12)  # new_feature_id


# ---------------------------------------------------------------------------
# Spec snapshot (registry defaults for the types the cases use)
# ---------------------------------------------------------------------------


def frozen_specs(element_types: list[str]) -> dict:
    specs = {}
    wanted = set(element_types)
    for spec in all_specs():
        key = spec.element_type.value
        if key in wanted:
            specs[key] = {
                "default_geometry": [float(v) for v in spec.default_geometry],
                "default_properties": copy.deepcopy(spec.default_properties),
            }
    missing = wanted - set(specs)
    if missing:
        raise SystemExit(f"unknown element types in case spec: {sorted(missing)}")
    return specs


# ---------------------------------------------------------------------------
# Composition session replay
# ---------------------------------------------------------------------------

COMPOSITION_ERRORS = {
    "ComposerError": components.ComposerError,
    "KeyError": KeyError,
    "ValueError": ValueError,
}


def run_composition_op(session: CompositionEditSession, op: dict, results: dict):
    """Apply one fixture op to the real session; returns (ok, error_class)."""
    kind = op["op"]
    if kind == "add_element":
        element = session.add_element(
            ElementType(op["element_type"]),
            x_mm=op.get("x_mm"),
            y_mm=op.get("y_mm"),
            width_mm=op.get("width_mm"),
            height_mm=op.get("height_mm"),
            properties=op.get("properties"),
        )
        results[id(op)] = element.id
        return True, None
    if kind == "insert_element":
        element = components.ComposerElement.from_dict(op["element"])
        session.insert_element(element)
        return True, None
    if kind == "remove_element":
        element = session.remove_element(op["element_id"])
        results[id(op)] = element.to_dict() if element is not None else None
        return True, None
    if kind == "move_element":
        session.move_element(op["element_id"], op["x_mm"], op["y_mm"])
        return True, None
    if kind == "scale_element":
        session.scale_element(op["element_id"], op["width_mm"], op["height_mm"])
        return True, None
    if kind == "configure_element":
        session.configure_element(op["element_id"], op["properties"])
        return True, None
    if kind == "duplicate_element":
        clone = session.duplicate_element(op["element_id"])
        results[id(op)] = clone.id if clone is not None else None
        return True, None
    if kind == "set_locked":
        session.set_locked(op["element_id"], op["locked"])
        return True, None
    if kind == "set_element_visible":
        session.set_element_visible(op["element_id"], op["visible"])
        return True, None
    if kind == "bring_to_front":
        session.bring_to_front(op["element_id"])
        return True, None
    if kind == "send_to_back":
        session.send_to_back(op["element_id"])
        return True, None
    if kind == "raise_element":
        session.raise_element(op["element_id"])
        return True, None
    if kind == "undo":
        results[id(op)] = session.undo()
        return True, None
    if kind == "redo":
        results[id(op)] = session.redo()
        return True, None
    if kind == "clear_history":
        session.clear_history()
        return True, None
    if kind == "bind_template":
        results[id(op)] = bind_template(session.document, binding_context=op["context"])
        return True, None
    if kind == "expect_error":
        # The refused call is executed for real; the error class is checked.
        error_type = COMPOSITION_ERRORS[op["error"]]
        try:
            run_composition_op(session, op["call"], results)
        except error_type:
            return True, None
        except Exception as exc:  # noqa: BLE001 — the mismatch IS the failure
            raise SystemExit(
                f"case op {op['call']} raised {type(exc).__name__}, "
                f"expected {op['error']}"
            ) from exc
        raise SystemExit(f"case op {op['call']} did not raise {op['error']}")
    raise SystemExit(f"unknown composition op {kind}")


def capture_composition_state(session: CompositionEditSession) -> dict:
    return {
        "revision": session.revision,
        "can_undo": session.can_undo(),
        "can_redo": session.can_redo(),
        "undo_labels": [cmd.label for cmd in session._undo_stack],
        "redo_labels": [cmd.label for cmd in session._redo_stack],
        "document": session.document.to_dict(),
    }


def composition_case(case: dict) -> dict:
    install_deterministic_ids()
    doc = MapCompositionDocument.from_dict(case["initial"])
    session = CompositionEditSession(doc)
    results: dict = {}
    steps = []
    element_types: list[str] = []

    def collect_types(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "element_type" and isinstance(value, str):
                    element_types.append(value)
                collect_types(value)
        elif isinstance(node, list):
            for item in node:
                collect_types(item)

    collect_types(case["ops"])
    specs = frozen_specs(sorted(set(element_types)))
    for index, op in enumerate(case["ops"]):
        run_composition_op(session, op, results)
        state = capture_composition_state(session)
        state["after_op"] = index
        result = results.get(id(op))
        if result is not None or op["op"] in {
            "remove_element", "duplicate_element", "undo", "redo", "bind_template"
        }:
            state["result"] = result
        steps.append(state)
    return {
        "name": case["name"],
        "expectation_source": "python-product",
        "specs": specs,
        "initial": case["initial"],
        "ops": case["ops"],
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# Map document kernel replay (document states are the Python truth)
# ---------------------------------------------------------------------------


def layer_from_payload(payload: dict):
    """Build the real Python layer from a frozen to_dict payload (the
    registry-baked default style and the post_init extent recompute are
    part of the frozen contract)."""
    return VectorMapLayer(
        id=payload["id"],
        name=payload.get("name", "Test Layer"),
        layer_type=payload.get("layer_type", "vector"),
        extent=tuple(payload.get("extent", (0.0, 0.0, 1.0, 1.0))),
        visible=payload.get("visible", True),
        source_version_id=payload.get("source_version_id", ""),
        features=tuple(payload.get("features", ())),
        style=dict(payload.get("style") or {}),
    )


def frozen_layer_payload(payload: dict) -> dict:
    """Construct the real layer and freeze its full to_dict (default style
    baked by real __post_init__ code, extent recomputed when features are
    present)."""
    return layer_from_payload(payload).to_dict()


def run_map_document_op(doc: MapDocument, op: dict, results: dict) -> None:
    kind = op["op"]
    if kind == "add_layer":
        layer = layer_from_payload(op["layer"])
        doc.add_layer(layer, op.get("position"))
        return
    if kind == "remove_layer":
        removed = doc.remove_layer(op["layer_id"])
        results[id(op)] = removed.to_dict() if removed is not None else None
        return
    if kind == "reorder_layers":
        doc.reorder_layers(op["layer_ids"])
        return
    if kind == "recompute_extent":
        doc.recompute_extent()
        return
    if kind == "set_visible":
        doc.get_layer(op["layer_id"]).set_visible(op["visible"])
        return
    if kind == "set_opacity":
        doc.get_layer(op["layer_id"]).set_opacity(op["opacity"])
        return
    if kind == "set_features":
        doc.get_layer(op["layer_id"]).set_features(op["features"])
        return
    if kind == "set_title":
        doc.title = op["title"]
        return
    if kind == "set_crs":
        doc.crs = op["crs"]
        return
    if kind == "set_active_layer":
        doc.active_layer_id = op["layer_id"]
        return
    if kind == "set_metadata":
        doc.metadata[op["key"]] = op["value"]
        return
    raise SystemExit(f"unknown map document op {kind}")


def map_document_case(case: dict) -> dict:
    install_deterministic_ids()
    doc = MapDocument(
        id=case["initial"].get("id", "map_00000001"),
        title=case["initial"].get("title", "Paleogeographic Map"),
        crs=case["initial"].get("crs", "EPSG:4326"),
        extent=tuple(case["initial"].get("extent", (0.0, 0.0, 1.0, 1.0))),
        metadata=copy.deepcopy(case["initial"].get("metadata", {})),
        active_layer_id=case["initial"].get("active_layer_id"),
    )
    for op in case["ops"]:
        if op["op"] == "add_layer":
            op["layer"] = frozen_layer_payload(op["layer"])
    results: dict = {}
    steps = []
    for index, op in enumerate(case["ops"]):
        run_map_document_op(doc, op, results)
        state = {
            "after_op": index,
            "document": doc.to_dict(),
        }
        result = results.get(id(op))
        if result is not None or op["op"] == "remove_layer":
            state["result"] = result
        steps.append(state)
    return {
        "name": case["name"],
        "expectation_source": "python-product",
        "initial": case["initial"],
        "ops": case["ops"],
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# Snapshot source states
# ---------------------------------------------------------------------------


def snapshot_case(case: dict) -> dict:
    install_deterministic_ids()
    doc = MapDocument(
        id=case["initial"]["id"],
        title=case["initial"].get("title", "Paleogeographic Map"),
        crs=case["initial"].get("crs", "EPSG:4326"),
        extent=tuple(case["initial"].get("extent", (0.0, 0.0, 1.0, 1.0))),
        metadata=copy.deepcopy(case["initial"].get("metadata", {})),
    )
    for layer_payload in case["initial"].get("layers", []):
        doc.add_layer(layer_from_payload(layer_payload))
    captures = [{"at_op": 0, "document": doc.to_dict()}]
    case["initial"]["layers"] = [
        frozen_layer_payload(layer_payload)
        for layer_payload in case["initial"].get("layers", [])
    ]
    for index, op in enumerate(case.get("mutations", []), start=1):
        run_map_document_op(doc, op, {})
        captures.append({"at_op": index, "document": doc.to_dict()})
    return {
        "name": case["name"],
        "expectation_source": "python-product",
        "initial": case["initial"],
        "mutations": case.get("mutations", []),
        "captures": captures,
    }


# ---------------------------------------------------------------------------
# document_io feature cases
# ---------------------------------------------------------------------------


def io_feature_case(case: dict) -> dict:
    install_deterministic_ids()
    record = copy.deepcopy(case["record"])
    # features_from_document consumes the PaleoMapDocument attribute surface;
    # the frozen record shape is exactly those attributes.
    document_like = types.SimpleNamespace(**record)
    features = features_from_document(document_like)
    reapplied = copy.deepcopy(record)
    reapplied_like = types.SimpleNamespace(**reapplied)
    apply_features_to_document(reapplied_like, features)
    reapplied = {
        key: getattr(reapplied_like, key)
        for key in ("facies_polygons", "well_overlays", "line_features",
                    "label_features")
    }
    return {
        "name": case["name"],
        "expectation_source": "python-product",
        "record": case["record"],
        "features": json.loads(json.dumps(features)),
        "reapplied_record": json.loads(json.dumps(reapplied)),
    }


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def build_fixture() -> dict:
    composition_cases = [
        composition_case({
            "name": "add_move_scale_undo_redo",
            "initial": {"id": "comp_0000000001", "title": "Case A"},
            "ops": [
                {"op": "add_element", "element_type": "legend",
                 "x_mm": 10.0, "y_mm": 20.0},
                {"op": "add_element", "element_type": "title",
                 "properties": {"text": "Hello"}},
                {"op": "move_element", "element_id": "el_0000000002",
                 "x_mm": 55.5, "y_mm": 66.25},
                {"op": "scale_element", "element_id": "el_0000000002",
                 "width_mm": 40.0, "height_mm": 12.5},
                {"op": "configure_element", "element_id": "el_0000000002",
                 "properties": {"text": "Changed", "color": "#123456"}},
                {"op": "undo"},
                {"op": "undo"},
                {"op": "undo"},
                {"op": "redo"},
                {"op": "redo"},
                {"op": "undo"},
            ],
        }),
        composition_case({
            "name": "remove_duplicate_lock_visibility",
            "initial": {"id": "comp_0000000002", "title": "Case B"},
            "ops": [
                {"op": "add_element", "element_type": "legend"},
                {"op": "add_element", "element_type": "north_arrow",
                 "x_mm": 5.0, "y_mm": 5.0},
                {"op": "duplicate_element", "element_id": "el_0000000002"},
                {"op": "set_locked", "element_id": "el_0000000003", "locked": True},
                {"op": "expect_error", "error": "ComposerError",
                 "call": {"op": "move_element", "element_id": "el_0000000003",
                          "x_mm": 1.0, "y_mm": 1.0}},
                {"op": "expect_error", "error": "ComposerError",
                 "call": {"op": "remove_element", "element_id": "el_0000000003"}},
                {"op": "expect_error", "error": "ComposerError",
                 "call": {"op": "duplicate_element", "element_id": "el_0000000003"}},
                {"op": "expect_error", "error": "ComposerError",
                 "call": {"op": "scale_element", "element_id": "el_0000000003",
                          "width_mm": 10.0, "height_mm": 10.0}},
                {"op": "expect_error", "error": "ComposerError",
                 "call": {"op": "configure_element", "element_id": "el_0000000003",
                          "properties": {"x": 1}}},
                {"op": "set_element_visible", "element_id": "el_0000000003",
                 "visible": False},
                {"op": "remove_element", "element_id": "el_0000000002"},
                {"op": "undo"},
                {"op": "redo"},
                {"op": "expect_error", "error": "KeyError",
                 "call": {"op": "move_element", "element_id": "el_missing",
                          "x_mm": 0.0, "y_mm": 0.0}},
                {"op": "set_locked", "element_id": "el_0000000003", "locked": False},
                {"op": "remove_element", "element_id": "el_0000000003"},
                {"op": "undo"},
                {"op": "undo"},
            ],
        }),
        composition_case({
            "name": "z_order_ties",
            "initial": {"id": "comp_0000000003", "title": "Case C"},
            "ops": [
                {"op": "insert_element",
                 "element": {"id": "el_zz00000001", "element_type": "text",
                             "x_mm": 1.0, "y_mm": 1.0, "width_mm": 2.0,
                             "height_mm": 2.0, "z_index": 1,
                             "visible": True, "locked": False,
                             "properties": {"text": "one"}}},
                {"op": "insert_element",
                 "element": {"id": "el_zz00000002", "element_type": "text",
                             "x_mm": 2.0, "y_mm": 2.0, "width_mm": 2.0,
                             "height_mm": 2.0, "z_index": 1,
                             "visible": True, "locked": False,
                             "properties": {"text": "two"}}},
                {"op": "insert_element",
                 "element": {"id": "el_zz00000003", "element_type": "text",
                             "x_mm": 3.0, "y_mm": 3.0, "width_mm": 2.0,
                             "height_mm": 2.0, "z_index": 0,
                             "visible": True, "locked": False,
                             "properties": {"text": "three"}}},
                {"op": "bring_to_front", "element_id": "el_zz00000003"},
                {"op": "send_to_back", "element_id": "el_zz00000001"},
                {"op": "raise_element", "element_id": "el_zz00000002"},
                {"op": "remove_element", "element_id": "el_zz00000002"},
                {"op": "undo"},
                {"op": "undo"},
                {"op": "undo"},
                {"op": "undo"},
                {"op": "undo"},
            ],
        }),
        composition_case({
            "name": "scale_error_leaves_history_untouched",
            "initial": {"id": "comp_0000000004", "title": "Case D"},
            "ops": [
                {"op": "add_element", "element_type": "scale_bar"},
                {"op": "move_element", "element_id": "el_0000000001",
                 "x_mm": 12.0, "y_mm": 13.0},
                {"op": "expect_error", "error": "ValueError",
                 "call": {"op": "scale_element", "element_id": "el_0000000001",
                          "width_mm": 0.0, "height_mm": 5.0}},
                {"op": "expect_error", "error": "ValueError",
                 "call": {"op": "scale_element", "element_id": "el_0000000001",
                          "width_mm": 5.0, "height_mm": -1.0}},
                {"op": "undo"},
                {"op": "undo"},
            ],
        }),
        composition_case({
            "name": "noops_still_bump_revision",
            "initial": {"id": "comp_0000000005", "title": "Case E"},
            "ops": [
                {"op": "add_element", "element_type": "legend", "x_mm": 1.0},
                {"op": "move_element", "element_id": "el_0000000001",
                 "x_mm": 1.0, "y_mm": 0.0},
                {"op": "set_element_visible", "element_id": "el_0000000001",
                 "visible": True},
                {"op": "raise_element", "element_id": "el_0000000001"},
                {"op": "bring_to_front", "element_id": "el_0000000001"},
                {"op": "send_to_back", "element_id": "el_0000000001"},
            ],
        }),
        composition_case({
            "name": "bind_template_resolves",
            "initial": {"id": "comp_0000000007", "title": "Case G"},
            "ops": [
                {"op": "add_element", "element_type": "colorbar",
                 "properties": {"data_binding": {"key": "factor.colorbar",
                                                 "fields": ["min", "max"]},
                                "title": "Untouched"}},
                {"op": "add_element", "element_type": "colorbar",
                 "properties": {"data_binding": {"key": "missing.key"}}},
                {"op": "add_element", "element_type": "colorbar",
                 "properties": {"data_binding": {"key": "factor.scale",
                                                 "fields": []}}},
                {"op": "bind_template",
                 "context": {"factor.colorbar": {"min": 0.0, "max": 1.0,
                                                 "units": "m"},
                             "factor.scale": {"min": -1.0, "max": 2.0,
                                              "units": "km", "extra": 7}}},
                {"op": "undo"},
                {"op": "bind_template", "context": {}},
            ],
        }),
        composition_case({
            "name": "clear_history_stops_undo",
            "initial": {"id": "comp_0000000008", "title": "Case H"},
            "ops": [
                {"op": "add_element", "element_type": "legend"},
                {"op": "clear_history"},
                {"op": "undo"},
                {"op": "add_element", "element_type": "title"},
                {"op": "undo"},
                {"op": "redo"},
            ],
        }),
    ]

    map_document_cases = [
        map_document_case({
            "name": "layers_add_remove_reorder_recompute",
            "initial": {"id": "map_0000000a", "title": "Map A",
                        "crs": "EPSG:4326"},
            "ops": [
                {"op": "add_layer",
                 "layer": {"id": "lyr_00000001", "name": "Wells",
                           "extent": [10.0, 20.0, 30.0, 40.0],
                           "source_version_id": "ver_1"}},
                {"op": "add_layer",
                 "layer": {"id": "lyr_00000002", "name": "Facies",
                           "extent": [5.0, 15.0, 25.0, 50.0],
                           "visible": False}},
                {"op": "add_layer",
                 "layer": {"id": "lyr_00000003", "name": "Lines",
                           "extent": [0.0, 0.0, 1.0, 1.0]},
                 "position": 0},
                {"op": "add_layer",
                 "layer": {"id": "lyr_00000004", "name": "First wins active"}},
                {"op": "remove_layer", "layer_id": "lyr_00000001"},
                {"op": "remove_layer", "layer_id": "lyr_missing"},
                {"op": "reorder_layers",
                 "layer_ids": ["lyr_00000003", "lyr_00000002"]},
                {"op": "reorder_layers",
                 "layer_ids": ["lyr_00000002", "lyr_00000002",
                               "lyr_unknown", "lyr_00000003"]},
                {"op": "reorder_layers", "layer_ids": []},
                {"op": "recompute_extent"},
            ],
        }),
        map_document_case({
            "name": "layer_style_and_feature_updates",
            "initial": {"id": "map_0000000b", "title": "Map B"},
            "ops": [
                {"op": "add_layer",
                 "layer": {"id": "lyr_00000010", "name": "Vectors",
                           "layer_type": "vector",
                           "features": [
                               {"id": "f1",
                                "geometry": {"type": "Point",
                                             "coordinates": [1.0, 2.0]}},
                               {"id": "f2",
                                "geometry": {"type": "LineString",
                                             "coordinates": [[0.0, 0.0],
                                                             [4.0, 6.0]]}}
                           ]}},
                {"op": "set_visible", "layer_id": "lyr_00000010",
                 "visible": False},
                {"op": "set_opacity", "layer_id": "lyr_00000010",
                 "opacity": 1.75},
                {"op": "set_features", "layer_id": "lyr_00000010",
                 "features": [
                     {"id": "f3",
                      "geometry": {"type": "Polygon",
                                   "coordinates": [[[0.0, 0.0], [2.0, 0.0],
                                                    [2.0, 2.0], [0.0, 0.0]]]}}
                 ]},
                {"op": "set_features", "layer_id": "lyr_00000010",
                 "features": []},
                {"op": "set_features", "layer_id": "lyr_00000010",
                 "features": [
                     {"id": "f4",
                      "geometry": {"type": "Point",
                                   "coordinates": [7.0, 7.0]}}
                 ]},
            ],
        }),
        map_document_case({
            "name": "document_level_fields",
            "initial": {"id": "map_0000000c", "title": "Map C",
                        "metadata": {"run_id": "run_a",
                                     "input_version_ids": ["v1", "v2"]}},
            "ops": [
                {"op": "add_layer",
                 "layer": {"id": "lyr_00000020", "name": "L1",
                           "extent": [1.0, 2.0, 3.0, 4.0],
                           "source_version_id": "v2"}},
                {"op": "add_layer",
                 "layer": {"id": "lyr_00000021", "name": "L2",
                           "extent": [10.0, 20.0, 30.0, 40.0],
                           "source_version_id": "v3"}},
                {"op": "set_title", "title": "Map C renamed"},
                {"op": "set_crs", "crs": "EPSG:3857"},
                {"op": "set_active_layer", "layer_id": "lyr_00000021"},
                {"op": "set_metadata", "key": "run_id", "value": "run_b"},
                {"op": "set_metadata", "key": "provenance",
                 "value": {"task": "t1", "inputs": ["v1"]}},
            ],
        }),
    ]

    snapshot_cases = [
        snapshot_case({
            "name": "snapshot_source_states",
            "initial": {
                "id": "map_0000000d",
                "title": "Snapshot Map",
                "crs": "EPSG:4326",
                "extent": [0.0, 0.0, 10.0, 10.0],
                "metadata": {"run_id": "run_snap",
                             "input_version_ids": ["va", "vb"],
                             "provenance": {"task": "snap-task"}},
                "layers": [
                    {"id": "lyr_00000030", "name": "Style carrier",
                     "extent": [1.0, 2.0, 3.0, 4.0],
                     "source_version_id": "va"},
                    {"id": "lyr_00000031", "name": "Feature carrier",
                     "extent": [0.0, 0.0, 1.0, 1.0],
                     "source_version_id": "vb",
                     "features": [
                         {"id": "s1",
                          "geometry": {"type": "Point",
                                       "coordinates": [5.5, 6.5]}}
                     ]},
                ],
            },
            "mutations": [
                {"op": "set_visible", "layer_id": "lyr_00000030",
                 "visible": False},
                {"op": "set_title", "title": "Mutated after capture"},
                {"op": "set_metadata", "key": "run_id", "value": "run_new"},
            ],
        }),
    ]

    io_feature_cases = [
        io_feature_case({
            "name": "malformed_geometry_skips",
            "record": {
                "facies_polygons": [
                    {"id": "fp_bad", "name": "Bad ring",
                     "geometry_type": "Polygon",
                     "coordinates": [[0.0, 0.0], ["a", "b"], [2.0, 2.0]]},
                ],
                "well_overlays": [
                    {"id": "w_empty", "name": "No coordinates",
                     "coordinates": []},
                ],
                "line_features": [
                    {"id": "l_scalar", "name": "Scalar point",
                     "coordinates": [5, "ab"]},
                    {"id": "l_string", "name": "Char expand",
                     "coordinates": ["ab", [1.0, 2.0]]},
                ],
                "label_features": [],
            },
        }),
        io_feature_case({
            "name": "legacy_record_roundtrip",
            "record": {
                "facies_polygons": [
                    {"id": "fp1", "name": "Sand",
                     "geometry_type": "Polygon",
                     "coordinates": [[[0.0, 0.0], [4.0, 0.0], [4.0, 4.0],
                                      [0.0, 0.0]]],
                     "style": {"fill": "#abc"},
                     "facies": "Sandstone", "probability": 0.75,
                     "region_id": "r1"},
                    {"id": "fp2", "facies": "Shale",
                     "geometry": {"type": "MultiPolygon",
                                  "coordinates": [
                                      [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0],
                                        [0.0, 0.0]]],
                                      [[[2.0, 2.0], [3.0, 2.0], [3.0, 3.0],
                                        [2.0, 2.0]]]]},
                     "properties": {"source": "compiler", "style": {"keep": 1}}},
                    {"id": "fp_open", "name": "Open ring",
                     "geometry_type": "Polygon",
                     "coordinates": [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0]]},
                ],
                "well_overlays": [
                    {"id": "w1", "name": "Well One",
                     "coordinates": [110.5, -23.25], "lng": 110.5, "lat": -23.25},
                    {"id": "w2", "name": "Short", "coordinates": [1.0]},
                    {"id": "w3", "name": "Bad", "coordinates": ["x", "y"]},
                    {"id": "w4", "name": "Scalar", "x": 5.0, "y": 6.0},
                    {"id": "w5", "name": "Mixed", "x": 5.0, "lat": 9.0},
                ],
                "line_features": [
                    {"id": "l1", "name": "Coast",
                     "coordinates": [[0.0, 0.0], [1.0, 1.0], [2.0, 0.5]]},
                    {"id": "l2", "name": "Empty", "coordinates": []},
                ],
                "label_features": [
                    {"id": "lb1", "text": "Basin", "anchor": [3.0, 4.0]},
                    {"id": "lb2", "text": "Bad", "anchor": [1.0]},
                    {"id": "lb3", "text": "XY", "x": 8.0, "y": 9.0},
                ],
            },
        }),
    ]

    return {
        "schema": "pwb.mapping_document.edit_oracle/1",
        "composition_cases": composition_cases,
        "map_document_cases": map_document_cases,
        "snapshot_cases": snapshot_cases,
        "io_feature_cases": io_feature_cases,
    }


def main() -> None:
    fixture = build_fixture()
    out_path = (REPO_ROOT / "libs" / "mapping_document" /
                "mapping_document_tests" / "fixtures" /
                "map_document_edit_oracle.json")
    out_path.write_text(
        json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
