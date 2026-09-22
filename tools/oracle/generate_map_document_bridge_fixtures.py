#!/usr/bin/env python3
"""Oracle fixture generator for the CONV-27d bridge edit domain.

Imports the REAL Python product code and freezes:

* ``session_set_cases`` — EditSessionSet lifecycle (open / join growth with
  gate accept+reject / discard / close), the CRS+schema change mutexes
  (exact rejection strings) and the stack-bound suppression window;
* ``gesture_cases`` — EditGestureManager finish/undo_plan/redo_plan/mark
  semantics (reverse-order undo, forward-order redo, idempotent marks,
  stale redo-queue pruning) plus the audit stream;
* ``native_cases`` — NativeEditSessionController against a fake bridge
  stack (same shape as tests/test_topo_m1_native_editing.py
  FakeNativeStack): gate-refused open never starts editing, old-bridge
  honest degradation, mirror rollback, read-back normalization, the
  attribute-write refusal matrix, gesture undo/redo plans over recorded
  bridge calls, and the whole-set all-or-nothing commit matrix (role gate,
  topology gate, geology gate, mid-commit failure with compensation);
* ``snapshot_cases`` — map_document_snapshot.document_render_snapshot over
  legacy documents: grouped features, whitelisted property lift, style
  merge (provider default ⊕ facies_style ⊕ layer_state), visibility,
  revision-keyed reuse, the layer_revisions prefix bridge and
  extent_for_snapshot. Content-derived revision VALUES are not frozen —
  the Python small-collection path uses the process-local hash()
  (C++ contract: deterministic digest, see ledgers/27d-decisions.md
  D-27d-07).

Determinism: every uuid4 the product would call is patched to a shared
deterministic hex counter, so compensation gesture ids are stable and
frozen into the fixture (C++ replays with an equivalent generator).

Regenerate with the oracle venv (needs PySide6 for the map_document_snapshot
import chain):
    /home/kevin/project/oracle-venvs/conv11/bin/python3 \
        tools/oracle/generate_map_document_bridge_fixtures.py
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

import paleo_workbench.mapping.edit_session_set as edit_session_set_mod  # noqa: E402
import paleo_workbench.mapping.edit_gesture_manager as edit_gesture_manager_mod  # noqa: E402
import paleo_workbench.mapping.geometry_schema as geometry_schema  # noqa: E402
import paleo_workbench.mapping.native_edit_session as native_edit_session_mod  # noqa: E402
from paleo_workbench.mapping.edit_gesture_manager import EditGestureManager  # noqa: E402
from paleo_workbench.mapping.edit_session_set import (  # noqa: E402
    EditSessionSet,
    reset_session_set,
)
from paleo_workbench.mapping.map_document_snapshot import (  # noqa: E402
    document_render_snapshot,
    extent_for_snapshot,
)
from paleo_workbench.mapping.native_edit_session import (  # noqa: E402
    NativeEditSessionController,
)
from paleo_workbench.mapping.map_styles import (  # noqa: E402
    default_style_for as _real_default_style_for,
)
from paleo_workbench.project.models import PaleoMapDocument  # noqa: E402

# ---------------------------------------------------------------------------
# Deterministic id generation
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
    geometry_schema.uuid4 = lambda: _FakeUuid4(12)


# ---------------------------------------------------------------------------
# Fake bridge stack (mirrors tests/test_topo_m1_native_editing.FakeNativeStack)
# ---------------------------------------------------------------------------


class FakeNativeStack:
    """A bridge with the M1 native editing face: records calls, fires the
    committed callback synchronously during commit."""

    def __init__(self, name="stack"):
        self.name = name
        self.editing: set[str] = set()
        self.calls: list[list] = []
        self.committed_callback = None
        self.mirror: dict[str, list[dict]] = {}
        self.pending_delta: dict[str, dict] = {}
        self.fail_commit_for: set[str] = set()
        self.dirty: dict[str, bool] = {}

    # -- M1 native edit face ------------------------------------------------
    def start_mirror_layer_editing(self, doc_id):
        self.calls.append(["start", doc_id])
        self.editing.add(doc_id)
        return ""

    def roll_back_mirror_layer(self, doc_id):
        self.calls.append(["rollback", doc_id])
        self.editing.discard(doc_id)
        return ""

    def commit_mirror_layer(self, doc_id):
        if doc_id not in self.editing:
            return "layer not editing"
        if doc_id in self.fail_commit_for:
            self.calls.append(["commit-failed", doc_id])
            return "simulated commit failure"
        self.calls.append(["commit", doc_id])
        self.editing.discard(doc_id)
        delta = self.pending_delta.pop(doc_id, {"doc_id": doc_id})
        delta["doc_id"] = doc_id
        if self.committed_callback is not None:
            self.committed_callback(doc_id, json.dumps(delta))
        return ""

    def mirror_features_json(self, doc_id, limit=0):
        return json.dumps({
            "exists": bool(doc_id in self.mirror),
            "features": self.mirror.get(doc_id, []),
        })

    def undo_mirror_edit(self, doc_id):
        self.calls.append(["undo", doc_id])
        return ""

    def redo_mirror_edit(self, doc_id):
        self.calls.append(["redo", doc_id])
        return ""

    def run_geometry_checks(self, canvas, layer_ids):
        # Capability marker: the production controller only routes through
        # the topology checker when the stack exposes this surface.
        self.calls.append(["run_geometry_checks", sorted(layer_ids)])
        return ""

    def set_committed_callback(self, canvas, callback):
        # M1 bridges carry the committed-callback surface (same shape as
        # tests/test_topo_m1_native_editing.FakeNativeStack).
        self.committed_callback = callback


class RestorableStack(FakeNativeStack):
    """A bridge that can snapshot/restore the mirror content (compensation
    path): mirror_features_json(id, 0) captures; restore puts the captured
    features back."""

    def restore_mirror_snapshot(self, doc_id, snapshot):
        self.calls.append(["restore", doc_id])
        # Production plumbing passes the snapshot through as a JSON string
        # (str(mirror_features_json(...))); parse before reading.
        payload = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
        self.mirror[doc_id] = payload.get("features", [])
        self.editing.add(doc_id)
        return ""

class OldBridgeStack(FakeNativeStack):
    """An old bridge: the native edit face methods are absent."""

    start_mirror_layer_editing = None
    commit_mirror_layer = None


class AttributeWriteStack(FakeNativeStack):
    """A bridge that additionally supports the mirror attribute-write op."""

    def set_mirror_feature_attributes(self, doc_id, ids_json, values_json):
        self.calls.append(["set_attrs", doc_id, ids_json, values_json])
        return ""


class DirtyProbeStack(FakeNativeStack):
    """A bridge with the mirror_layer_dirty query surface."""

    def __init__(self, name="stack"):
        super().__init__(name)
        self.dirty_state: dict[str, bool] = {}

    def mirror_layer_dirty(self, doc_id):
        return self.dirty_state.get(doc_id, False)


def stack_callable(obj, name):
    """Python-native capability probe over a duck-typed stack."""
    return callable(getattr(obj, name, None))


# Patch the controller module's bridge_supports to probe the fake the same
# way the production code does (getattr/callable on arbitrary objects).
def probe_bridge_supports(stack) -> bool:
    return (
        stack_callable(stack, "start_mirror_layer_editing")
        and stack_callable(stack, "commit_mirror_layer")
        and stack_callable(stack, "roll_back_mirror_layer")
        and stack_callable(stack, "mirror_features_json")
    )


native_edit_session_mod.NativeEditSessionController.bridge_supports = (
    staticmethod(probe_bridge_supports)
)


class FakeLayer:
    """ICommittedDeltaSink stand-in: records apply_committed_delta calls."""

    def __init__(self, layer_id, name="", crs=""):
        self.id = layer_id
        self.name = name or layer_id
        self.crs = crs
        self.calls: list[dict] = []

    def apply_committed_delta(self, delta, *, session_id, source_tool,
                              gestures=None):
        self.calls.append({
            "delta": delta,
            "session_id": session_id,
            "source_tool": source_tool,
            "gestures": list(gestures or []),
        })


# ---------------------------------------------------------------------------
# Case runners (each op records the observable state after it)
# ---------------------------------------------------------------------------


def run_session_set_op(subject: EditSessionSet, op: dict, results: list,
                       stacks: dict) -> None:
    kind = op["op"]
    # The op dict stays JSON-safe: "stack" is the stack NAME; the runner
    # resolves it to the identity object.
    entry: dict = {"op": dict(op)}
    if kind == "open":
        subject.open(op["layer_id"], crs=op.get("crs", ""),
                     stack=stacks.get(op["stack"]))
    elif kind == "request_join":
        gate = None
        gate_spec = op.get("gate")
        if gate_spec is not None:
            accepted = set(gate_spec.get("accepted", []))
            reasons = gate_spec.get("reason", {})

            def _gate(layer_id, _a=accepted, _r=reasons):
                if layer_id in _a:
                    return True, ""
                return False, _r.get(layer_id, "")
            gate = _gate
        decisions = subject.request_join(op["layer_ids"], gate=gate)
        entry["decisions"] = [
            {"layer_id": d.layer_id, "accepted": d.accepted, "reason": d.reason}
            for d in decisions
        ]
    elif kind == "discard":
        subject.discard(op["layer_id"])
    elif kind == "close":
        entry["closed_layers"] = list(subject.close())
    elif kind == "active_layer_ids":
        entry["active_layer_ids"] = list(
            subject.active_layer_ids(stacks.get(op["stack"])))
    elif kind == "allows_crs_change":
        allowed, reason = subject.allows_crs_change()
        entry["allowed"] = allowed
        entry["reason"] = reason
    elif kind == "allows_schema_change":
        allowed, reason = subject.allows_schema_change(op["layer_id"])
        entry["allowed"] = allowed
        entry["reason"] = reason
    else:
        raise ValueError(f"unknown session-set op {kind!r}")
    entry["state"] = session_set_state(subject)
    results.append(entry)


def session_set_state(subject: EditSessionSet) -> dict:
    allowed_crs, crs_reason = subject.allows_crs_change()
    return {
        "layer_ids": list(subject.layer_ids()),
        "is_open": subject.is_open,
        "frozen_crs": subject.frozen_crs,
        "allows_crs_change": [allowed_crs, crs_reason],
    }


def run_gesture_op(manager: EditGestureManager, op: dict, results: list) -> None:
    kind = op["op"]
    entry: dict = {"op": op}
    if kind == "finish":
        record = manager.finish(op["gesture_id"], undo_text=op["undo_text"],
                                layer_ids=op["layer_ids"])
        entry["record"] = {
            "gesture_id": record.gesture_id,
            "undo_text": record.undo_text,
            "layer_ids": list(record.layer_ids),
            "undone": record.undone,
        }
    elif kind == "undo_plan":
        entry["plan"] = list(manager.undo_plan())
    elif kind == "redo_plan":
        entry["plan"] = list(manager.redo_plan())
    elif kind == "mark_undone":
        manager.mark_undone(op["gesture_id"])
    elif kind == "mark_redone":
        manager.mark_redone(op["gesture_id"])
    elif kind == "current_gesture_id":
        entry["gesture_id"] = manager.current_gesture_id()
    elif kind == "clear":
        manager.clear()
    else:
        raise ValueError(f"unknown gesture op {kind!r}")
    entry["audit"] = manager.audit_records()
    results.append(entry)


class _Checker:
    """Bridge-driven checker (the topology.checker attribute shape)."""

    def __init__(self, issues):
        self.issues = issues

    def run_for_commit(self, stack, canvas, layer_ids):
        return list(self.issues)


class _TopologyProbe:
    """Topology gate double: bridge-checker path (when `checker` is set and
    the stack exposes run_geometry_checks) or per-layer validator."""

    def __init__(self, enabled=True, checker=None, validate_issue_map=None):
        self.enabled = enabled
        self.checker = checker
        self.validate_issue_map = validate_issue_map or {}
        self.validations: list[tuple[str, int]] = []

    def validate_records(self, layer_id, records):
        count = self.validate_issue_map.get(layer_id, 0)
        return [
            {"layer_id": layer_id, "feature_id": f"bad-{i}", "message": "err"}
            for i in range(count)
        ]

    def record_validation(self, layer, count):
        self.validations.append((getattr(layer, "id", layer), count))


def run_native_op(controller, op: dict, results: list, ctx: dict) -> None:
    kind = op["op"]
    entry: dict = {"op": kind, "args": dict(op)}
    if kind == "bridge_supports":
        entry["supported"] = controller.bridge_supports(ctx["stacks"][op["stack"]])
    elif kind == "open":
        ok, reason = controller.open(
            ctx["stacks"][op["stack"]], ctx["layers"][op["layer"]],
            gate=ctx["gates"].get(op.get("gate")), canvas_address=op.get("canvas", 0))
        entry["ok"] = ok
        entry["reason"] = reason
        entry["sessions"] = list(controller.session_layer_ids())
        stack = ctx["stacks"][op["stack"]]
        entry["bridge_editing"] = sorted(stack.editing) if hasattr(stack, "editing") else []
    elif kind == "rollback":
        ok, reason = controller.rollback(op["layer_id"])
        entry["ok"] = ok
        entry["reason"] = reason
        entry["sessions"] = list(controller.session_layer_ids())
    elif kind == "readback_features":
        records = controller.readback_features(ctx["stacks"][op["stack"]],
                                               op["layer_id"])
        entry["records"] = records
    elif kind == "set_feature_attributes":
        ok, reason = controller.set_feature_attributes(
            op["layer_id"], op["feature_ids"], op["attributes"])
        entry["ok"] = ok
        entry["reason"] = reason
    elif kind == "pending_changes":
        result = controller.pending_changes(op["layer_id"])
        entry["pending"] = None if result is None else bool(result)
    elif kind == "handle_committed":
        controller.handle_committed(op["doc_id"], op["delta"])
    elif kind == "commit_all":
        topology = None
        if op.get("topology") is not None:
            topology = ctx["topologies"][op["topology"]]
        geology = None
        if op.get("geology") is not None:
            geology = ctx["geologies"][op["geology"]]
        on_committed = None
        committed_calls: list[str] = []
        if op.get("observe_committed"):
            on_committed = lambda layer: committed_calls.append(layer.id)  # noqa: E731
        ok, reason = controller.commit_all(
            gate=ctx["gates"].get(op.get("gate")), topology=topology,
            geology=geology, on_committed=on_committed)
        entry["ok"] = ok
        entry["reason"] = reason
        entry["on_committed"] = committed_calls
        entry["sessions"] = list(controller.session_layer_ids())
        if topology is not None:
            entry["validations"] = [list(v) for v in topology.validations]
    elif kind == "undo_gesture":
        entry["ok"] = controller.undo_gesture()
    elif kind == "redo_gesture":
        entry["ok"] = controller.redo_gesture()
    elif kind == "compensations":
        entry["compensations"] = list(controller.compensations)
    else:
        raise ValueError(f"unknown native op {kind!r}")
    entry["bridge_calls"] = {name: list(stack.calls)
                             for name, stack in ctx["stacks"].items()}
    entry["layer_calls"] = {name: list(layer.calls)
                            for name, layer in ctx["layers"].items()}
    entry["session_set"] = session_set_state(
        edit_session_set_mod.SESSION_SET)
    results.append(entry)


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def default_style_for(kind: str) -> dict:
    """The REAL map_styles registry default (to_dict shape) — frozen into
    the fixture so the C++ provider seam serves byte-identical host data."""
    return json.loads(json.dumps(_real_default_style_for(kind).to_dict(),
                                 ensure_ascii=False))


def snapshot_case(case: dict) -> dict:
    install_deterministic_ids()
    provider = default_style_for
    visibility = case.get("visibility")
    records = case.get("records")
    data_revisions = case.get("data_revisions")
    layer_revisions = case.get("layer_revisions")
    raw_doc = case.get("document")
    document = None
    document_id = "map"
    if raw_doc is not None:
        payload = dict(raw_doc)
        payload.setdefault("name", "oracle")
        payload.setdefault("linked_target_horizon", "H")
        document = PaleoMapDocument(**payload)
        document_id = document.id
    snapshot = document_render_snapshot(
        document,
        project_crs=case.get("project_crs", ""),
        visibility=visibility,
        records=records,
        data_revisions=data_revisions,
        layer_revisions=layer_revisions,
    )
    layers = []
    for layer in snapshot.layers:
        kind = layer.id.split(":", 1)[-1]
        host_provided = bool(
            (data_revisions and kind in data_revisions)
            or (layer_revisions and layer.id in layer_revisions))
        layers.append({
            "id": layer.id,
            "name": layer.name,
            "layer_type": layer.layer_type,
            "extent": list(layer.extent),
            "crs": layer.crs,
            # Content-derived revisions use the process-local Python hash()
            # on the small-collection path — NOT reproducible across runs.
            # They are frozen as null; the C++ digest value is a C++ contract
            # (determinism + distinctness, see D-27d-07).
            "data_revision": layer.data_revision if host_provided else None,
            "features": [json.loads(json.dumps(f)) for f in layer.features],
            "style": layer.style,
            "visible": layer.visible,
            "opacity": layer.opacity,
        })
    return {
        "name": case["name"],
        "document_id": document_id,
        # Raw legacy-document payload (what the C++ adapter consumes; the
        # PaleoMapDocument model itself needs pydantic on the C++ side —
        # the JSON record shape IS the ported contract).
        "document": raw_doc,
        "project_crs": snapshot.project_crs,
        "visibility": visibility,
        "records": records,
        "data_revisions": data_revisions,
        "layer_revisions": layer_revisions,
        # The provider seam inputs are host data on the C++ side — freeze
        # the exact defaults the Python oracle served.
        "style_defaults": {kind: default_style_for(kind)
                           for kind in ("facies", "well", "line", "label")},
        "layers": layers,
        "full_extent": list(extent_for_snapshot(snapshot)),
    }


# ---------------------------------------------------------------------------
# Fixture build
# ---------------------------------------------------------------------------


def build_fixture() -> dict:
    fixture: dict = {"schema": "pwb.mapping_document.bridge_oracle/1"}

    # -- session set ---------------------------------------------------------
    session_set_cases = []

    def session_case(name, ops, stack_names):
        subject = EditSessionSet()
        stacks = {name: object() for name in stack_names}
        results: list[dict] = []
        for op in ops:
            run_session_set_op(subject, op, results, stacks)
        session_set_cases.append({"name": name, "stack_names": list(stacks),
                                  "results": results})

    session_case(
        "lifecycle_join_growth_and_close",
        [
            {"op": "allows_crs_change"},
            {"op": "open", "layer_id": "draft-1", "crs": "EPSG:4326",
             "stack": "pub"},
            {"op": "allows_crs_change"},
            {"op": "allows_schema_change", "layer_id": "draft-1"},
            {"op": "allows_schema_change", "layer_id": "other"},
            {"op": "request_join", "layer_ids": ["draft-1", "draft-2", "raw-1"],
             "gate": {"accepted": ["draft-2"],
                      "reason": {"raw-1": "图层角色为「原始相图（RAW）」——不可直接编辑；请创建 DERIVED 草稿后编辑"}}},
            {"op": "active_layer_ids", "stack": "pub"},
            {"op": "active_layer_ids", "stack": "other"},
            {"op": "discard", "layer_id": "draft-2"},
            {"op": "discard", "layer_id": "draft-1"},
            {"op": "allows_crs_change"},
            {"op": "open", "layer_id": "draft-3", "crs": "EPSG:3857",
             "stack": "pub"},
            {"op": "close"},
            {"op": "allows_crs_change"},
        ],
        ["pub", "other"],
    )

    session_case(
        "crs_mismatch_mutex_messages",
        [
            {"op": "open", "layer_id": "a", "crs": "EPSG:4326", "stack": "pub"},
            {"op": "allows_schema_change", "layer_id": "a"},
            {"op": "discard", "layer_id": "ghost"},
            {"op": "close"},
        ],
        ["pub"],
    )

    session_case(
        "ungated_join_accepts_everything",
        [
            {"op": "open", "layer_id": "a", "crs": "", "stack": "pub"},
            {"op": "request_join", "layer_ids": ["b", "c", "b"]},
            {"op": "close"},
        ],
        ["pub"],
    )

    fixture["session_set_cases"] = session_set_cases

    # -- gestures ------------------------------------------------------------
    gesture_cases = []

    def gesture_case(name, ops):
        manager = EditGestureManager()
        results: list[dict] = []
        for op in ops:
            run_gesture_op(manager, op, results)
        gesture_cases.append({"name": name, "results": results})

    gesture_case(
        "finish_dedup_undo_reverse_redo_forward",
        [
            {"op": "undo_plan"},
            {"op": "redo_plan"},
            {"op": "finish", "gesture_id": "g1", "undo_text": "移动顶点",
             "layer_ids": ["l1", "l2", "l1", "l3"]},
            {"op": "current_gesture_id"},
            {"op": "undo_plan"},
            {"op": "mark_undone", "gesture_id": "g1"},
            {"op": "mark_undone", "gesture_id": "g1"},
            {"op": "undo_plan"},
            {"op": "redo_plan"},
            {"op": "current_gesture_id"},
            {"op": "mark_redone", "gesture_id": "g1"},
            {"op": "mark_redone", "gesture_id": "g1"},
            {"op": "redo_plan"},
            {"op": "undo_plan"},
            {"op": "current_gesture_id"},
            {"op": "mark_undone", "gesture_id": "ghost"},
            {"op": "mark_redone", "gesture_id": "ghost"},
            {"op": "clear"},
            {"op": "undo_plan"},
            {"op": "redo_plan"},
            {"op": "current_gesture_id"},
        ],
    )

    gesture_case(
        "two_gestures_lifo_redo_and_stale_queue_prune",
        [
            {"op": "finish", "gesture_id": "g1", "undo_text": "一", "layer_ids": ["a"]},
            {"op": "finish", "gesture_id": "g2", "undo_text": "二",
             "layer_ids": ["b", "c"]},
            {"op": "undo_plan"},
            {"op": "mark_undone", "gesture_id": "g2"},
            {"op": "undo_plan"},
            {"op": "mark_undone", "gesture_id": "g1"},
            {"op": "current_gesture_id"},
            {"op": "redo_plan"},
            {"op": "mark_redone", "gesture_id": "g1"},
            {"op": "redo_plan"},
            {"op": "mark_redone", "gesture_id": "g2"},
            {"op": "redo_plan"},
        ],
    )

    fixture["gesture_cases"] = gesture_cases

    # -- native controller -----------------------------------------------------
    native_cases = []

    def square(feature_id, x0=0.0, y0=0.0):
        return {
            "id": feature_id,
            "geometry": {"type": "Polygon", "coordinates": [[
                [x0, y0], [x0 + 2.0, y0], [x0 + 2.0, y0 + 2.0],
                [x0, y0 + 2.0], [x0, y0]]]},
            "properties": {"__pwb_fid": feature_id, "name": "f"},
        }

    def native_case(name, build_ops, run_ops):
        install_deterministic_ids()
        reset_session_set()
        ctx: dict = {"stacks": {}, "layers": {}, "gates": {},
                     "topologies": {}, "geologies": {}}
        controller = NativeEditSessionController()
        results: list[dict] = []
        for spec in build_ops:
            kind = spec["kind"]
            if kind == "stack":
                cls = {"fake": FakeNativeStack, "old": OldBridgeStack,
                       "attrs": AttributeWriteStack, "dirty": DirtyProbeStack,
                       "restorable": RestorableStack}[spec.get("shape", "fake")]
                ctx["stacks"][spec["name"]] = cls(spec["name"])
                if "mirror" in spec:
                    # Deep-copy: the fakes mutate their state (restore,
                    # pop), and the spec dict is frozen into the fixture.
                    ctx["stacks"][spec["name"]].mirror = json.loads(
                        json.dumps(spec["mirror"]))
                if "pending_delta" in spec:
                    ctx["stacks"][spec["name"]].pending_delta = json.loads(
                        json.dumps(spec["pending_delta"]))
                if "fail_commit" in spec:
                    ctx["stacks"][spec["name"]].fail_commit_for = set(spec["fail_commit"])
            elif kind == "layer":
                ctx["layers"][spec["name"]] = FakeLayer(
                    spec.get("layer_id", spec["name"]), spec.get("display", ""),
                    spec.get("crs", ""))
            elif kind == "gate":
                allow = set(spec.get("allow", []))
                reason = spec.get("reason", "门禁拒绝")
                if spec.get("allow_all"):
                    ctx["gates"][spec["name"]] = lambda layer_id, _a=allow: (True, "")
                else:
                    def gate(layer_id, _a=allow, _r=reason):
                        if layer_id in _a:
                            return True, ""
                        return False, _r
                    ctx["gates"][spec["name"]] = gate
            elif kind == "topology":
                checker = None
                if spec.get("checker_issues") is not None:
                    checker = _Checker(spec["checker_issues"])
                ctx["topologies"][spec["name"]] = _TopologyProbe(
                    enabled=spec.get("enabled", True), checker=checker,
                    validate_issue_map=spec.get("validate_issues", {}))
            elif kind == "geology":
                violations = spec.get("violations", [])
                # Production violations carry attributes (.code/.message/
                # .severity/.layer_id); wrap the frozen dicts to match.
                ctx["geologies"][spec["name"]] = lambda records, _v=violations: [
                    types.SimpleNamespace(**dict(v)) for v in _v]
        for op in run_ops:
            run_native_op(controller, op, results, ctx)
        native_cases.append({"name": name, "stack_names": sorted(ctx["stacks"]),
                             # Build specs frozen so C++ reconstructs the same
                             # fakes (stack shapes/mirrors/gates/topologies).
                             "build": build_ops,
                             "results": results})
        reset_session_set()

    native_case(
        "open_gate_and_capability_matrix",
        [
            {"kind": "stack", "name": "bridge"},
            {"kind": "stack", "name": "old", "shape": "old"},
            {"kind": "stack", "name": "attrs", "shape": "attrs"},
            {"kind": "stack", "name": "probe", "shape": "dirty",
             "mirror": {"draft-p": [{"id": "p1", "geometry": {"type": "Point",
                                                        "coordinates": [0.0, 0.0]},
                                     "properties": {"__pwb_fid": "p1"}}]}},
            {"kind": "layer", "name": "raw", "layer_id": "raw-1"},
            {"kind": "layer", "name": "draft", "layer_id": "draft-1",
             "crs": "EPSG:4326"},
            {"kind": "layer", "name": "probe_layer", "layer_id": "draft-p",
             "crs": "EPSG:4326"},
            {"kind": "layer", "name": "nomirror", "layer_id": "draft-2",
             "crs": "EPSG:4326"},
            {"kind": "layer", "name": "mismatch", "layer_id": "draft-x",
             "crs": "EPSG:3857"},
            {"kind": "gate", "name": "reject_raw",
             "reason": "图层角色为「原始相图（RAW）」——不可直接编辑；请创建 DERIVED 草稿后编辑"},
            {"kind": "gate", "name": "allow_all", "allow_all": True},
        ],
        [
            {"op": "bridge_supports", "stack": "bridge"},
            {"op": "bridge_supports", "stack": "old"},
            {"op": "open", "stack": "bridge", "layer": "raw",
             "gate": "reject_raw"},
            {"op": "open", "stack": "old", "layer": "draft",
             "gate": "allow_all"},
            {"op": "open", "stack": "bridge", "layer": "draft",
             "gate": "allow_all"},
            {"op": "open", "stack": "bridge", "layer": "draft",
             "gate": "allow_all"},
            {"op": "open", "stack": "bridge", "layer": "nomirror",
             "gate": "allow_all"},
            {"op": "open", "stack": "bridge", "layer": "mismatch",
             "gate": "allow_all"},
            {"op": "open", "stack": "probe", "layer": "probe_layer",
             "gate": "allow_all"},
            {"op": "pending_changes", "layer_id": "draft-1"},
            {"op": "pending_changes", "layer_id": "draft-p"},
            {"op": "pending_changes", "layer_id": "ghost"},
            {"op": "set_feature_attributes", "layer_id": "ghost",
             "feature_ids": ["f1"], "attributes": {"a": 1}},
            {"op": "set_feature_attributes", "layer_id": "draft-1",
             "feature_ids": ["f1"], "attributes": {"a": 1}},
            {"op": "set_feature_attributes", "layer_id": "draft-1",
             "feature_ids": [], "attributes": {"a": 1}},
            {"op": "set_feature_attributes", "layer_id": "draft-1",
             "feature_ids": ["f1"], "attributes": {}},
            {"op": "set_feature_attributes", "layer_id": "draft-1",
             "feature_ids": ["f1", "f2"], "attributes": {"facies": "sand"}},
            {"op": "rollback", "layer_id": "ghost"},
            {"op": "rollback", "layer_id": "draft-p"},
            {"op": "pending_changes", "layer_id": "draft-p"},
            {"op": "rollback", "layer_id": "draft-1"},
            {"op": "compensations"},
        ],
    )

    native_case(
        "readback_normalization_and_committed_delta",
        [
            {"kind": "stack", "name": "bridge",
             "mirror": {"draft-1": [
                 {"id": "geom-id", "geometry": {"type": "Point", "coordinates": [1, 2]},
                  "properties": {"__pwb_fid": "fid-9", "k": "v"}},
                 {"id": "id-only", "geometry": {"type": "Point", "coordinates": [3, 4]},
                  "properties": {}},
                 {"geometry": None},
                 "junk",
             ]},
             "pending_delta": {"draft-1": {
                 "geometry_changes": [{"feature_id": "f1",
                                       "geometry": {"type": "Point",
                                                    "coordinates": [5.0, 6.0]}}],
                 "attribute_changes": [{"feature_id": "f1",
                                        "changes": {"facies": "clay"}}],
                 "removed": ["f2"],
                 "added": [{"id": "new-1",
                            "geometry": {"type": "Point", "coordinates": [7.0, 8.0]},
                            "properties": {"__pwb_fid": "fid-new", "name": "n"}}],
             }}},
            {"kind": "layer", "name": "draft", "layer_id": "draft-1",
             "crs": "EPSG:4326"},
            {"kind": "gate", "name": "allow_all", "allow_all": True},
        ],
        [
            {"op": "open", "stack": "bridge", "layer": "draft",
             "gate": "allow_all"},
            {"op": "readback_features", "stack": "bridge", "layer_id": "draft-1"},
            {"op": "readback_features", "stack": "bridge", "layer_id": "ghost"},
            {"op": "commit_all", "gate": "allow_all", "observe_committed": True},
            {"op": "undo_gesture"},
            {"op": "redo_gesture"},
            {"op": "compensations"},
        ],
    )

    native_case(
        "commit_gates_block_whole_set",
        [
            {"kind": "stack", "name": "bridge",
             "mirror": {"draft-1": [square("f1")],
                        "draft-2": [square("g1", 10.0)]}},
            {"kind": "layer", "name": "draft1", "layer_id": "draft-1",
             "crs": "EPSG:4326"},
            {"kind": "layer", "name": "draft2", "layer_id": "draft-2",
             "crs": "EPSG:4326"},
            {"kind": "layer", "name": "raw", "layer_id": "raw-1"},
            {"kind": "gate", "name": "reject_draft2",
             "reason": "图层角色为「原始相图（RAW）」——不可直接编辑；请创建 DERIVED 草稿后编辑"},
            {"kind": "gate", "name": "allow_all", "allow_all": True},
            {"kind": "topology", "name": "topo_bridge",
             "checker_issues": [
                 {"layer_id": "draft-2", "feature_id": "g1",
                  "message": "重叠"}, {"layer_id": "draft-2", "feature_id": "g1",
                                       "message": "悬挂"},
                 {"layer_id": "draft-1", "feature_id": "f1", "message": "伪节点"},
                 {"layer_id": "draft-1", "feature_id": "f1", "message": "四"}]},
            {"kind": "topology", "name": "topo_fallback",
             "validate_issues": {"draft-2": 1}},
            {"kind": "geology", "name": "geo_error",
             "violations": [{"layer_id": "draft-1", "code": "G-1",
                             "message": "海相缺失", "severity": "error"},
                            {"layer_id": "draft-2", "code": "G-2",
                             "message": "警告项", "severity": "warning"}]},
        ],
        [
            {"op": "open", "stack": "bridge", "layer": "raw",
             "gate": "reject_draft2"},
            {"op": "open", "stack": "bridge", "layer": "draft1",
             "gate": "allow_all"},
            {"op": "open", "stack": "bridge", "layer": "draft2",
             "gate": "allow_all"},
            {"op": "commit_all", "gate": "reject_draft2"},
            {"op": "commit_all", "gate": "allow_all", "topology": "topo_bridge"},
            {"op": "commit_all", "gate": "allow_all", "topology": "topo_fallback"},
            {"op": "commit_all", "gate": "allow_all", "geology": "geo_error"},
            {"op": "commit_all", "gate": "allow_all"},
            {"op": "compensations"},
        ],
    )

    native_case(
        "join_order_not_id_order_governs_commit",
        [
            {"kind": "stack", "name": "bridge",
             "mirror": {"zeta-9": [square("f9", 40.0)],
                        "alpha-1": [square("f1", 50.0)]}},
            {"kind": "layer", "name": "zeta", "layer_id": "zeta-9",
             "crs": "EPSG:4326"},
            {"kind": "layer", "name": "alpha", "layer_id": "alpha-1",
             "crs": "EPSG:4326"},
            {"kind": "gate", "name": "allow_all", "allow_all": True},
            {"kind": "gate", "name": "reject_alpha",
             "reason": "图层角色为「原始相图（RAW）」——不可直接编辑；请创建 DERIVED 草稿后编辑"},
        ],
        [
            {"op": "open", "stack": "bridge", "layer": "zeta",
             "gate": "allow_all"},
            {"op": "open", "stack": "bridge", "layer": "alpha",
             "gate": "allow_all"},
            # Gate re-check walks JOIN order: zeta-9 (opened first) passes,
            # alpha-1 (second) rejects — the message names alpha-1, and no
            # bridge commit has happened (all-or-nothing, gate 1).
            {"op": "commit_all", "gate": "reject_alpha"},
            # Same set, allowed: commits MUST run zeta-9 then alpha-1
            # (join order), not the lexicographic alpha-1 first.
            {"op": "commit_all", "gate": "allow_all",
             "observe_committed": True},
        ],
    )

    native_case(
        "commit_success_with_topology_off_and_warning_geology",
        [
            {"kind": "stack", "name": "bridge",
             "mirror": {"draft-1": [square("f1")],
                        "draft-2": [square("g1", 10.0)]}},
            {"kind": "layer", "name": "draft1", "layer_id": "draft-1",
             "crs": "EPSG:4326"},
            {"kind": "layer", "name": "draft2", "layer_id": "draft-2",
             "crs": "EPSG:4326"},
            {"kind": "gate", "name": "allow_all", "allow_all": True},
            {"kind": "topology", "name": "topo_off", "enabled": False},
            {"kind": "geology", "name": "geo_warn_only",
             "violations": [{"layer_id": "draft-2", "code": "G-2",
                             "message": "警告项", "severity": "warning"}]},
        ],
        [
            {"op": "open", "stack": "bridge", "layer": "draft1",
             "gate": "allow_all"},
            {"op": "open", "stack": "bridge", "layer": "draft2",
             "gate": "allow_all"},
            {"op": "commit_all", "gate": "allow_all", "topology": "topo_off",
             "geology": "geo_warn_only", "observe_committed": True},
            {"op": "compensations"},
        ],
    )

    native_case(
        "mid_commit_failure_compensates_committed_layers",
        [
            {"kind": "stack", "name": "bridge", "shape": "restorable",
             "mirror": {"draft-1": [square("f1")],
                        "draft-2": [square("g1", 10.0)],
                        "draft-3": [square("h1", 20.0)]},
             "fail_commit": ["draft-2"]},
            {"kind": "layer", "name": "draft1", "layer_id": "draft-1",
             "crs": "EPSG:4326"},
            {"kind": "layer", "name": "draft2", "layer_id": "draft-2",
             "crs": "EPSG:4326"},
            {"kind": "layer", "name": "draft3", "layer_id": "draft-3",
             "crs": "EPSG:4326"},
            {"kind": "gate", "name": "allow_all", "allow_all": True},
        ],
        [
            {"op": "open", "stack": "bridge", "layer": "draft1",
             "gate": "allow_all"},
            {"op": "open", "stack": "bridge", "layer": "draft2",
             "gate": "allow_all"},
            {"op": "open", "stack": "bridge", "layer": "draft3",
             "gate": "allow_all"},
            {"op": "commit_all", "gate": "allow_all"},
            {"op": "compensations"},
            {"op": "undo_gesture"},
            {"op": "rollback", "layer_id": "draft-2"},
            {"op": "rollback", "layer_id": "draft-1"},
            {"op": "rollback", "layer_id": "draft-3"},
        ],
    )

    fixture["native_cases"] = native_cases

    # -- render snapshots -------------------------------------------------------
    legacy_document = {
        "id": "map_1",
        "facies_style": {"fill_color": "#c8b28e"},
        "layer_state": {
            "vector_layers": [
                {"kind": "facies", "id": "map_1:facies",
                 "style": {"stroke_width": 0.8}, "labels": {"show": True}},
                {"kind": "line", "id": "map_1:line",
                 "style": {"stroke_color": "#123456"}, "labels": {}},
            ],
        },
        "facies_polygons": [
            {"id": "poly-1", "name": "sand", "facies": "sand",
             "probability": 0.8, "region_id": "r1",
             "geometry": {"type": "Polygon", "coordinates": [
                 [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [0.0, 4.0], [0.0, 0.0]],
                 [[1.0, 1.0], [2.0, 1.0], [2.0, 2.0], [1.0, 2.0], [1.0, 1.0]]]},
             "properties": {"kept": True}},
            {"id": "poly-bad", "kind": "facies", "name": "no-geometry"},
            {"id": "poly-multi", "name": "multi", "kind": "facies",
             "topology_status": "checked",
             "geometry": {"type": "MultiPolygon", "coordinates": [
                 [[[10.0, 0.0], [12.0, 0.0], [12.0, 2.0], [10.0, 2.0],
                   [10.0, 0.0]]],
                 [[[14.0, 0.0], [16.0, 0.0], [16.0, 2.0], [14.0, 2.0],
                   [14.0, 0.0]]]]}},
        ],
        "well_overlays": [
            {"id": "w-1", "name": "well-1", "x": 1.5, "y": 2.5,
             "lng": 1.5, "lat": 2.5},
            {"id": "w-bad", "name": "well-bad", "x": None, "y": None},
            {"id": "w-status", "name": "kept-status", "x": 9.0, "y": 9.0,
             "coordinate_status": "INVALID"},
        ],
        "line_features": [
            {"id": "ln-1", "name": "shore", "coordinates": [
                [0.0, 0.0], [1.0, 1.0], [2.0, 0.5]]},
            {"id": "ln-short", "name": "one-point", "coordinates": [[1.0, 1.0]]},
            {"id": "ln-mixed", "name": "mixed", "coordinates": [
                [0.0, 0.0], ["x", "y"], [5.0, 5.0]]},
        ],
        "label_features": [
            {"id": "lb-1", "text": "Alpha", "anchor": [3.0, 3.0]},
            {"id": "lb-default", "name": "BetaName", "anchor": [4.0, 4.0]},
        ],
    }

    fixture["snapshot_cases"] = [
        snapshot_case({
            "name": "grouped_layers_without_mutating_document",
            "document": legacy_document,
            "project_crs": "EPSG:4326",
        }),
        snapshot_case({
            "name": "visibility_records_override_and_revisions",
            "document": legacy_document,
            "project_crs": "EPSG:3857",
            "visibility": {"facies": False, "label": False},
            "data_revisions": {"facies": 7, "well": 3, "line": 3, "label": 3},
            "records": [
                {"id": "live-1", "kind": "facies", "name": "live",
                 "geometry": {"type": "Polygon", "coordinates": [
                     [[20.0, 20.0], [22.0, 20.0], [22.0, 22.0], [20.0, 22.0],
                      [20.0, 20.0]]]}},
            ],
        }),
        snapshot_case({
            "name": "layer_revisions_prefix_bridge",
            "document": legacy_document,
            "project_crs": "EPSG:4326",
            "layer_revisions": {"map_1:facies": 11, "other:well": 5},
        }),
        snapshot_case({
            "name": "empty_document_placeholder_extent",
            "document": {"id": "map_empty", "facies_polygons": [],
                         "well_overlays": [], "line_features": [],
                         "label_features": []},
            "project_crs": "EPSG:4326",
        }),
        snapshot_case({
            "name": "degenerate_extent_padding",
            "document": {
                "id": "map_thin",
                "facies_polygons": [
                    {"id": "pt-like", "kind": "facies", "name": "thin",
                     "geometry": {"type": "Polygon", "coordinates": [
                         [[2.0, 3.0], [2.0, 3.0], [2.0, 3.0], [2.0, 3.0]]]}},
                ],
                "well_overlays": [], "line_features": [], "label_features": [],
            },
            "project_crs": "EPSG:4326",
        }),
        snapshot_case({
            "name": "null_document_empty_snapshot",
            "document": None,
            "project_crs": "EPSG:4326",
        }),
    ]

    return fixture


def main() -> None:
    fixture = build_fixture()
    out = REPO_ROOT / ("libs/mapping_document/mapping_document_tests/"
                       "fixtures/map_document_bridge_oracle.json")
    out.write_text(json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
