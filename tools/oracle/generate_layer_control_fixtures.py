#!/usr/bin/env python3
"""Freeze the V14 layer-control oracle from the real Python product.

Covers the five Qt-free kernels ported by V14-QGIS-CONTROL into
libs/workspace:

* layer_order.py   — key primitives, assign_keys_for_order, role bands
* layer_tree.py    — snapshot model, traversal, flatten_for_render,
                     tree_from_nodes
* layer_tree_diff.py — keyed-LCS minimal op set
* source_usage.py  — version/asset reverse usage queries
* stage_state.py   — the behavior surface the controllers consume
                     (effective_group_visibility / record_* / defaults)

Outputs libs/workspace/workspace_tests/fixtures/layer_control_oracle.json.
The C++ side replays every case against the frozen expectations
(workspace_tests/oracle_replay_test.cpp); regeneration requires this
script plus the frozen Python modules (never hand-edited).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from paleo_workbench.mapping_workspace.layer_order import (  # noqa: E402
    FACTOR_ROLE_RANK,
    ROLE_BANDS,
    KeySpaceExhausted,
    assign_keys_for_order,
    band_sort_key,
    factor_role_rank,
    key_after,
    key_before,
    key_between,
    key_for_index,
    key_sequence,
    role_band,
    valid_key,
)
from paleo_workbench.mapping_workspace.layer_tree import (  # noqa: E402
    LayerTreeSnapshot,
    tree_from_nodes,
)
from paleo_workbench.mapping_workspace.layer_tree_diff import diff_trees  # noqa: E402
from paleo_workbench.mapping_workspace.source_usage import (  # noqa: E402
    usages_of_asset,
    usages_of_version,
)
from paleo_workbench.mapping_workspace.stage_state import (  # noqa: E402
    MappingWorkspaceState,
    StageViewState,
)


def key_cases() -> dict:
    index_keys = []
    for index in (0, 1, 2, 25, 26, 27, 675, 676, 1000, 100000, 8000000000):
        index_keys.append([index, key_for_index(index)])
    between = []
    for a, b in (
        ("aaaaaaab", "aaaaaaac"),   # sibling keys, one slot between
        ("a", "ab"),                # prefix pair: descend inside rest
        ("a", "c"),
        ("az", "b"),
        ("aaaaaaaz", "aaaaaaba"),
        ("y", "z"),
        ("m", "mb"),
        ("aabb", "aabbz"),
        # str_below second branch: b's tail is "a"-padded ("x" + P+"a"*k)
        ("x", "xaba"),
        ("x", "xaa"),
        ("ab", "abaaa"),
        ("zzb", "zzbaa"),
    ):
        between.append({"a": a, "b": b, "key": key_between(a, b)})
    between_exhausted = []
    for a, b in (("x", "xa"), ("abc", "abca"), ("zzb", "zzba")):
        try:
            key_between(a, b)
            raise AssertionError(f"expected exhaustion for {a},{b}")
        except KeySpaceExhausted:
            between_exhausted.append({"a": a, "b": b})
        except ValueError:
            # prefix+rest=="b" has "a"+... slots — not exhausted; keep as
            # between case instead.
            between.append({"a": a, "b": b, "key": key_between(a, b)})
    after = [{"a": a, "key": key_after(a)} for a in ("", "a", "abc", "zzzzzzzz")]
    before = [{"b": b, "key": key_before(b)}
              for b in ("b", "c", "ab", "aaaaaaac", "zaa", "baa", "abca")]
    before_exhausted = []
    for b in ("a",):
        try:
            key_before(b)
            raise AssertionError(f"expected exhaustion below {b}")
        except KeySpaceExhausted:
            before_exhausted.append(b)
    return {
        "index_keys": index_keys,
        "index_error": -1,
        "sequence_count": 6,
        "sequence_keys": key_sequence(6),
        "between": between,
        "between_exhausted": between_exhausted,
        "after": after,
        "before": before,
        "before_exhausted": before_exhausted,
        "valid": [
            {"key": "", "valid": True},
            {"key": "abc", "valid": True},
            {"key": "aaaaaaac", "valid": True},
            {"key": "aXc", "valid": False},
            {"key": "abc ", "valid": False},
        ],
    }


def assign_cases() -> list[dict]:
    cases = []

    # Fresh container: fixed-width defaults.
    cases.append({
        "name": "fresh_container_defaults",
        "ordered": ["a", "b", "c", "d"],
        "existing": {},
        "expected": {"a": "aaaaaaac", "b": "aaaaaaad",
                     "c": "aaaaaaae", "d": "aaaaaaaf"},
    })

    # All keys already consistent: LIS keeps everything.
    cases.append({
        "name": "lis_keeps_consistent_keys",
        "ordered": ["a", "b", "c"],
        "existing": {"a": "k1", "b": "k3", "c": "k5"},
        "expected": {"a": "k1", "b": "k3", "c": "k5"},
    })

    # One user drag: only the moved node gets a new midpoint key.
    cases.append({
        "name": "single_drag_midpoint",
        "ordered": ["a", "c", "b"],
        "existing": {"a": "m", "b": "n", "c": "q"},
        "expected": assign_keys_for_order(
            ["a", "c", "b"], {"a": "m", "b": "n", "c": "q"}),
    })

    # Unkeyed node between keyed keepers: midpoint chain.
    cases.append({
        "name": "unkeyed_between_keepers",
        "ordered": ["a", "x", "y", "b"],
        "existing": {"a": "r", "b": "t"},
        "expected": assign_keys_for_order(
            ["a", "x", "y", "b"], {"a": "r", "b": "t"}),
    })

    # Pending at the head (no lower bound).
    cases.append({
        "name": "pending_at_head",
        "ordered": ["x", "a", "b"],
        "existing": {"a": "s", "b": "u"},
        "expected": assign_keys_for_order(
            ["x", "a", "b"], {"a": "s", "b": "u"}),
    })

    # Pending at the tail (no upper bound).
    cases.append({
        "name": "pending_at_tail",
        "ordered": ["a", "b", "z1", "z2"],
        "existing": {"a": "s", "b": "u"},
        "expected": assign_keys_for_order(
            ["a", "b", "z1", "z2"], {"a": "s", "b": "u"}),
    })

    # Downward drag: new node must land BELOW an existing low key.
    cases.append({
        "name": "drag_below_all",
        "ordered": ["x", "lo"],
        "existing": {"lo": "lz"},
        "expected": assign_keys_for_order(["x", "lo"], {"lo": "lz"}),
    })

    # Existing keys in DISAGREEMENT with the observed order: LIS keeps the
    # longer agreeing chain, others are re-keyed.
    cases.append({
        "name": "disagree_rekeys_minority",
        "ordered": ["p", "q", "r", "s"],
        "existing": {"p": "d", "q": "c", "r": "b", "s": "a"},
        "expected": assign_keys_for_order(
            ["p", "q", "r", "s"], {"p": "d", "q": "c", "r": "b", "s": "a"}),
    })

    # None values in existing are treated as absent (no "None" key
    # injection).
    cases.append({
        "name": "none_values_filtered",
        "ordered": ["a", "b"],
        "existing": {"a": None, "b": "z"},
        "expected": assign_keys_for_order(["a", "b"], {"a": None, "b": "z"}),
    })

    # Adjacent-pair exhaustion rebalances the whole container to
    # fixed-width defaults.
    tight = {"keep1": "x", "keep2": "xa"}
    cases.append({
        "name": "exhaustion_rebalances",
        "ordered": ["keep1", "mid", "keep2"],
        "existing": tight,
        "expected": assign_keys_for_order(
            ["keep1", "mid", "keep2"], tight),
    })

    # Oversized keys (>64 chars) trigger a rebalance.
    big = {"a": "a" * 65, "b": "a" * 65 + "b"}
    cases.append({
        "name": "oversized_key_rebalances",
        "ordered": ["a", "b", "c"],
        "existing": big,
        "expected": assign_keys_for_order(["a", "b", "c"], big),
    })

    # Empty input.
    cases.append({
        "name": "empty",
        "ordered": [],
        "existing": {},
        "expected": {},
    })
    return cases


def band_cases() -> dict:
    return {
        "roles": [{"role": role, "band": band}
                  for role, band in sorted(ROLE_BANDS.items())],
        "unknown_band": role_band("no_such_role"),
        "factor_ranks": [{"role": role, "rank": rank}
                         for role, rank in FACTOR_ROLE_RANK.items()],
        "unknown_factor_rank": factor_role_rank("no_such_role"),
        "band_sort_keys": [
            {"role": role, "sub": sub, "node": node,
             "key": list(band_sort_key(role, sub, node))}
            for role, sub, node in (
                ("qc_warning", 0, "n1"),
                ("base_reference", 0, "n1"),
                ("unknown_role", 5, "n2"),
                ("factor_grid", 2, "n3"),
            )
        ],
    }


def tree_cases() -> list[dict]:
    cases = []
    doc = {
        "source": "domain",
        "children": [
            {"type": "group", "id": "phase1.initial_facies", "name": "初始相",
             "kind": "system", "expanded": True, "locked": False,
             "visible": True,
             "children": [
                 {"type": "layer", "id": "l1", "order_key": "aaaaaaac"},
                 {"type": "layer", "id": "l2"},
             ]},
            {"type": "group", "id": "user.1", "name": "我的组",
             "kind": "user", "expanded": False, "locked": True,
             "visible": False,
             "children": [
                 {"type": "group", "id": "user.2", "name": "嵌套",
                  "kind": "user", "children": [
                      {"type": "layer", "id": "l3", "order_key": "zz"}]},
                 {"type": "layer", "id": "l4"},
             ]},
            {"type": "layer", "id": "l_root", "note": ""},
        ],
    }
    snapshot = LayerTreeSnapshot.from_dict(doc)
    parent_of = {}
    for layer_id in ("l1", "l2", "l3", "l4", "l_root", "l_missing"):
        parent = snapshot.find_layer_parent(layer_id)
        if parent is None:
            if layer_id == "l_missing":
                continue  # absent: key omitted entirely
            parent_of[layer_id] = None  # root-level layer
        else:
            parent_of[layer_id] = parent.group_id
    cases.append({
        "name": "mixed_tree",
        "input": doc,
        "probes": {
            "layer_ids": list(snapshot.layer_ids_top_first()),
            "group_ids": list(snapshot.group_ids()),
            "parent_of": parent_of,
        },
        "roundtrip": snapshot.to_dict(),
        "flatten": {
            "snapshot_ids": ["l4", "l1", "l_new", "l3", "l2", "l_root"],
            "ordered": [layer.id for layer in snapshot.flatten_for_render(
                [SimpleNamespace(id=x) for x in
                 ["l4", "l1", "l_new", "l3", "l2", "l_root"]])],
        },
    })

    # Empty tree.
    empty = LayerTreeSnapshot()
    cases.append({
        "name": "empty_tree",
        "input": {"source": "domain", "children": []},
        "probes": {"layer_ids": [], "group_ids": [], "parent_of": {}},
        "roundtrip": empty.to_dict(),
        "flatten": {"snapshot_ids": ["x"], "ordered": [
            layer.id for layer in
            empty.flatten_for_render([SimpleNamespace(id="x")])]},
    })
    return cases


def tree_from_nodes_cases() -> list[dict]:
    nodes = [
        {"type": "group", "id": "phase1.initial_facies", "name": "初始相",
         "expanded": True, "children": [
             {"type": "layer", "id": "m1"},
             {"type": "group", "id": "user.deadbeef", "name": "用户组",
              "children": [{"type": "layer", "id": "m2"}]},
         ]},
        {"type": "layer", "id": "m3"},
    ]
    observed = tree_from_nodes(nodes)
    return [{
        "name": "bridge_nodes",
        "nodes": nodes,
        "roundtrip": observed.to_dict(),
        "source": observed.source,
    }]


def diff_cases() -> list[dict]:
    def case(name, current_doc, desired_doc):
        current = LayerTreeSnapshot.from_dict(current_doc)
        desired = LayerTreeSnapshot.from_dict(desired_doc)
        diff = diff_trees(current, desired)
        return {
            "name": name,
            "current": current_doc,
            "desired": desired_doc,
            "expected": {
                "creates": [{"group_id": op.group_id, "name": op.name,
                             "parent": op.parent}
                            for op in diff.group_creates],
                "removes": [op.group_id for op in diff.group_removes],
                "renames": [{"group_id": op.group_id,
                             "new_name": op.new_name}
                            for op in diff.group_renames],
                "group_moves": [{"group_id": op.group_id,
                                 "new_parent": op.new_parent,
                                 "new_index": op.new_index}
                                for op in diff.group_moves],
                "layer_moves": [{"layer_id": op.layer_id,
                                 "new_parent": op.new_parent,
                                 "new_index": op.new_index}
                                for op in diff.layer_moves],
                "states": [{"group_id": op.group_id, "kind": op.kind,
                            "value": op.value}
                           for op in diff.group_states],
            },
        }

    def group(gid, name="G", children=(), **kw):
        out = {"type": "group", "id": gid, "name": name, "kind": "system",
               "children": list(children)}
        out.update(kw)
        return out

    def layer(lid):
        return {"type": "layer", "id": lid}

    return [
        case("identical",
             {"children": [group("g1", children=[layer("a"), layer("b")])]},
             {"children": [group("g1", children=[layer("a"), layer("b")])]}),
        case("reorder_in_group_lcs_keeps_two",
             {"children": [group("g1", children=[
                 layer("a"), layer("b"), layer("c"), layer("d")])]},
             {"children": [group("g1", children=[
                 layer("a"), layer("c"), layer("b"), layer("d")])]}),
        case("cross_container_move",
             {"children": [group("g1", children=[layer("a"), layer("b")]),
                           group("g2", children=[layer("c")])]},
             {"children": [group("g1", children=[layer("a")]),
                           group("g2", children=[layer("c"), layer("b")])]}),
        case("create_remove_rename_state",
             {"children": [group("g1", name="旧名", visible=False,
                                 children=[layer("a")]),
                           group("gone", children=[layer("z")])]},
             {"children": [group("g1", name="新名", visible=True,
                                 expanded=False, children=[layer("a")]),
                           group("new", name="N", children=[])]}),
        case("group_move_between_parents",
             {"children": [group("p1", children=[
                 group("child1", name="C1", children=[layer("a")])]),
                 group("p2", children=[])]},
             {"children": [group("p1", children=[]),
                           group("p2", children=[
                               group("child1", name="C1",
                                     children=[layer("a")])])]}),
        case("root_level_reorder",
             {"children": [layer("r1"), layer("r2"), layer("r3")]},
             {"children": [layer("r2"), layer("r1"), layer("r3")]})
    ]


class FakeCatalog:
    """Duck-typed catalog for the usage oracle (records + planned errors)."""

    def __init__(self):
        self.run_inputs = {
            "run_map": ["v1", "v2"],
            "run_wide": [f"v{i}" for i in range(200)],
        }
        self.run_meta = {
            "run_map": ("export_map", "finished"),
            "run_wide": ("predict", "running"),
            "run_other": ("import", "finished"),
        }
        for i in range(120):
            self.run_meta[f"run_cap_{i}"] = (f"batch_{i}", "finished")
        self._runs_consuming = {
            "v1": ["run_map", "run_other"],
            "v2": ["run_wide"],
            "v3": [f"run_cap_{i}" for i in range(120)],
        }
        self._versions_by_asset = {"asset_1": ["v1", "v2"], "asset_2": ["v3"]}

    def get_run(self, run_id):
        if run_id not in self.run_meta:
            return None

        class _Run:
            pass
        run = _Run()
        run.id = run_id
        run.operation, run.status = self.run_meta[run_id]
        run.input_version_ids = self.run_inputs.get(run_id, [])
        return run

    def runs_consuming(self, version_id):
        return [self.get_run(rid)
                for rid in self._runs_consuming.get(version_id, [])]

    def _ensure_maps(self):
        class _Maps:
            pass
        maps = _Maps()
        # The real catalog map holds version records with .id; the oracle
        # fixture stores bare ids (the C++ seam contract).
        maps.versions_by_asset = {
            asset: tuple(SimpleNamespace(id=vid) for vid in vids)
            for asset, vids in self._versions_by_asset.items()}
        return maps


class FakeProject:
    """Duck-typed ProjectDocument (attribute access via getattr)."""

    def __init__(self, data):
        self.factor_map_tasks = [
            SimpleNamespace(**task) for task in data["factor_map_tasks"]]
        self.compilation_input_sets = data["compilation_input_sets"]
        self.map_products = [
            SimpleNamespace(**record) for record in data["map_products"]]


def usage_cases() -> dict:
    workspace_dict = {
        "schema_version": 1,
        "memberships": {
            "layer_map": {"role": "facies_boundary",
                          "source_version_id": "v1",
                          "source_asset_id": "asset_1",
                          "binding_kind": "catalog_version",
                          "created_stage": "constraint_factor"},
            "layer_direct_asset": {"role": "well_facies_prediction",
                                   "source_version_id": "v9",
                                   "source_asset_id": "asset_2"},
            "layer_fp": {"role": "fault_constraint",
                         "binding_kind": "content_fingerprint"},
        },
    }
    project_dict = {
        "factor_map_tasks": [
            {"id": "task_1", "name": "GR 网格", "grid_artifact_version_id": "v2"},
            {"id": "task_2", "grid_artifact_version_id": ""},
        ],
        "compilation_input_sets": [
            {"id": "set_1", "name": "最终编图输入", "frozen": True,
             "entries": [{"pinned_version_id": "v1"},
                         {"pinned_version_id": "v3",
                          "resolved_asset_id": "asset_2"}]},
            {"id": "set_2", "entries": [{"pinned_version_id": "v2"}]},
        ],
        "map_products": [
            {"id": "prod_1", "product_name": "P1", "output_version_id": "v3",
             "run_id": "run_map", "lifecycle": "published"},
            {"id": "prod_2", "product_name": "", "output_version_id": "v0",
             "run_id": "run_map", "lifecycle": ""},
        ],
    }
    catalog = FakeCatalog()
    workspace = MappingWorkspaceState.from_dict(workspace_dict)
    project = FakeProject(project_dict)
    version_queries = []
    for vid, include_runs, with_project in (
            ("v1", True, True), ("v2", True, True), ("v3", True, True),
            ("v9", True, True), ("missing", True, False), ("", True, True),
            ("v1", False, True)):
        report = usages_of_version(
            vid, workspace=workspace,
            project=project if with_project else None,
            catalog=catalog, include_runs=include_runs)
        version_queries.append({
            "version_id": vid,
            "include_runs": include_runs,
            "with_project": with_project,
            "expected": [u.__dict__ for u in report.usages],
            "truncated": report.truncated,
        })
    asset_queries = []
    for aid, with_catalog, with_project in (
            ("asset_1", True, True), ("asset_2", True, True),
            ("asset_none", True, True), ("", True, True),
            ("asset_1", False, True), ("asset_1", False, False)):
        report = usages_of_asset(
            aid, workspace=workspace,
            project=project if with_project else None,
            catalog=catalog if with_catalog else None)
        asset_queries.append({
            "asset_id": aid,
            "with_catalog": with_catalog,
            "with_project": with_project,
            "expected": [u.__dict__ for u in report.usages],
        })
    return {
        # NOTE: expected usages are in Python's natural collection order;
        # the C++ replay compares them SORTED by (kind, ref_id, version_id)
        # — iteration order of the underlying containers is not a frozen
        # contract (Python dict insertion order vs std::map key order).
        "workspace": workspace_dict,
        "project": project_dict,
        "catalog": {
            "run_inputs": catalog.run_inputs,
            "runs_consuming": catalog._runs_consuming,
            "versions_by_asset": catalog._versions_by_asset,
            "run_meta": {rid: list(meta)
                         for rid, meta in catalog.run_meta.items()},
        },
        "version_queries": version_queries,
        "asset_queries": asset_queries,
    }


def stage_view_cases() -> dict:
    view_input = {
        "stage": "constraint_factor",
        "group_visibility": {"g1": True, "g2": None, "g3": False},
        "layer_opacity": {"l1": 0.3, "l2": 2.0},
        "customized": False,
    }
    defaults = {"g1": False, "g2": True, "g4": True}
    view = StageViewState.from_dict(view_input)
    ops = [
        {"kind": "group_visibility", "id": "gA", "value": True},
        {"kind": "layer_visibility", "id": "l1", "value": False},
        {"kind": "layer_opacity", "id": "l1", "value": 0.03},
        {"kind": "layer_opacity", "id": "l2", "value": 5.0},
    ]
    recorder = StageViewState.from_dict({"stage": "constraint_factor"})
    for op in ops:
        if op["kind"] == "group_visibility":
            recorder.record_group_visibility(op["id"], op["value"])
        elif op["kind"] == "layer_visibility":
            recorder.record_layer_visibility(op["id"], op["value"])
        else:
            recorder.record_layer_opacity(op["id"], op["value"])
    reset_input = {
        "stage": "constraint_factor",
        "group_visibility": {"g1": True},
        "layer_visibility": {"l1": False},
        "layer_opacity": {"l1": 0.5},
        "customized": True,
    }
    reset_view = StageViewState.from_dict(reset_input)
    reset_view.reset_to_defaults()
    reset_defaults = {"g0": False}
    return {
        "effective": {
            "view": view_input,
            "defaults": defaults,
            "expected": dict(view.effective_group_visibility(defaults)),
        },
        "records": {
            "ops": ops,
            "effective_defaults": {},
            "expected_effective":
                dict(recorder.effective_group_visibility({})),
            "expected_visibility":
                {k: v for k, v in recorder.layer_visibility.items()
                 if v is not None},
            "expected_opacity":
                {k: v for k, v in recorder.layer_opacity.items()
                 if v is not None},
            "customized": recorder.customized,
        },
        "reset": {
            "view": reset_input,
            "defaults": reset_defaults,
            "expected_effective":
                dict(reset_view.effective_group_visibility(reset_defaults)),
            "customized": reset_view.customized,
        },
    }


def main() -> int:
    oracle = {
        "schema": "pwb.workspace.layer_control.oracle/1",
        "expectation_source": "python-product",
        "key_cases": key_cases(),
        "assign_cases": assign_cases(),
        "band_cases": band_cases(),
        "tree_cases": tree_cases(),
        "tree_from_nodes_cases": tree_from_nodes_cases(),
        "diff_cases": diff_cases(),
        "usage_cases": usage_cases(),
        "stage_view_cases": stage_view_cases(),
    }
    out = ROOT / "libs/workspace/workspace_tests/fixtures/layer_control_oracle.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(oracle, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
