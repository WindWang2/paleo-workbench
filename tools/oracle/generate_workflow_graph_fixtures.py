#!/usr/bin/env python3
"""Generate the frozen dependency_graph + interpretation/evidence oracle for
CONV-25.

Drives the REAL Python implementation and freezes: graph rebuild indexes,
cycle detection, downstream traversals, reuse matching, topological order
(incl. synthetic task edges), selector format/parse, every resolve_* status
branch (catalog/workspace/constraint seams stubbed per D7), and
available_evidence listings.

Deterministic: re-run must be byte-identical (CI checks the diff).
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.catalog.types import DataRunRef, DataVersionRef  # noqa: E402
from paleo_workbench.workflow.dependency_graph import (  # noqa: E402
    DependencyGraph,
)
from paleo_workbench.workflow.interpretation.evidence import (  # noqa: E402
    EvidenceKind,
    EvidenceSelector,
    available_evidence,
    format_evidence_selector,
    parse_evidence_selector,
    resolve_evidence,
)

FIXTURE = (
    ROOT
    / "libs/workflow_graph/workflow_graph_tests/fixtures/workflow_graph_oracle.json"
)

cases: list[dict] = []


def add(cid: str, fn: str, inp: dict, expect: dict) -> None:
    cases.append({"id": cid, "fn": fn, "input": inp, "expect": expect})


def capture(fn, *args, **kwargs):
    try:
        return {"result": fn(*args, **kwargs)}
    except Exception as exc:  # noqa: BLE001 — freeze class + message verbatim
        return {"raise": {"python_class": type(exc).__name__, "message": str(exc)}}


def ns(**kw):
    """Record-position object -> SimpleNamespace (dict leaves stay dict)."""
    out = types.SimpleNamespace()
    for k, v in kw.items():
        setattr(out, k, v)
    return out


def make_run(spec: dict) -> DataRunRef:
    return DataRunRef(
        run_id=spec["run_id"],
        operation=spec.get("operation", ""),
        input_version_ids=spec.get("input_version_ids"),
        output_version_ids=spec.get("output_version_ids"),
        parameters=spec.get("parameters"),
        generator_version=spec.get("generator_version"),
        status=spec.get("status", "running"),
        started_at=spec.get("started_at", "2026-01-01T00:00:00"),
        finished_at=spec.get("finished_at"),
        domain_task_id=spec.get("domain_task_id"),
        input_snapshot_hash=spec.get("input_snapshot_hash"),
    )


def make_version(spec: dict) -> DataVersionRef:
    return DataVersionRef(
        asset_id=spec["asset_id"],
        version_id=spec["version_id"],
        name=spec.get("name", ""),
        producing_run_id=spec.get("producing_run_id"),
        created_at=spec.get("created_at", "2026-01-01T00:00:00"),
    )


class _Catalog:
    """Duck-typed catalog: list_versions/list_runs (+ resolve_version when
    given a versions map; raise_mode makes it throw)."""

    def __init__(self, versions=None, runs=None, resolve_map=None, raises=False):
        self._versions = versions or []
        self._runs = runs or []
        self._resolve = resolve_map or {}
        self._raises = raises

    def list_versions(self):
        return list(self._versions)

    def list_runs(self):
        return list(self._runs)

    def resolve_version(self, version_id):
        if self._raises:
            raise RuntimeError("catalog backend exploded")
        return self._resolve.get(version_id)


def make_catalog(spec):
    """input.catalog spec: None | {"resolve": {vid: {...}}, "raise": true}."""
    if spec is None:
        return None
    resolve_map = {
        vid: ns(**info) for vid, info in (spec.get("resolve") or {}).items()
    }
    return _Catalog(resolve_map=resolve_map, raises=bool(spec.get("raise")))


def make_graph(versions_spec, runs_spec) -> DependencyGraph:
    catalog = _Catalog(
        versions=[make_version(v) for v in versions_spec],
        runs=[make_run(r) for r in runs_spec],
    )
    return DependencyGraph.from_catalog(catalog)


def freeze_graph(g: DependencyGraph) -> dict:
    return {
        "producing_run": dict(g.producing_run),
        "consumers": {k: list(v) for k, v in g.consumers.items()},
        "run_inputs": {k: list(v) for k, v in g.run_inputs.items()},
        "run_outputs": {k: list(v) for k, v in g.run_outputs.items()},
        "version_asset": dict(g.version_asset),
        "asset_versions": {k: list(v) for k, v in g.asset_versions.items()},
        "domain_task_runs": {k: list(v) for k, v in g.domain_task_runs.items()},
        "edges": [
            [e.source_version_id, e.run_id, e.target_version_id, e.operation]
            for e in g.edges
        ],
        "cycle_nodes": sorted(g.cycle_nodes),
        "has_cycle": g.has_cycle(),
    }


# ---------------------------------------------------------------------------
# dependency_graph — rebuild + indexes
# ---------------------------------------------------------------------------

V_BASIC = [
    {"version_id": "v1", "asset_id": "a1"},
    {"version_id": "v2", "asset_id": "a1"},
    {"version_id": "v3", "asset_id": "a2", "producing_run_id": "r2"},
    {"version_id": "v4", "asset_id": "a2"},
]
R_BASIC = [
    {"run_id": "r1", "operation": "idw", "input_version_ids": ["v1"],
     "output_version_ids": ["v2"], "status": "complete",
     "domain_task_id": "task-x", "started_at": "2026-01-01T01:00:00"},
    {"run_id": "r2", "operation": "factor_fusion", "input_version_ids": ["v2"],
     "output_version_ids": ["v3", "v4"], "status": "complete",
     "domain_task_id": "task-y", "started_at": "2026-01-01T02:00:00"},
    {"run_id": "r3", "operation": "map_compile", "input_version_ids": ["v3"],
     "output_version_ids": [], "status": "running",
     "domain_task_id": "task-x", "started_at": "2026-01-01T03:00:00"},
]

for cid, vs, rs in [
    ("graph_basic", V_BASIC, R_BASIC),
    ("graph_empty", [], []),
    ("graph_orphan_runs", [], [
        {"run_id": "r1", "operation": "op", "input_version_ids": ["ghost"],
         "output_version_ids": ["ghost2"]},
    ]),
    ("graph_self_loop", [{"version_id": "v1", "asset_id": "a1"}], [
        {"run_id": "r1", "operation": "op", "input_version_ids": ["v1"],
         "output_version_ids": ["v1"]},
    ]),
    ("graph_two_cycle", [
        {"version_id": "v1", "asset_id": "a1"},
        {"version_id": "v2", "asset_id": "a1"},
    ], [
        {"run_id": "r1", "operation": "op", "input_version_ids": ["v1"],
         "output_version_ids": ["v2"]},
        {"run_id": "r2", "operation": "op", "input_version_ids": ["v2"],
         "output_version_ids": ["v1"]},
    ]),
    ("graph_mixed_cycle", [
        {"version_id": f"v{i}", "asset_id": "a"} for i in range(1, 5)
    ], [
        {"run_id": "r1", "operation": "op", "input_version_ids": ["v1"],
         "output_version_ids": ["v2"]},
        {"run_id": "r2", "operation": "op", "input_version_ids": ["v2"],
         "output_version_ids": ["v3"]},
        {"run_id": "r3", "operation": "op", "input_version_ids": ["v3"],
         "output_version_ids": ["v2"]},
        {"run_id": "r4", "operation": "op", "input_version_ids": ["v3"],
         "output_version_ids": ["v4"]},
    ]),
    ("graph_dup_edges", V_BASIC, [
        {"run_id": "r1", "operation": "op", "input_version_ids": ["v1", "v1"],
         "output_version_ids": ["v2", "v2"]},
    ]),
    ("graph_producing_first", [
        {"version_id": "v1", "asset_id": "a1", "producing_run_id": "declared"},
    ], [
        {"run_id": "r1", "operation": "op", "input_version_ids": [],
         "output_version_ids": ["v1"]},
        {"run_id": "r2", "operation": "op", "input_version_ids": [],
         "output_version_ids": ["v1"]},
    ]),
    # #1340: duplicated run_id — dict semantics: first-key order kept, LAST
    # record stored (status/outputs come from the second row).
    ("graph_dup_run", [
        {"version_id": "v1", "asset_id": "a1"},
    ], [
        {"run_id": "r1", "operation": "op", "input_version_ids": ["v1"],
         "output_version_ids": ["v2"], "status": "failed",
         "started_at": "2026-01-01T01:00:00"},
        {"run_id": "r1", "operation": "op", "input_version_ids": ["v1"],
         "output_version_ids": ["v3"], "status": "complete",
         "started_at": "2026-01-01T02:00:00"},
    ]),
    # #1340: duplicated version_id — last record wins for version()/
    # version_asset; declared producing_run_id from the winning row applies;
    # asset_versions still accumulates one entry per listing row.
    ("graph_dup_version", [
        {"version_id": "v1", "asset_id": "a1"},
        {"version_id": "v1", "asset_id": "a2", "producing_run_id": "rx"},
    ], []),
    # #1340: setdefault — a version_id first SEEN with an empty declared
    # producer must NOT be overwritten by the run-output producer.
    ("graph_producing_empty_declared", [
        {"version_id": "v1", "asset_id": "a1", "producing_run_id": ""},
    ], [
        {"run_id": "r1", "operation": "op", "input_version_ids": [],
         "output_version_ids": ["v1"]},
    ]),
]:
    add(cid, "graph_rebuild", {"versions": vs, "runs": rs},
        capture(lambda v=vs, r=rs: freeze_graph(make_graph(v, r))))

# #1342: a >=3-node cycle — membership is traversal-order dependent (Python
# iterates a hash-randomised set), so freeze has_cycle + non-emptiness only;
# the harness treats the literal "*" as "assert nonempty, skip set compare".
_THREE_CYCLE_V = [{"version_id": f"v{i}", "asset_id": "a"}
                  for i in range(1, 4)]
_THREE_CYCLE_R = [
    {"run_id": "r1", "operation": "op", "input_version_ids": ["v1"],
     "output_version_ids": ["v2"]},
    {"run_id": "r2", "operation": "op", "input_version_ids": ["v2"],
     "output_version_ids": ["v3"]},
    {"run_id": "r3", "operation": "op", "input_version_ids": ["v3"],
     "output_version_ids": ["v1"]},
]
_3c = capture(lambda: freeze_graph(
    make_graph(_THREE_CYCLE_V, _THREE_CYCLE_R)))
_3c["result"]["cycle_nodes"] = "*"
add("graph_three_cycle", "graph_rebuild",
    {"versions": _THREE_CYCLE_V, "runs": _THREE_CYCLE_R}, _3c)

# #1344: rebuild() must fully reset state — the graph object is reusable.
def rebuild_twice(inp):
    g = make_graph(inp["versions"], inp["runs"])
    g.rebuild(_Catalog(
        versions=[make_version(v) for v in inp.get("versions2",
                                                   inp["versions"])],
        runs=[make_run(r) for r in inp.get("runs2", inp["runs"])]))
    return freeze_graph(g)


_RB2 = {"versions": V_BASIC, "runs": R_BASIC,
        "versions2": [{"version_id": "w1", "asset_id": "b1"}],
        "runs2": [{"run_id": "rw", "operation": "op",
                   "input_version_ids": ["w1"],
                   "output_version_ids": ["w2"]}]}
add("graph_rebuild_twice", "graph_rebuild_twice", _RB2,
    capture(lambda: rebuild_twice(_RB2)))


# ---------------------------------------------------------------------------
# graph queries
# ---------------------------------------------------------------------------

for cid, vid in [
    ("ddr_v2", "v2"), ("ddr_none", "v9"), ("ddr_v1", "v1"),
]:
    add(cid, "direct_downstream", {"versions": V_BASIC, "runs": R_BASIC,
                                   "version_id": vid},
        capture(lambda v=vid: [r.run_id for r in
                               make_graph(V_BASIC, R_BASIC)
                               .direct_downstream_runs(v)]))

for cid, roots, maxn in [
    ("tdr_v1", ["v1"], 100000),
    ("tdr_multi", ["v2", "v3"], 100000),
    ("tdr_empty", [], 100000),
    ("tdr_blank", ["", None], 100000),
    ("tdr_cycle", ["v1"], 100000),
    ("tdr_capped", ["v1"], 2),
    ("tdr_orphan", ["ghost"], 100000),
]:
    vs, rs = (V_BASIC, R_BASIC)
    if cid == "tdr_cycle":
        vs = [{"version_id": "v1", "asset_id": "a"},
              {"version_id": "v2", "asset_id": "a"}]
        rs = [{"run_id": "r1", "operation": "op", "input_version_ids": ["v1"],
               "output_version_ids": ["v2"]},
              {"run_id": "r2", "operation": "op", "input_version_ids": ["v2"],
               "output_version_ids": ["v1"]}]
    if cid == "tdr_orphan":
        rs = [{"run_id": "r1", "operation": "op",
               "input_version_ids": ["ghost"], "output_version_ids": ["o"]}]
    add(cid, "transitive_runs",
        {"versions": vs, "runs": rs, "version_ids": roots, "max_nodes": maxn},
        capture(lambda v=vs, r=rs, ro=roots, m=maxn:
                [x.run_id for x in make_graph(v, r)
                 .transitive_downstream_runs(ro, max_nodes=m)]))

for cid, roots in [("tdv_v1", ["v1"]), ("tdv_none", ["ghost"])]:
    add(cid, "transitive_versions",
        {"versions": V_BASIC, "runs": R_BASIC, "version_ids": roots},
        capture(lambda ro=roots: make_graph(V_BASIC, R_BASIC)
                .transitive_downstream_versions(ro)))

for cid, tid in [("latest_x", "task-x"), ("latest_y", "task-y"),
                 ("latest_none", "task-z")]:
    add(cid, "latest_run", {"versions": V_BASIC, "runs": R_BASIC, "task_id": tid},
        capture(lambda t=tid: (lambda r: r.run_id if r else None)(
            make_graph(V_BASIC, R_BASIC).latest_run_for_domain_task(t))))

for cid, vid in [("asset_v1", "v1"), ("asset_ghost", "v9")]:
    add(cid, "asset_id_for", {"versions": V_BASIC, "runs": R_BASIC,
                              "version_id": vid},
        capture(lambda v=vid: make_graph(V_BASIC, R_BASIC).asset_id_for(v)))


# ---------------------------------------------------------------------------
# find_reuse_run
# ---------------------------------------------------------------------------

R_REUSE = [
    {"run_id": "old", "operation": "idw", "input_version_ids": ["v1"],
     "output_version_ids": ["v2"], "status": "complete",
     "generator_version": "g1", "input_snapshot_hash": "h1",
     "parameters": {"power": 2, "radius": 500},
     "started_at": "2026-01-01T01:00:00"},
    {"run_id": "mid", "operation": "idw", "input_version_ids": ["v1"],
     "output_version_ids": [], "status": "complete",
     "generator_version": "g1", "input_snapshot_hash": "h1",
     "parameters": {"power": 2},
     "started_at": "2026-01-01T02:00:00"},
    {"run_id": "new", "operation": "idw", "input_version_ids": ["v1"],
     "output_version_ids": ["v9"], "status": "failed",
     "generator_version": "g1",
     "started_at": "2026-01-01T03:00:00"},
    {"run_id": "newer", "operation": "idw", "input_version_ids": ["v1"],
     "output_version_ids": ["v8"], "status": "completed",
     "generator_version": "g2", "input_snapshot_hash": "h1",
     "parameters": {"power": 2, "extra": "x"},
     "started_at": "2026-01-01T04:00:00"},
]

for cid, kw in [
    ("reuse_latest_wins", {"operation": "idw", "input_version_ids": ["v1"],
                           "require_outputs": False}),
    ("reuse_outputs_req", {"operation": "idw", "input_version_ids": ["v1"]}),
    ("reuse_gv_match", {"operation": "idw", "input_version_ids": ["v1"],
                        "generator_version": "g1"}),
    ("reuse_gv_none", {"operation": "idw", "input_version_ids": ["v1"],
                       "generator_version": "g2"}),
    ("reuse_hash", {"operation": "idw", "input_version_ids": ["v1"],
                    "input_snapshot_hash": "h1"}),
    ("reuse_hash_miss", {"operation": "idw", "input_version_ids": ["v1"],
                         "input_snapshot_hash": "hX"}),
    ("reuse_params_subset", {"operation": "idw", "input_version_ids": ["v1"],
                             "parameters": {"power": 2}}),
    ("reuse_params_miss", {"operation": "idw", "input_version_ids": ["v1"],
                           "parameters": {"power": 3}}),
    ("reuse_params_extra", {"operation": "idw", "input_version_ids": ["v1"],
                            "parameters": {"power": 2, "extra": "x"},
                            "generator_version": "g2"}),
    ("reuse_wrong_op", {"operation": "kriging", "input_version_ids": ["v1"]}),
    ("reuse_wrong_inputs", {"operation": "idw", "input_version_ids": ["v2"]}),
    ("reuse_input_order", {"operation": "idw", "input_version_ids": ["v1", "v2"]}),
    ("reuse_none", {"operation": "noop", "input_version_ids": []}),
]:
    add(cid, "find_reuse_run", {"versions": V_BASIC, "runs": R_REUSE, "query": kw},
        capture(lambda k=kw: (lambda r: r.run_id if r else None)(
            make_graph(V_BASIC, R_REUSE).find_reuse_run(**k))))

# #1340: duplicated run_id — runs.values() keeps only the LAST record; the
# failed duplicate must hide the earlier complete row entirely.
R_REUSE_DUP = [
    {"run_id": "dup", "operation": "idw", "input_version_ids": ["v1"],
     "output_version_ids": ["v9"], "status": "complete",
     "started_at": "2026-01-01T01:00:00"},
    {"run_id": "dup", "operation": "idw", "input_version_ids": ["v1"],
     "output_version_ids": ["v9"], "status": "failed",
     "started_at": "2026-01-01T02:00:00"},
]
add("reuse_dup_last_wins", "find_reuse_run",
    {"versions": V_BASIC, "runs": R_REUSE_DUP,
     "query": {"operation": "idw", "input_version_ids": ["v1"]}},
    capture(lambda: (lambda r: r.run_id if r else None)(
        make_graph(V_BASIC, R_REUSE_DUP)
        .find_reuse_run(operation="idw", input_version_ids=["v1"]))))


# ---------------------------------------------------------------------------
# topological_runs
# ---------------------------------------------------------------------------

R_CHAIN = [
    {"run_id": "ra", "operation": "idw", "input_version_ids": ["v1"],
     "output_version_ids": ["v2"], "domain_task_id": "t-a",
     "started_at": "2026-01-01T01:00:00"},
    {"run_id": "rb", "operation": "fuse", "input_version_ids": ["v2"],
     "output_version_ids": ["v3"], "domain_task_id": "t-b",
     "started_at": "2026-01-01T02:00:00"},
    {"run_id": "rc", "operation": "map_compile", "input_version_ids": ["v3"],
     "output_version_ids": ["v4"], "domain_task_id": "t-c",
     "started_at": "2026-01-01T03:00:00"},
]
R_DIAMOND = [
    {"run_id": "r1", "operation": "op", "input_version_ids": ["v0"],
     "output_version_ids": ["v1", "v2"]},
    {"run_id": "r2", "operation": "op", "input_version_ids": ["v1"],
     "output_version_ids": ["v3"]},
    {"run_id": "r3", "operation": "op", "input_version_ids": ["v2"],
     "output_version_ids": ["v4"]},
    {"run_id": "r4", "operation": "op", "input_version_ids": ["v3", "v4"],
     "output_version_ids": ["v5"]},
]
R_SUBSET_CYCLE = [
    {"run_id": "r1", "operation": "op", "input_version_ids": ["v1"],
     "output_version_ids": ["v2"]},
    {"run_id": "r2", "operation": "op", "input_version_ids": ["v2"],
     "output_version_ids": ["v1"]},
    {"run_id": "r3", "operation": "op", "input_version_ids": ["v9"],
     "output_version_ids": ["v8"]},
]
R_SYNTH = [
    {"run_id": "pred", "operation": "predict", "input_version_ids": [],
     "output_version_ids": [], "domain_task_id": "t-pred",
     "started_at": "2026-01-02T00:00:00"},
    {"run_id": "pred_old", "operation": "predict", "input_version_ids": [],
     "output_version_ids": [], "domain_task_id": "t-pred",
     "started_at": "2026-01-01T00:00:00"},
    {"run_id": "mc", "operation": "map_compile", "input_version_ids": [],
     "output_version_ids": ["vm"], "domain_task_id": "t-map",
     "parameters": {"linked_prediction_task_id": "t-pred",
                    "source_task_ids": ["t-factor"]},
     "started_at": "2026-01-03T00:00:00"},
    {"run_id": "fac", "operation": "idw", "input_version_ids": [],
     "output_version_ids": [], "domain_task_id": "t-factor",
     "started_at": "2026-01-01T12:00:00"},
]

for cid, vs, rs, ids, tc in [
    ("topo_chain", V_BASIC, R_CHAIN, ["rc", "ra", "rb"], None),
    ("topo_single", V_BASIC, R_CHAIN, ["rb"], None),
    ("topo_unknown", V_BASIC, R_CHAIN, ["ghost"], None),
    ("topo_diamond", V_BASIC, R_DIAMOND, ["r4", "r3", "r2", "r1"], None),
    ("topo_subset_cycle", V_BASIC, R_SUBSET_CYCLE, ["r1", "r2"], None),
    ("topo_cycle_outside", V_BASIC, R_SUBSET_CYCLE, ["r3"], None),
    ("topo_synth", V_BASIC, R_SYNTH, ["mc", "pred", "fac", "pred_old"], None),
    ("topo_synth_tc", V_BASIC, R_SYNTH, ["mc", "fac"],
     {"t-map": {"t-factor", "t-pred"}}),
    ("topo_synth_reach_guard", V_BASIC, [
        {"run_id": "r1", "operation": "op", "input_version_ids": ["v1"],
         "output_version_ids": ["v2"], "domain_task_id": "t-a"},
        {"run_id": "r2", "operation": "map_compile",
         "input_version_ids": ["v2"], "output_version_ids": ["v3"],
         "domain_task_id": "t-b",
         "parameters": {"linked_prediction_task_id": "t-a"}},
    ], ["r1", "r2"], None),
    # #1343 item 3: str(1.0) == "1.0" — a float task id must bind to the
    # domain task literally named "1.0" (the old %g path produced "1").
    ("topo_synth_float_tid", V_BASIC, [
        {"run_id": "rp", "operation": "predict", "input_version_ids": [],
         "output_version_ids": [], "domain_task_id": "1.0",
         "started_at": "2026-01-01T01:00:00"},
        {"run_id": "mc", "operation": "map_compile",
         "input_version_ids": [], "output_version_ids": ["vm"],
         "domain_task_id": "t-map",
         "parameters": {"linked_prediction_task_id": 1.0},
         "started_at": "2026-01-02T00:00:00"},
    ], ["mc", "rp"], None),
    # #1343 item 4: iterating a dict source_task_ids yields its KEYS.
    ("topo_synth_dict_src", V_BASIC, [
        {"run_id": "ra", "operation": "idw", "input_version_ids": [],
         "output_version_ids": [], "domain_task_id": "t-a",
         "started_at": "2026-01-01T01:00:00"},
        {"run_id": "rb", "operation": "idw", "input_version_ids": [],
         "output_version_ids": [], "domain_task_id": "t-b",
         "started_at": "2026-01-01T01:30:00"},
        {"run_id": "mc", "operation": "map_compile",
         "input_version_ids": [], "output_version_ids": ["vm"],
         "domain_task_id": "t-map",
         "parameters": {"source_task_ids": {"t-b": 1, "t-a": 2}},
         "started_at": "2026-01-02T00:00:00"},
    ], ["mc", "ra", "rb"], None),
    # #1343 item 4: a truthy non-iterable scalar makes `for s in 5` raise
    # TypeError — propagate, never swallow.
    ("topo_synth_scalar_src", V_BASIC, [
        {"run_id": "mc", "operation": "map_compile",
         "input_version_ids": [], "output_version_ids": ["vm"],
         "domain_task_id": "t-map",
         "parameters": {"source_task_ids": 5},
         "started_at": "2026-01-02T00:00:00"},
    ], ["mc"], None),
]:
    add(cid, "topological_runs",
        {"versions": vs, "runs": rs, "run_ids": ids,
         "task_consumers": {k: sorted(v) for k, v in (tc or {}).items()} or None},
        capture(lambda v=vs, r=rs, i=ids, t=tc:
                [x.run_id for x in make_graph(v, r)
                 .topological_runs(i, task_consumers=t)]))


# ---------------------------------------------------------------------------
# evidence — format / parse
# ---------------------------------------------------------------------------

for cid, kw in [
    ("fmt_draft", {"kind": "phase1_draft", "ref_id": "layer-9"}),
    ("fmt_factor", {"kind": "factor", "ref_id": "task-1"}),
    ("fmt_factor_ver", {"kind": "factor", "ref_id": "task-1",
                        "version_id": "ver_abc"}),
    ("fmt_pred", {"kind": "prediction", "ref_id": "p1"}),
    ("fmt_pred_ver", {"kind": "prediction", "ref_id": "p1",
                      "version_id": "v9"}),
    ("fmt_cg_float", {"kind": "constraint_group", "ref_id": "g",
                      "floating": True}),
    ("fmt_cg_bare", {"kind": "constraint_group", "ref_id": "",
                     "version_id": ""}),
    ("fmt_cg_named", {"kind": "constraint_group", "ref_id": "断层组"}),
    ("fmt_cg_named_ver", {"kind": "constraint_group", "ref_id": "断层组",
                          "version_id": "ver_1"}),
    ("fmt_cg_current", {"kind": "constraint_group", "ref_id": "current"}),
    ("fmt_cg_current_ver", {"kind": "constraint_group", "ref_id": "current",
                            "version_id": "ver_1"}),
    ("fmt_ver", {"kind": "catalog_version", "ref_id": "ver_x"}),
    ("fmt_ver_ver", {"kind": "catalog_version", "ref_id": "",
                     "version_id": "ver_y"}),
    ("fmt_kind_str", {"kind": "factor", "ref_id": 123, "version_id": None}),
]:
    add(cid, "format_selector", kw,
        capture(lambda k=kw: format_evidence_selector(
            k["kind"], k.get("ref_id", ""), k.get("version_id", ""),
            floating=k.get("floating", False))))

for cid, text in [
    ("parse_draft", "draft:layer-9"),
    ("parse_draft_colons", "draft:layer:with:colons"),
    ("parse_draft_empty", "draft:"),
    ("parse_factor", "factor:task-1"),
    ("parse_factor_ver", "factor:task-1:ver_abc"),
    ("parse_factor_trail", "factor:task-1:"),
    ("parse_factor_extra", "factor:a:b:c"),
    ("parse_factor_empty", "factor:"),
    ("parse_pred", "prediction:p1"),
    ("parse_pred_ver", "prediction:p1:v9"),
    ("parse_cg_current", "constraints:current"),
    ("parse_cg_named", "constraints:断层组"),
    ("parse_cg_ver", "constraints:g1:ver_2"),
    ("parse_cg_empty", "constraints:"),
    ("parse_ver", "version:ver_abc"),
    ("parse_ver_empty", "version:"),
    ("parse_bare_ver", "ver_0123456789"),
    ("parse_bare_dver", "dver_x"),
    ("parse_bare_uuid", "01234567-89ab-cdef-0123-456789abcdef"),
    ("parse_bare_sha", "sha:01234567-89ab-cdef-0123-456789abcdef"),
    ("parse_bare_short_dash", "ab-cd"),
    ("parse_ws", "  factor:task-1  "),
    # #1343 item 1: str.strip() covers Unicode whitespace — U+3000 must
    # strip exactly like ASCII space.
    ("parse_unicode_ws", "　factor:task-1　"),
    # #1343 item 2: repr() switches to double quotes when the text holds '.
    ("parse_repr_quote", "factor:it's:x:y"),
    ("parse_empty", ""),
    ("parse_none", None),
    ("parse_int", 42),
    ("parse_unknown", "mystery:thing"),
    ("parse_case", "Factor:task-1"),
]:
    add(cid, "parse_selector", {"value": text},
        capture(lambda t=text: (lambda s: {
            "kind": s.kind.value, "ref_id": s.ref_id,
            "version_id": s.version_id, "floating": s.floating,
            "raw": s.raw})(parse_evidence_selector(t))))


# ---------------------------------------------------------------------------
# evidence — resolve_* (seams per D7)
# ---------------------------------------------------------------------------

DOC = {
    "user_vector_layers": [
        {"id": "layer-9", "name": "沉积相草稿"},
        {"id": "layer-2", "name": "别的"},
    ],
    "factor_map_tasks": [
        {"id": "task-1", "name": "砂地比图", "status": "complete",
         "grid_artifact_version_id": "ver_cur",
         "quality_metrics": {"r2": 0.91, "n_points": 120, "other": "x"},
         "source_kind": "mock"},
        {"id": "task-2", "name": "", "status": "running",
         "grid_artifact_version_id": "",
         "quality_metrics": {}, "source_kind": "real"},
        {"id": "task-3", "name": "孔隙度图", "status": "complete",
         "grid_artifact_version_id": "ver_p3",
         "quality_metrics": {"variance_min": 0.1, "variance_max": 0.9},
         "source_kind": "mixed"},
    ],
    "prediction_tasks": [
        {"id": "p1", "name": "河道预测", "status": "complete",
         "adapter_kind": "mock",
         "probability_summary": {"classes": ["a", "b"], "mean_confidence": 0.7}},
        {"id": "p2", "name": "", "status": "failed",
         "adapter_kind": "onnx", "probability_summary": {}},
        {"id": "p3", "name": "湖盆预测", "status": "done",
         "adapter_kind": "real", "probability_summary": {"classes": []}},
    ],
    "constraint_layers": [{"id": "cg1", "name": "断层"}],
}


def make_doc(spec):
    if spec is None:
        return None
    return ns(
        user_vector_layers=[ns(**l) for l in spec.get("user_vector_layers", [])],
        factor_map_tasks=[ns(**t) for t in spec.get("factor_map_tasks", [])],
        prediction_tasks=[ns(**t) for t in spec.get("prediction_tasks", [])],
        constraint_layers=[ns(**g) for g in spec.get("constraint_layers", [])],
    )


class _WS:
    def __init__(self, memberships=None, role_map=None):
        self._m = memberships or {}
        self._roles = role_map or {}

    def membership(self, layer_id):
        return self._m.get(layer_id)

    def layers_with_role(self, role):
        return list(self._roles.get(getattr(role, "value", role), []))


def make_ws(spec):
    if spec is None:
        return None
    return _WS(
        memberships={
            lid: ns(**m) for lid, m in (spec.get("membership") or {}).items()
        },
        role_map=spec.get("roles") or {},
    )


# constraint resolver seam: canned verdict / raise / real function not ported.
VERDICTS = {
    "clean": {"status": "clean", "detail": "matches latest commit"},
    "current": {"status": "current", "detail": "pinned commit is latest"},
    "stale": {"status": "stale", "detail": "content differs from latest"},
    "superseded": {"status": "superseded",
                   "detail": "constraint group has a newer commit abc…"},
    "missing": {"status": "missing", "detail": "no such group"},
    "unknown": {"status": "unknown", "detail": "never committed"},
    "weird": {"status": "unexpected-word", "detail": "unmapped"},
    # #1344: explicit null detail — str(None or "") must freeze "".
    "null_detail": {"status": "clean", "detail": None},
}


class _DocCatalog:
    """Catalog stub for resolve_constraint_ref's positional signature — the
    oracle replaces the resolver itself, so this is only a placeholder."""

    def __init__(self, catalog):
        self._c = catalog


# Seam stub: evidence._resolve_constraint_group resolves
# `paleo_workbench.workflow.constraint_versions.resolve_constraint_ref` via
# a runtime `from ... import`. The real module pulls catalog.service +
# pydantic; the C++ port takes the resolver as an injected callback (D2/D7),
# so the oracle injects a stub MODULE into sys.modules carrying exactly the
# seam surface — the verdict dict — rather than the subsystem internals.
_CV_MOD_NAME = "paleo_workbench.workflow.constraint_versions"
if _CV_MOD_NAME not in sys.modules:
    try:
        import importlib

        importlib.import_module(_CV_MOD_NAME)
    except Exception:  # noqa: BLE001 — pydantic-less env: stub the module
        stub = types.ModuleType(_CV_MOD_NAME)
        stub.__package__ = "paleo_workbench.workflow"
        sys.modules[_CV_MOD_NAME] = stub
_cv_mod = sys.modules[_CV_MOD_NAME]


def make_resolve(value, doc_spec, catalog_spec, ws_spec, verdict):
    document = make_doc(doc_spec)
    catalog = make_catalog(catalog_spec)
    workspace = make_ws(ws_spec)

    if verdict is None:
        resolver = None
    elif "absent" in verdict:
        resolver = "ABSENT"  # seam attr deleted — ImportError state
    elif "verbatim" in verdict:
        # #1344: a NON-DICT verdict — verdict.get(...) raises AttributeError.
        def resolver(document, catalog, ref, _v=verdict["verbatim"]):
            return _v
    elif "raise" in verdict:
        def resolver(document, catalog, ref, _m=verdict["raise"]):
            raise RuntimeError(_m)
    else:
        def resolver(document, catalog, ref, _v=verdict):
            return dict(_v)

    if resolver == "ABSENT":
        orig = getattr(_cv_mod, "resolve_constraint_ref", None)
        if orig is not None:
            del _cv_mod.resolve_constraint_ref
        try:
            return resolve_evidence(
                document, value, catalog=catalog, workspace_state=workspace)
        finally:
            if orig is not None:
                _cv_mod.resolve_constraint_ref = orig
    elif resolver is not None:
        orig = getattr(_cv_mod, "resolve_constraint_ref", None)
        _cv_mod.resolve_constraint_ref = resolver
        try:
            return resolve_evidence(
                document, value, catalog=catalog, workspace_state=workspace)
        finally:
            if orig is not None:
                _cv_mod.resolve_constraint_ref = orig
            else:
                del _cv_mod.resolve_constraint_ref
    return resolve_evidence(
        document, value, catalog=catalog, workspace_state=workspace)


def resolve_case(cid, value, doc_spec=None, catalog_spec=None, ws_spec=None,
                 verdict=None):
    inp = {"value": value, "document": doc_spec if doc_spec is not None else DOC,
           "catalog": catalog_spec, "workspace": ws_spec,
           "verdict": verdict}
    add(cid, "resolve", inp,
        capture(lambda: (lambda r: r.to_dict())(make_resolve(
            value, inp["document"], catalog_spec, ws_spec, verdict))))


CAT = {"resolve": {"ver_cur": {"asset_id": "a-1", "name": "砂地比成果"},
                   "ver_p3": {"asset_id": "a-2", "name": "孔图"},
                   "ver_x": {"asset_id": "a-9", "name": "外部版"},
                   "ver_raw": {"asset_id": "a-raw", "name": "RAW"}}}

resolve_case("res_draft_ok", "draft:layer-9",
             ws_spec={"membership": {"layer-9": {"source_version_id": "ver_raw"}}},
             catalog_spec=CAT)
resolve_case("res_draft_no_ws", "draft:layer-9", ws_spec=None, catalog_spec=CAT)
resolve_case("res_draft_no_member", "draft:layer-2",
             ws_spec={"membership": {}}, catalog_spec=CAT)
resolve_case("res_draft_unpinned", "draft:layer-9",
             ws_spec={"membership": {"layer-9": {"source_version_id": ""}}},
             catalog_spec=CAT)
resolve_case("res_draft_no_catalog", "draft:layer-9",
             ws_spec={"membership": {"layer-9": {"source_version_id": "ver_raw"}}},
             catalog_spec=None)
resolve_case("res_draft_ver_missing", "draft:layer-9",
             ws_spec={"membership": {"layer-9": {"source_version_id": "ver_zzz"}}},
             catalog_spec=CAT)
resolve_case("res_draft_catalog_raise", "draft:layer-9",
             ws_spec={"membership": {"layer-9": {"source_version_id": "ver_raw"}}},
             catalog_spec={"raise": True})
resolve_case("res_factor_ok", "factor:task-1", catalog_spec=CAT)
resolve_case("res_factor_pin_ok", "factor:task-1:ver_cur", catalog_spec=CAT)
resolve_case("res_factor_stale", "factor:task-1:ver_old",
             catalog_spec={"resolve": {"ver_old": {"asset_id": "a-o",
                                                   "name": "旧版"}}})
resolve_case("res_factor_missing_task", "factor:ghost", catalog_spec=CAT)
resolve_case("res_factor_unpinned", "factor:task-2", catalog_spec=CAT)
resolve_case("res_factor_no_catalog", "factor:task-1", catalog_spec=None)
resolve_case("res_factor_ver_missing", "factor:task-1:ver_zzz",
             catalog_spec=CAT)
resolve_case("res_factor_quality", "factor:task-3", catalog_spec=CAT)
resolve_case("res_pred_ok_unpinned", "prediction:p1", catalog_spec=CAT)
resolve_case("res_pred_unfinished", "prediction:p2", catalog_spec=CAT)
resolve_case("res_pred_missing_task", "prediction:ghost", catalog_spec=CAT)
resolve_case("res_pred_ver_missing", "prediction:p1:ver_zzz", catalog_spec=CAT)
resolve_case("res_pred_ver_ok", "prediction:p1:ver_cur", catalog_spec=CAT)
resolve_case("res_pred_done", "prediction:p3", catalog_spec=CAT)
resolve_case("res_pred_no_cat_ver", "prediction:p1:ver_x", catalog_spec=None)
resolve_case("res_cg_float_clean", "constraints:current",
             verdict=VERDICTS["clean"])
resolve_case("res_cg_float_stale", "constraints:current",
             verdict=VERDICTS["stale"])
resolve_case("res_cg_float_superseded", "constraints:current",
             verdict=VERDICTS["superseded"])
resolve_case("res_cg_float_unknown", "constraints:current",
             verdict=VERDICTS["unknown"])
resolve_case("res_cg_float_weird", "constraints:current",
             verdict=VERDICTS["weird"])
resolve_case("res_cg_float_raise", "constraints:current",
             verdict={"raise": "backend dead"})
resolve_case("res_cg_named_missing", "constraints:g1:ver_2",
             verdict=VERDICTS["missing"])
resolve_case("res_cg_named_clean", "constraints:g1:ver_2",
             verdict=VERDICTS["clean"])
resolve_case("res_cg_named_stale", "constraints:g1:ver_2",
             verdict=VERDICTS["stale"])
resolve_case("res_cg_named_unknown", "constraints:g1:ver_2",
             verdict=VERDICTS["unknown"])
resolve_case("res_cg_named_raise", "constraints:g1:ver_2",
             verdict={"raise": "io error"})
resolve_case("res_ver_ok", "version:ver_x", catalog_spec=CAT)
resolve_case("res_ver_no_catalog", "version:ver_x", catalog_spec=None)
resolve_case("res_ver_missing", "version:ver_zzz", catalog_spec=CAT)
resolve_case("res_bare_ver", "ver_x", catalog_spec=CAT)
resolve_case("res_raise_parse", "mystery:thing", catalog_spec=CAT)

# --- #1339: falsy scalar fields collapse via `or ""` ------------------------
DOC_FALSY = {
    "user_vector_layers": [{"id": "l-fals", "name": []}],
    "factor_map_tasks": [
        {"id": "t-fals", "name": [], "status": "complete",
         "grid_artifact_version_id": 0, "quality_metrics": {},
         "source_kind": "real"},
    ],
    "prediction_tasks": [
        {"id": "p-fals", "name": False, "status": False,
         "adapter_kind": "real", "probability_summary": {}},
        {"id": None, "name": "无名", "status": "complete",
         "adapter_kind": "real", "probability_summary": {}},
    ],
    "constraint_layers": [],
}
# name=[] falsy -> display falls back to ref_id; grid_artifact_version_id=0
# falsy -> "" -> UNPINNED (not a "0" version lookup).
resolve_case("res_factor_falsy_fields", "factor:t-fals",
             doc_spec=DOC_FALSY, catalog_spec=CAT)
# status=False falsy -> "" -> proceeds to UNPINNED; name=False falsy ->
# ref_id display.
resolve_case("res_pred_falsy_status", "prediction:p-fals",
             doc_spec=DOC_FALSY, catalog_spec=CAT)
# task.id=None -> str(None) == "None" — matches the literal selector.
resolve_case("res_pred_id_none", "prediction:None",
             doc_spec=DOC_FALSY, catalog_spec=CAT)
# falsy layer name -> display falls back to the layer id.
resolve_case("res_draft_falsy_name", "draft:l-fals", doc_spec=DOC_FALSY,
             ws_spec={"membership": {"l-fals": {"source_version_id": ""}}})
# falsy membership pin -> UNPINNED.
resolve_case("res_draft_falsy_pin", "draft:layer-9",
             ws_spec={"membership": {"layer-9": {"source_version_id": 0}}},
             catalog_spec=CAT)

# --- #1344: verdict edge shapes ---------------------------------------------
resolve_case("res_cg_null_detail", "constraints:current",
             verdict=VERDICTS["null_detail"])
# Non-dict verdict: verdict.get raises AttributeError OUT of resolve_evidence.
resolve_case("res_cg_verdict_scalar", "constraints:current",
             verdict={"verbatim": "oops"})
resolve_case("res_cg_verdict_list", "constraints:g1:ver_2",
             verdict={"verbatim": ["clean"]})

# #1343 item 5 / #1344: absent resolver — Python's `from ... import` raises
# ImportError BEFORE the try; message embeds the module path (mask with "*").
def _resolve_absent(cid, value):
    inp = {"value": value, "document": DOC, "catalog": None,
           "workspace": None, "verdict": {"absent": True}}
    exp = capture(lambda: make_resolve(value, DOC, None, None,
                                       {"absent": True}))
    if "raise" in exp and exp["raise"]["python_class"] == "ImportError":
        exp["raise"]["message"] = "*"  # module-path-dependent text
    add(cid, "resolve", inp, exp)


_resolve_absent("res_cg_absent_float", "constraints:current")
_resolve_absent("res_cg_absent_named", "constraints:g1:ver_2")

# selector-object input (not str) — EvidenceSelector passes straight through.
add("res_selector_obj", "resolve_selector_obj",
    {"kind": "catalog_version", "ref_id": "ver_x", "version_id": "ver_x",
     "floating": False, "catalog": CAT},
    capture(lambda: resolve_evidence(
        make_doc(DOC),
        EvidenceSelector(EvidenceKind.CATALOG_VERSION,
                         ref_id="ver_x", version_id="ver_x"),
        catalog=make_catalog(CAT)).to_dict()))


# ---------------------------------------------------------------------------
# available_evidence
# ---------------------------------------------------------------------------

def _with_resolver(verdict, fn):
    """Install the seam resolver while fn() runs (avail cases freeze the
    verdict, not the real subsystem's internals — D7)."""
    if verdict is None:
        return fn()
    if "absent" in verdict:
        orig = getattr(_cv_mod, "resolve_constraint_ref", None)
        if orig is not None:
            del _cv_mod.resolve_constraint_ref
        try:
            return fn()
        finally:
            if orig is not None:
                _cv_mod.resolve_constraint_ref = orig
    if "verbatim" in verdict:
        def resolver(document, catalog, ref, _v=verdict["verbatim"]):
            return _v
    elif "raise" in verdict:
        def resolver(document, catalog, ref, _m=verdict["raise"]):
            raise RuntimeError(_m)
    else:
        def resolver(document, catalog, ref, _v=verdict):
            return dict(_v)
    orig = getattr(_cv_mod, "resolve_constraint_ref", None)
    _cv_mod.resolve_constraint_ref = resolver
    try:
        return fn()
    finally:
        if orig is not None:
            _cv_mod.resolve_constraint_ref = orig
        else:
            del _cv_mod.resolve_constraint_ref


for cid, doc_spec, ws_spec, verdict in [
    ("avail_none", None, None, None),
    ("avail_empty_ws", DOC, {"membership": {}, "roles": {}},
     {"raise": "backend dead"}),
    ("avail_full", DOC,
     {"membership": {"layer-9": {"source_version_id": "ver_raw"}},
      "roles": {"initial_facies_draft": ["layer-9"]}},
     {"status": "clean", "detail": "live constraint content"}),
    ("avail_no_constraints", {
        "user_vector_layers": [],
        "factor_map_tasks": DOC["factor_map_tasks"],
        "prediction_tasks": DOC["prediction_tasks"],
        "constraint_layers": [],
    }, None, None),
    # #1341: ids containing ":" enter through the STRING selector path —
    # "prediction:a:b" parses to ref="a", version="b" (a direct selector
    # would have kept ref="a:b" verbatim).
    ("avail_pred_colon_id", {
        "user_vector_layers": [],
        "factor_map_tasks": [],
        "prediction_tasks": [
            {"id": "a:b", "name": "x", "status": "complete",
             "adapter_kind": "real", "probability_summary": {}},
        ],
        "constraint_layers": [],
    }, None, None),
    # #1341: draft layer ids keep the whole body (colons included).
    ("avail_draft_colon_id", {
        "user_vector_layers": [{"id": "l:x", "name": "草稿"}],
        "factor_map_tasks": [], "prediction_tasks": [],
        "constraint_layers": [],
    }, {"membership": {}, "roles": {"initial_facies_draft": ["l:x"]}},
        None),
    # #1341: an empty task id produces "prediction:" — a parse ValueError
    # that propagates out of available_evidence (a direct selector would
    # have silently produced a Missing result).
    ("avail_pred_empty_id", {
        "user_vector_layers": [], "factor_map_tasks": [],
        "prediction_tasks": [
            {"id": "", "name": "x", "status": "complete",
             "adapter_kind": "real", "probability_summary": {}},
        ],
        "constraint_layers": [],
    }, None, None),
    # #1341: a colon-bearing factor id turns "factor:f:1:ver_x" into a
    # 3-segment selector — parse rejects it, the whole listing raises.
    ("avail_factor_colon_id", {
        "user_vector_layers": [],
        "factor_map_tasks": [
            {"id": "f:1", "name": "x", "status": "complete",
             "grid_artifact_version_id": "ver_x", "quality_metrics": {},
             "source_kind": "real"},
        ],
        "prediction_tasks": [], "constraint_layers": [],
    }, None, None),
    # #1344: absent resolver seam reached via the constraints entry.
    ("avail_absent_resolver", {
        "user_vector_layers": [], "factor_map_tasks": [],
        "prediction_tasks": [], "constraint_layers": [{"id": "g", "name": "c"}],
    }, None, {"absent": True}),
]:
    inp = {"document": doc_spec, "workspace": ws_spec, "verdict": verdict}
    exp = capture(lambda d=doc_spec, w=ws_spec, v=verdict: _with_resolver(
        v, lambda: [r.to_dict() for r in available_evidence(
            make_doc(d), workspace_state=make_ws(w))]))
    if ("raise" in exp and exp["raise"]["python_class"] == "ImportError"):
        exp["raise"]["message"] = "*"  # module-path-dependent (#1344)
    add(cid, "available_evidence", inp, exp)


# ---------------------------------------------------------------------------

payload = {
    "meta": {
        "generator": "tools/oracle/generate_workflow_graph_fixtures.py",
        "source": "paleo_workbench/workflow/dependency_graph.py + "
                  "workflow/interpretation/evidence.py",
        "cases": len(cases),
    },
    "cases": cases,
}
FIXTURE.parent.mkdir(parents=True, exist_ok=True)
FIXTURE.write_text(
    json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
)
print(f"wrote {len(cases)} cases -> {FIXTURE}")
