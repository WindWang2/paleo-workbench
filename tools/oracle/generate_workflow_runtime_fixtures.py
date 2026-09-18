#!/usr/bin/env python3
"""Generate the frozen workflow runtime oracle for CONV-26.

Drives the REAL Python implementation (freshness / current_context /
recompute_plan / constraint_versions / provenance_graph /
interpretation.staleness adapters) with deterministic fake catalogs and
freezes every observable output (states, reason lists, plan steps,
executor messages, commit reports, staleness adjudications, lifecycle
graphs, adapter verdicts). Raise cases freeze class + message verbatim.

Every case's ``input`` carries the FULL scenario as plain JSON so the C++
replay test reconstructs it independently — the fixture is the only
shared artifact. Deterministic: re-run must be byte-identical. Cases
avoid Python set-iteration-order-dependent outputs (single selected tip
per supersession key; the cycle-fallback plan has one stale run).
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from paleo_workbench.catalog.types import DataRunRef, DataVersionRef  # noqa: E402
from paleo_workbench.workflow.current_context import (  # noqa: E402
    CurrentProjectVersionContext,
)
from paleo_workbench.workflow.dependency_graph import DependencyGraph  # noqa: E402
from paleo_workbench.workflow.freshness import FreshnessService  # noqa: E402
from paleo_workbench.workflow.recompute_plan import (  # noqa: E402
    PlanExecutor,
    build_recompute_plan,
)
from paleo_workbench.workflow.interpretation.staleness import (  # noqa: E402
    ArtifactVerdict,
    StalenessVerdict,
    from_constraint_pin,
    from_run_freshness,
    from_workspace_status,
)

FIXTURE = (
    ROOT
    / "libs/workflow_runtime/workflow_runtime_tests/fixtures/"
    "workflow_runtime_oracle.json"
)

cases: list[dict] = []

# Hermetic payload for the integrity "modified" branch: both the generator
# and the C++ replay create this file before evaluating (idempotent).
INTEGRITY_MODIFIED_PATH = Path("/tmp/pwb-runtime-oracle-payload.json")
INTEGRITY_MODIFIED_PATH.write_text("payload-bytes-v1", encoding="utf-8")


def add(cid: str, fn: str, inp: dict, expect: dict) -> None:
    cases.append({"id": cid, "fn": fn, "input": inp, "expect": expect})


def capture(fn, *args, **kwargs):
    try:
        return {"result": fn(*args, **kwargs)}
    except Exception as exc:  # noqa: BLE001 — freeze class + message verbatim
        return {"raise": {"python_class": type(exc).__name__, "message": str(exc)}}


# ------------------------------------------------------- record fakes (dicts)

def make_run(spec: dict):
    return DataRunRef(
        run_id=spec["run_id"],
        operation=spec.get("operation", ""),
        input_version_ids=spec.get("input_version_ids") or [],
        output_version_ids=spec.get("output_version_ids") or [],
        parameters=spec.get("parameters"),
        generator_version=spec.get("generator_version"),
        status=spec.get("status", "running"),
        started_at=spec.get("started_at", "2026-01-01T00:00:00"),
        finished_at=spec.get("finished_at"),
        domain_task_id=spec.get("domain_task_id"),
        input_snapshot_hash=spec.get("input_snapshot_hash"),
    )


class FakeVersion(types.SimpleNamespace):
    """DataVersionRef-shaped record with checksum/trashed/path."""


def make_version(spec: dict) -> FakeVersion:
    return FakeVersion(
        asset_id=spec["asset_id"],
        version_id=spec["version_id"],
        name=spec.get("name", ""),
        producing_run_id=spec.get("producing_run_id"),
        checksum=spec.get("checksum"),
        trashed=spec.get("trashed", False),
        path=spec.get("path", ""),
        created_at=spec.get("created_at", "2026-01-01T00:00:00"),
        payload_json=spec.get("payload_json"),
    )


class FakeCatalog:
    """resolve_version / verify_integrity seam fake."""

    def __init__(self, versions: list[FakeVersion]) -> None:
        self._by_id = {v.version_id: v for v in versions}

    def resolve_version(self, version_id: str):
        return self._by_id.get(version_id)

    def resolve_run(self, run_id: str):
        return None  # off-graph runs are unknown to the catalog fake

    def verify_integrity(self, version_id: str):
        ver = self._by_id.get(version_id)
        if ver is None or not ver.checksum or ver.payload_json is None:
            return None
        actual = hashlib.sha256(ver.payload_json.encode()).hexdigest()
        return "verified" if actual == ver.checksum else "modified"


def build_service(spec: dict) -> FreshnessService:
    versions = [make_version(v) for v in spec["versions"]]
    runs = [make_run(r) for r in spec["runs"]]
    # The REAL system's graph.versions records are the catalog's full
    # DataVersionRef objects (checksum / trashed included — freshness reads
    # them off the graph first). Model that faithfully: the graph holds the
    # same rich records, not a stripped projection.
    graph = DependencyGraph.from_catalog(
        types.SimpleNamespace(list_versions=lambda: versions,
                              list_runs=lambda: runs)
    )
    ctx = build_ctx_from_spec(spec.get("context", {}))
    return FreshnessService(
        graph, ctx, catalog=FakeCatalog(versions),
        check_integrity=spec.get("check_integrity", False),
    )


def build_ctx_from_spec(context: dict) -> CurrentProjectVersionContext:
    ctx = CurrentProjectVersionContext()
    for sel in context.get("selects", []):
        ctx.select(sel["asset_id"], sel["version_id"],
                   label=sel.get("label", ""))
    for mark in context.get("domain_current", []):
        ctx.mark_domain_product_current(mark["domain_task_id"],
                                        mark["version_id"])
    for ident in context.get("expected_identity", []):
        ctx.set_expected_identity(
            ident["key"],
            generator_version=ident.get("generator_version"),
            input_snapshot_hash=ident.get("input_snapshot_hash"),
            parameters=ident.get("parameters"),
            model_ref=ident.get("model_ref"),
        )
    return ctx


def add_run_case(cid: str, spec: dict, run_id: str):
    svc = build_service(spec)
    add(cid, "freshness.evaluate_run", {"spec": spec, "run_id": run_id},
        capture(lambda: svc.evaluate_run(run_id).to_dict()))


# ------------------------------------------------------------- scenario specs

LINEAR = {
    "versions": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v1", "name": "H1",
         "producing_run_id": None},
        {"asset_id": "asset_h1", "version_id": "ver_h1_v2", "name": "H1",
         "producing_run_id": None, "checksum": "c" * 64},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1", "name": "F1",
         "producing_run_id": "run_f1"},
        {"asset_id": "asset_m1", "version_id": "ver_m1_v1", "name": "M1",
         "producing_run_id": "run_m1"},
    ],
    "runs": [
        {"run_id": "run_f1", "operation": "factor_map",
         "input_version_ids": ["ver_h1_v1"],
         "output_version_ids": ["ver_f1_v1"], "status": "complete",
         "domain_task_id": "task_f1",
         "started_at": "2026-01-01T00:00:01"},
        {"run_id": "run_m1", "operation": "map_compile",
         "input_version_ids": ["ver_f1_v1"],
         "output_version_ids": ["ver_m1_v1"], "status": "complete",
         "started_at": "2026-01-01T00:00:02"},
    ],
    "context": {"selects": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v2",
         "label": "H1 最新"},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1"},
        {"asset_id": "asset_m1", "version_id": "ver_m1_v1"},
    ]},
}

FRESH_CASE = {
    "versions": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v1", "name": "H1",
         "producing_run_id": None},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1", "name": "F1",
         "producing_run_id": "run_f1"},
    ],
    "runs": [
        {"run_id": "run_f1", "operation": "factor_map",
         "input_version_ids": ["ver_h1_v1"],
         "output_version_ids": ["ver_f1_v1"], "status": "complete",
         "started_at": "2026-01-01T00:00:01"},
    ],
    "context": {"selects": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v1"},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1"},
    ]},
}


def clone(spec: dict) -> dict:
    return json.loads(json.dumps(spec))


IDENTICAL = clone(LINEAR)
IDENTICAL["versions"][0]["checksum"] = "d" * 64
IDENTICAL["versions"][1]["checksum"] = "d" * 64

PARENT = {
    "versions": [
        {"asset_id": "asset_i1", "version_id": "ver_i1", "name": "I1",
         "producing_run_id": None},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1", "name": "F1",
         "producing_run_id": "run_f1"},
        {"asset_id": "asset_f2", "version_id": "ver_f2_v1", "name": "F2",
         "producing_run_id": "run_f2"},
    ],
    "runs": [
        {"run_id": "run_f1", "operation": "integrated_interpretation",
         "input_version_ids": ["ver_i1"],
         "output_version_ids": ["ver_f1_v1"], "status": "complete",
         "started_at": "2026-01-01T00:00:01"},
        {"run_id": "run_f2", "operation": "integrated_interpretation",
         "input_version_ids": ["ver_f1_v1"],
         "output_version_ids": ["ver_f2_v1"], "status": "complete",
         "parameters": {"parent_version_id": "ver_f1_v1"},
         "started_at": "2026-01-01T00:00:02"},
    ],
    "context": {"selects": [
        {"asset_id": "asset_i1", "version_id": "ver_i1"},
    ]},
}

CYCLE = {
    "versions": [
        {"asset_id": "asset_a", "version_id": "ver_a", "name": "A",
         "producing_run_id": "run_b"},
        {"asset_id": "asset_b", "version_id": "ver_b", "name": "B",
         "producing_run_id": "run_a"},
    ],
    "runs": [
        {"run_id": "run_a", "operation": "factor_map",
         "input_version_ids": ["ver_b"], "output_version_ids": ["ver_a"],
         "status": "complete", "started_at": "2026-01-01T00:00:01"},
        {"run_id": "run_b", "operation": "factor_map",
         "input_version_ids": ["ver_a"], "output_version_ids": ["ver_b"],
         "status": "complete", "started_at": "2026-01-01T00:00:02"},
    ],
    "context": {"selects": []},
}

INTEGRITY = {
    "versions": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v1", "name": "H1",
         "producing_run_id": None},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1", "name": "F1",
         "producing_run_id": "run_f1", "path": "/nonexistent/payload_f1.json",
         "checksum": "a" * 64, "payload_json": "changed!"},
    ],
    "runs": [
        {"run_id": "run_f1", "operation": "factor_map",
         "input_version_ids": ["ver_h1_v1"],
         "output_version_ids": ["ver_f1_v1"], "status": "complete",
         "started_at": "2026-01-01T00:00:01"},
    ],
    "context": {"selects": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v1"},
    ]},
    "check_intity": True,
}
INTEGRITY["check_integrity"] = True  # (typo guard above stays out of JSON)

STEPS = {
    "versions": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v1", "name": "H1",
         "producing_run_id": None},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1", "name": "F1",
         "producing_run_id": "run_f1a"},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v2", "name": "F1",
         "producing_run_id": "run_f1b"},
        {"asset_id": "asset_p1", "version_id": "ver_p1_v1", "name": "P1",
         "producing_run_id": "run_p1"},
        {"asset_id": "asset_i2", "version_id": "ver_i2_v1", "name": "I2",
         "producing_run_id": "run_i2"},
    ],
    "runs": [
        {"run_id": "run_f1a", "operation": "factor_map",
         "input_version_ids": ["ver_h1_v1"],
         "output_version_ids": ["ver_f1_v1"], "status": "failed",
         "domain_task_id": "task_f1",
         "started_at": "2026-01-01T00:00:01"},
        {"run_id": "run_f1b", "operation": "factor_map",
         "input_version_ids": ["ver_h1_v1"],
         "output_version_ids": ["ver_f1_v2"], "status": "complete",
         "domain_task_id": "task_f1",
         "started_at": "2026-01-01T00:00:05"},
        {"run_id": "run_p1", "operation": "prediction",
         "input_version_ids": ["ver_f1_v2"],
         "output_version_ids": ["ver_p1_v1"], "status": "complete",
         "started_at": "2026-01-01T00:00:06"},
        {"run_id": "run_i2", "operation": "inference",
         "input_version_ids": ["ver_h1_v1"],
         "output_version_ids": ["ver_i2_v1"], "status": "complete",
         "started_at": "2026-01-01T00:00:07"},
    ],
    "context": {"selects": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v1"},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v2"},
    ]},
}

REUSE = {
    "versions": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v1", "name": "H1",
         "producing_run_id": None},
        {"asset_id": "asset_h1", "version_id": "ver_h1_v2", "name": "H1",
         "producing_run_id": None},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1", "name": "F1",
         "producing_run_id": "run_f1_old"},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v2", "name": "F1",
         "producing_run_id": "run_f1_new"},
        {"asset_id": "asset_m1", "version_id": "ver_m1_v1", "name": "M1",
         "producing_run_id": "run_m1"},
    ],
    "runs": [
        {"run_id": "run_f1_old", "operation": "factor_map",
         "input_version_ids": ["ver_h1_v1"],
         "output_version_ids": ["ver_f1_v1"], "status": "complete",
         "domain_task_id": "task_f1",
         "started_at": "2026-01-01T00:00:01"},
        {"run_id": "run_f1_new", "operation": "factor_map",
         "input_version_ids": ["ver_h1_v2"],
         "output_version_ids": ["ver_f1_v2"], "status": "complete",
         "domain_task_id": "task_f1",
         "started_at": "2026-01-01T00:00:04"},
        {"run_id": "run_m1", "operation": "map_compile",
         "input_version_ids": ["ver_f1_v1"],
         "output_version_ids": ["ver_m1_v1"], "status": "complete",
         "started_at": "2026-01-01T00:00:05"},
    ],
    "context": {"selects": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v2"},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v2"},
        {"asset_id": "asset_m1", "version_id": "ver_m1_v1"},
    ]},
}

H11 = {
    "versions": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v1", "name": "H1",
         "producing_run_id": None},
        {"asset_id": "asset_h1", "version_id": "ver_h1_v2", "name": "H1",
         "producing_run_id": None},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1", "name": "F1",
         "producing_run_id": "run_f1"},
    ],
    "runs": [
        {"run_id": "run_f1", "operation": "factor_map",
         "input_version_ids": ["ver_h1_v1"],
         "output_version_ids": ["ver_f1_v1"], "status": "complete",
         "domain_task_id": "task_f1",
         "started_at": "2026-01-01T00:00:01"},
        {"run_id": "run_p1", "operation": "prediction",
         "input_version_ids": [], "output_version_ids": [],
         "status": "complete", "domain_task_id": "task_p1",
         "started_at": "2026-01-01T00:00:02"},
    ],
    "context": {"selects": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v2"},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1"},
    ]},
}

H11_PROJECT = {
    "prediction_tasks": [
        {"id": "task_p1", "input_factor_map_ids": ["task_f1"]},
    ],
    "paleomap_documents": [],
}

EMPTY_SPEC = {"versions": [], "runs": [], "context": {}}


# --------------------------------------------------------------- current_context

CTX_STATE = {
    "selects": [{"asset_id": "asset_h1", "version_id": "ver_h1_v1",
                 "label": "H1 解释"}],
    "domain_current": [{"domain_task_id": "task_f1",
                        "version_id": "ver_f1_v1"}],
    "expected_identity": [{
        "key": "task_f1", "generator_version": "factor-v2",
        "input_snapshot_hash": "snap-1",
        "parameters": {"method": "idw", "power": 2.0, "colormap": "viridis",
                       "_display_zoom": 1.25},
        "model_ref": {"model_id": "m1", "model_version": "3"},
    }],
}

ctx = build_ctx_from_spec(CTX_STATE)
add(
    "ctx_state", "current_context.state", {"state": CTX_STATE},
    capture(lambda: {
        "current_by_asset": dict(ctx.current_by_asset),
        "selected": sorted(ctx.selected_version_ids),
        "labels": dict(ctx.labels),
        "current_by_domain_task": dict(ctx.current_by_domain_task),
        "expected_identity": ctx.expected_identity,
        "current_for_asset(h1)": ctx.current_for_asset("asset_h1"),
        "current_for_asset(none)": ctx.current_for_asset(None),
        "is_current(ver_h1_v1)": ctx.is_current_version("ver_h1_v1"),
        "is_current(ver_x)": ctx.is_current_version("ver_x"),
    }),
)

CTX_RESELECT = {
    "selects": [{"asset_id": "a", "version_id": "v1"},
                {"asset_id": "a", "version_id": "v2"}],
}
ctx2 = build_ctx_from_spec(CTX_RESELECT)
add(
    "ctx_reselect", "current_context.reselect", {"state": CTX_RESELECT},
    capture(lambda: {
        "current": ctx2.current_for_asset("a"),
        "selected": sorted(ctx2.selected_version_ids),
    }),
)

# ------------------------------------------------------------------- freshness

add_run_case("fresh_upstream_changed", LINEAR, "run_f1")
add_run_case("fresh_transitive_stale", LINEAR, "run_m1")
add_run_case("fresh_content_identical", IDENTICAL, "run_f1")
add_run_case("fresh_ok", FRESH_CASE, "run_f1")
add_run_case("fresh_parent_link_no_tip", PARENT, "run_f2")
add_run_case("fresh_cycle", CYCLE, "run_a")
add_run_case("fresh_integrity_modified", INTEGRITY, "run_f1")

for status, cid in [("failed", "fresh_run_failed"),
                    ("error", "fresh_run_error"),
                    ("cancelled", "fresh_run_cancelled"),
                    ("running", "fresh_run_running"),
                    ("pending", "fresh_run_pending")]:
    spec = clone(FRESH_CASE)
    spec["runs"][0]["status"] = status
    add_run_case(cid, spec, "run_f1")

spec = clone(FRESH_CASE)
spec["runs"][0]["input_version_ids"] = []
add_run_case("fresh_missing_lineage_op", spec, "run_f1")

spec = clone(FRESH_CASE)
spec["versions"][0]["trashed"] = True
add_run_case("fresh_input_withdrawn", spec, "run_f1")

spec = clone(FRESH_CASE)
spec["runs"][0]["input_version_ids"] = ["ver_ghost"]
add_run_case("fresh_input_purged", spec, "run_f1")

base = clone(FRESH_CASE)
base["context"]["expected_identity"] = [{
    "key": "task_f1",
    "generator_version": "factor-v2",
    "input_snapshot_hash": "snap-1",
    "parameters": {"method": "idw", "power": 2.0},
    "model_ref": {"model_id": "m1", "model_version": "3"},
}]
base["runs"][0]["domain_task_id"] = "task_f1"
base["runs"][0]["generator_version"] = "factor-v1"
base["runs"][0]["input_snapshot_hash"] = "snap-0"
base["runs"][0]["parameters"] = {"method": "idw", "power": 3.0,
                                 "model_id": "m1", "model_version": "2"}
add_run_case("fresh_identity_generator", base, "run_f1")

base2 = clone(base)
base2["runs"][0]["generator_version"] = "factor-v2"
base2["runs"][0]["parameters"] = {"method": "idw", "power": 2.0,
                                  "model_id": "m1", "model_version": "3"}
add_run_case("fresh_identity_snapshot", base2, "run_f1")

base3 = clone(base)
base3["runs"][0]["generator_version"] = "factor-v2"
base3["runs"][0]["input_snapshot_hash"] = "snap-1"
base3["runs"][0]["parameters"] = {"method": "idw", "power": 2.0,
                                  "model_ref": {"model_id": "m1",
                                                "model_version": "9"}}
add_run_case("fresh_identity_model_ref", base3, "run_f1")

base4 = clone(base)
base4["runs"][0]["generator_version"] = "factor-v2"
base4["runs"][0]["input_snapshot_hash"] = "snap-1"
base4["runs"][0]["parameters"] = {"method": "idw", "power": 2.0,
                                  "model_id": "m1", "model_version": "3"}
add_run_case("fresh_identity_match", base4, "run_f1")

base5 = clone(base4)
base5["context"]["expected_identity"][0]["parameters"] = {
    "method": "idw", "power": 2.0, "colormap": "plasma"}
base5["runs"][0]["parameters"]["colormap"] = "viridis"
add_run_case("fresh_display_only_ignored", base5, "run_f1")

svc = build_service(LINEAR)
add("fresh_version_delegates", "freshness.evaluate_version",
    {"spec": LINEAR, "version_id": "ver_f1_v1"},
    capture(lambda: svc.evaluate_version("ver_f1_v1").to_dict()))
add("fresh_version_root", "freshness.evaluate_version",
    {"spec": LINEAR, "version_id": "ver_h1_v1"},
    capture(lambda: svc.evaluate_version("ver_h1_v1").to_dict()))
add("fresh_version_missing", "freshness.evaluate_version",
    {"spec": LINEAR, "version_id": "ver_nope"},
    capture(lambda: svc.evaluate_version("ver_nope").to_dict()))
add("fresh_run_missing", "freshness.evaluate_run",
    {"spec": LINEAR, "run_id": "run_nope"},
    capture(lambda: svc.evaluate_run("run_nope").to_dict()))
add("fresh_domain_task", "freshness.evaluate_domain_task",
    {"spec": LINEAR, "domain_task_id": "task_f1"},
    capture(lambda: svc.evaluate_domain_task("task_f1").to_dict()))
add("fresh_domain_task_missing", "freshness.evaluate_domain_task",
    {"spec": LINEAR, "domain_task_id": "task_none"},
    capture(lambda: svc.evaluate_domain_task("task_none").to_dict()))
add("fresh_downstream_impact", "freshness.downstream_impact",
    {"spec": LINEAR, "version_ids": ["ver_h1_v1"]},
    capture(lambda: [r.to_dict() for r in
                     svc.downstream_impact(["ver_h1_v1"])]))
add("fresh_stale_downstream", "freshness.stale_downstream",
    {"spec": LINEAR, "version_ids": ["ver_h1_v1"]},
    capture(lambda: [r.to_dict() for r in
                     svc.stale_downstream(["ver_h1_v1"])]))
add("fresh_evaluate_operation", "freshness.evaluate_operation",
    {"spec": LINEAR, "operation": "factor_map"},
    capture(lambda: [r.to_dict() for r in
                     svc.evaluate_operation("factor_map")]))

svc_steps = build_service(STEPS)
for step in ("factor_map", "prediction", "map_compile", "qc", "export",
             "factor_fusion", "unknown_step"):
    state = svc_steps.step_freshness(step)
    add(f"step_{step}", "freshness.step_freshness",
        {"spec": STEPS, "step_type": step},
        {"result": None if state is None else state.value})

# ---- selection-mismatch rule coverage (rules 1 / 3 / 4) ----
# Shared shape: run_h1/run_h2 are two recompute attempts of domain task
# task_h (asset-per-run), run_b consumes the FIRST attempt's output.
DOMAIN_BASE = {
    "versions": [
        {"asset_id": "asset_raw", "version_id": "ver_raw", "name": "RAW",
         "producing_run_id": None},
        {"asset_id": "asset_h1", "version_id": "ver_h_v1", "name": "H1",
         "producing_run_id": "run_h1"},
        {"asset_id": "asset_h2", "version_id": "ver_h_v2", "name": "H2",
         "producing_run_id": "run_h2"},
        {"asset_id": "asset_b", "version_id": "ver_b_v1", "name": "B",
         "producing_run_id": "run_b"},
    ],
    "runs": [
        {"run_id": "run_h1", "operation": "factor_map",
         "input_version_ids": ["ver_raw"],
         "output_version_ids": ["ver_h_v1"], "status": "complete",
         "domain_task_id": "task_h",
         "started_at": "2026-01-01T00:00:01"},
        {"run_id": "run_h2", "operation": "factor_map",
         "input_version_ids": ["ver_raw"],
         "output_version_ids": ["ver_h_v2"], "status": "complete",
         "domain_task_id": "task_h",
         "started_at": "2026-01-01T00:00:02"},
        {"run_id": "run_b", "operation": "prediction",
         "input_version_ids": ["ver_h_v1"],
         "output_version_ids": ["ver_b_v1"], "status": "complete",
         "started_at": "2026-01-01T00:00:03"},
    ],
    "context": {"selects": [
        {"asset_id": "asset_raw", "version_id": "ver_raw"},
        {"asset_id": "asset_b", "version_id": "ver_b_v1"},
    ]},
}

# rule 1: explicit domain-task product tip (task_h -> ver_h_v2) supersedes
# the consumed ver_h_v1 even though neither asset pointer moved.
RULE1 = clone(DOMAIN_BASE)
RULE1["context"]["domain_current"] = [
    {"domain_task_id": "task_h", "version_id": "ver_h_v2"}]
add_run_case("fresh_rule1_domain_tip", RULE1, "run_b")

# rule 3: no domain pointer; the SELECTED tip of the same domain task
# (ver_h_v2) supersedes the unselected ver_h_v1.
RULE3 = clone(DOMAIN_BASE)
RULE3["context"]["selects"].append(
    {"asset_id": "asset_h2", "version_id": "ver_h_v2"})
add_run_case("fresh_rule3_domain_supersession", RULE3, "run_b")

# rule 4: parent-link supersession — a selected tip whose producing run
# branched FROM the consumed version (parent_version_id == input).
RULE4 = clone(PARENT)
RULE4["context"]["selects"].append(
    {"asset_id": "asset_f2", "version_id": "ver_f2_v1"})
add_run_case("fresh_rule4_parent_supersession", RULE4, "run_f2")

# ---- integrity "modified" branch: payload exists, checksum differs ----
INTEGRITY_MODIFIED = {
    "versions": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v1", "name": "H1",
         "producing_run_id": None},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1", "name": "F1",
         "producing_run_id": "run_f1",
         "path": str(INTEGRITY_MODIFIED_PATH),
         "checksum": "b" * 64, "payload_json": "payload-bytes-v1"},
    ],
    "runs": [
        {"run_id": "run_f1", "operation": "factor_map",
         "input_version_ids": ["ver_h1_v1"],
         "output_version_ids": ["ver_f1_v1"], "status": "complete",
         "started_at": "2026-01-01T00:00:01"},
    ],
    "context": {"selects": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v1"},
    ]},
    "check_integrity": True,
}
add_run_case("fresh_integrity_modified_branch", INTEGRITY_MODIFIED,
             "run_f1")

# ---- step_freshness aggregation ladder branches ----
STEP_RUNNING = clone(STEPS)
STEP_RUNNING["runs"][1]["status"] = "running"
svc_running = build_service(STEP_RUNNING)
add("step_factor_map_running", "freshness.step_freshness",
    {"spec": STEP_RUNNING, "step_type": "factor_map"},
    {"result": svc_running.step_freshness("factor_map").value})

STEP_MISSING = clone(STEPS)
STEP_MISSING["versions"][1]["path"] = "/nonexistent/gone.json"
STEP_MISSING["versions"][1]["checksum"] = "e" * 64
STEP_MISSING["versions"][1]["payload_json"] = "x"
svc_missing = build_service(STEP_MISSING)
add("step_factor_map_missing", "freshness.step_freshness",
    {"spec": STEP_MISSING, "step_type": "factor_map"},
    {"result": svc_missing.step_freshness("factor_map").value})

STEP_UNKNOWN = clone(STEPS)
STEP_UNKNOWN["runs"][1]["input_version_ids"] = []
svc_unknown = build_service(STEP_UNKNOWN)
add("step_factor_map_unknown", "freshness.step_freshness",
    {"spec": STEP_UNKNOWN, "step_type": "factor_map"},
    {"result": svc_unknown.step_freshness("factor_map").value})

STEP_FAILED_LATEST = clone(STEPS)
STEP_FAILED_LATEST["runs"][1]["status"] = "failed"
svc_failed = build_service(STEP_FAILED_LATEST)
add("step_factor_map_failed_latest", "freshness.step_freshness",
    {"spec": STEP_FAILED_LATEST, "step_type": "factor_map"},
    {"result": svc_failed.step_freshness("factor_map").value})

# ---- current_context: domain tip replacement discards the old selection
CTX_DOMAIN_REPLACE = {
    "domain_current": [
        {"domain_task_id": "t1", "version_id": "ver_1"},
        {"domain_task_id": "t1", "version_id": "ver_2"},
    ],
    "selects": [{"asset_id": "a1", "version_id": "ver_1"}],
}
ctx_dr = build_ctx_from_spec(CTX_DOMAIN_REPLACE)
add("ctx_domain_replace", "current_context.reselect",
    {"state": CTX_DOMAIN_REPLACE},
    capture(lambda: {
        "current_by_domain_task": dict(ctx_dr.current_by_domain_task),
        "selected": sorted(ctx_dr.selected_version_ids),
    }))

# ------------------------------------------------------------- recompute_plan


def plan_case(cid: str, spec: dict, project_json: dict | None = None,
              **kwargs):
    svc = build_service(spec)
    project = None
    if project_json is not None:
        project = types.SimpleNamespace(
            prediction_tasks=[types.SimpleNamespace(**t)
                              for t in project_json["prediction_tasks"]],
            paleomap_documents=[types.SimpleNamespace(**d)
                                for d in project_json["paleomap_documents"]],
        )
    add(cid, "recompute.build_plan",
        {"spec": spec, "options": kwargs, "project": project_json},
        capture(lambda: build_recompute_plan(svc, project=project,
                                             **kwargs).to_dict()))


plan_case("plan_stale_all", REUSE)
plan_case("plan_changed_versions", REUSE, changed_version_ids=["ver_h1_v2"])
plan_case("plan_operations_filter", REUSE,
          changed_version_ids=["ver_h1_v2"], operations=["map_compile"])
plan_case("plan_empty", EMPTY_SPEC)
plan_case("plan_cycle", CYCLE)
plan_case("plan_task_links_h11", H11, project_json=H11_PROJECT,
          changed_version_ids=["ver_h1_v2"])

svc = build_service(REUSE)
add("plan_summary_zh", "recompute.summary_zh", {"spec": REUSE},
    capture(lambda: build_recompute_plan(svc).summary_zh()))


def executor_case(cid: str, handler_behavior: str, stop_on_failure=True,
                  cancelled=False):
    """handler_behavior for the map_compile op: "ok" | "fail:<message>"."""
    svc = build_service(REUSE)
    plan = build_recompute_plan(svc)

    def handler(step):
        if handler_behavior.startswith("fail:"):
            raise RuntimeError(handler_behavior[5:])

    handlers = {"factor_map": lambda step: None}
    if handler_behavior:
        handlers["map_compile"] = handler
    executor = PlanExecutor(handlers,
                            generation=0, stop_on_failure=stop_on_failure)
    if cancelled:
        executor.bump_generation()  # pre-cancel via generation guard
    result = executor.execute(plan)
    add(cid, "recompute.execute_plan",
        {"spec": REUSE, "map_compile_handler": handler_behavior,
         "stop_on_failure": stop_on_failure, "cancelled": cancelled},
        {"result": {"stopped_early": result.stopped_early,
                    "messages": result.messages,
                    "completed": plan.completed_run_ids,
                    "failed": plan.failed_run_ids,
                    "skipped": plan.skipped_run_ids}})


executor_case("exec_all_ok", "ok")
executor_case("exec_failure_poisons", "fail:boom: 参数越界")
executor_case("exec_no_handler", "")
executor_case("exec_stop_on_failure_off", "fail:boom",
              stop_on_failure=False)
executor_case("exec_generation_guard", "ok", cancelled=True)

# 3-step chain: middle fails with stop_on_failure=False — the downstream
# consumer of the failed outputs must be POISON-SKIPPED, not executed.
CHAIN3 = {
    "versions": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v1", "name": "H1",
         "producing_run_id": None},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1", "name": "F1",
         "producing_run_id": "run_f1"},
        {"asset_id": "asset_m1", "version_id": "ver_m1_v1", "name": "M1",
         "producing_run_id": "run_m1"},
        {"asset_id": "asset_p1", "version_id": "ver_p1_v1", "name": "P1",
         "producing_run_id": "run_p1"},
    ],
    "runs": [
        {"run_id": "run_f1", "operation": "factor_map",
         "input_version_ids": ["ver_h1_v1"],
         "output_version_ids": ["ver_f1_v1"], "status": "complete",
         "started_at": "2026-01-01T00:00:01"},
        {"run_id": "run_m1", "operation": "map_compile",
         "input_version_ids": ["ver_f1_v1"],
         "output_version_ids": ["ver_m1_v1"], "status": "complete",
         "started_at": "2026-01-01T00:00:02"},
        {"run_id": "run_p1", "operation": "prediction",
         "input_version_ids": ["ver_m1_v1"],
         "output_version_ids": ["ver_p1_v1"], "status": "complete",
         "started_at": "2026-01-01T00:00:03"},
    ],
    "context": {"selects": [
        {"asset_id": "asset_h1", "version_id": "ver_h1_v2x"},
        {"asset_id": "asset_f1", "version_id": "ver_f1_v1"},
        {"asset_id": "asset_m1", "version_id": "ver_m1_v1"},
        {"asset_id": "asset_p1", "version_id": "ver_p1_v1"},
    ]},
}
CHAIN3["versions"][0]["checksum"] = "1" * 64  # current tip content differs
svc_chain = build_service(CHAIN3)
plan_chain = build_recompute_plan(svc_chain)


def executor_chain_case(cid, map_behavior, stop_on_failure=True):
    plan = build_recompute_plan(build_service(CHAIN3))

    def make(op, behavior):
        def handler(step):
            if behavior.startswith("fail:"):
                raise RuntimeError(behavior[5:])
        return handler

    handlers = {"factor_map": make("factor_map", "ok"),
                "prediction": make("prediction", "ok")}
    if map_behavior:
        handlers["map_compile"] = make("map_compile", map_behavior)
    executor = PlanExecutor(handlers, generation=0,
                            stop_on_failure=stop_on_failure)
    result = executor.execute(plan)
    add(cid, "recompute.execute_plan",
        {"spec": CHAIN3,
         "handlers": {"factor_map": "ok", "prediction": "ok",
                      "map_compile": map_behavior},
         "stop_on_failure": stop_on_failure, "cancelled": False,
         "chain": True},
        {"result": {"stopped_early": result.stopped_early,
                    "messages": result.messages,
                    "completed": plan.completed_run_ids,
                    "failed": plan.failed_run_ids,
                    "skipped": plan.skipped_run_ids}})


executor_chain_case("exec_poison_downstream", "fail:编译崩溃",
                    stop_on_failure=False)

# recompute with stale_only=False plans FRESH runs too.
svc_all = build_service(FRESH_CASE)
add("plan_all_states", "recompute.build_plan",
    {"spec": FRESH_CASE, "options": {"stale_only": False}, "project": None},
    capture(lambda: build_recompute_plan(svc_all, stale_only=False).to_dict()))

# ------------------------------------------------------------ constraint_versions
from paleo_workbench.workflow import constraint_versions as cv  # noqa: E402


class FakeCatalogService:
    """Deterministic fake DataCatalogService (constraint lifecycle) — the
    same id scheme C++ RuntimeStore uses (asset_/ver_/run_ %06d, 1s ticks).
    """

    def __init__(self):
        self.assets: list[types.SimpleNamespace] = []
        self.versions: list[types.SimpleNamespace] = []
        self.runs: list[types.SimpleNamespace] = []
        self._n_asset = 0
        self._n_ver = 0
        self._n_run = 0
        self._tick = 0
        self._tmp = Path(tempfile.mkdtemp(prefix="constraint-oracle-"))

    def list_assets(self):
        return list(self.assets)

    def list_versions(self, asset_id=None, **kwargs):
        if asset_id is None:
            return list(self.versions)
        return [v for v in self.versions if v.asset_id == asset_id]

    def list_runs(self):
        return list(self.runs)

    def get_version(self, version_id):
        for v in self.versions:
            if v.id == version_id:
                return v
        return None

    def register_run(self, operation, input_version_ids=None,
                     parameters=None, generator=None, status="running"):
        self._n_run += 1
        run = types.SimpleNamespace(
            id=f"run_{self._n_run:06d}", operation=operation,
            input_version_ids=list(input_version_ids or []),
            output_version_ids=[],
            parameters=dict(parameters or {}),
            generator=generator, status=status)
        self.runs.append(run)
        return run

    def register_result_asset(self, *, name, type, format, asset_metadata,
                              source_path, stage, run_id, version_metadata):
        self._n_asset += 1
        asset = types.SimpleNamespace(
            id=f"asset_{self._n_asset:06d}", name=name, type=type,
            format=format, current_version_id=None,
            metadata=dict(asset_metadata or {}))
        self.assets.append(asset)
        payload = Path(source_path).read_text(encoding="utf-8")
        version = self._make_version(asset, payload, version_metadata, run_id)
        asset.current_version_id = version.id
        run = next(r for r in self.runs if r.id == run_id)
        run.output_version_ids.append(version.id)
        return version

    def register_version(self, asset_id, source_path, stage,
                         parent_version_ids=None, run_id=None, metadata=None):
        asset = next(a for a in self.assets if a.id == asset_id)
        payload = Path(source_path).read_text(encoding="utf-8")
        version = self._make_version(asset, payload, metadata or {}, run_id)
        if run_id:
            run = next(r for r in self.runs if r.id == run_id)
            run.output_version_ids.append(version.id)
        return version

    def update_run_status(self, run_id, status):
        run = next(r for r in self.runs if r.id == run_id)
        run.status = status

    def _make_version(self, asset, payload, metadata, run_id):
        self._n_ver += 1
        self._tick += 1
        digest = hashlib.sha256(payload.encode()).hexdigest()
        path = self._tmp / f"v{self._n_ver}.json"
        path.write_text(payload, encoding="utf-8")
        version = types.SimpleNamespace(
            id=f"ver_{self._n_ver:06d}",
            asset_id=asset.id,
            name=asset.name,
            producing_run_id=run_id,
            checksum=digest,
            trashed=False,
            path="",
            created_at=f"2026-01-01T00:00:{self._tick:02d}",
            metadata=dict(metadata or {}),
            source_uri=str(path),
            payload=payload,
        )
        self.versions.append(version)
        return version


def group_ns(group: dict):
    """Json group dict -> the namespace shape the Python module reads."""
    return types.SimpleNamespace(
        id=group["id"], name=group.get("name", ""),
        target_horizon=group.get("target_horizon", ""),
        crs=group.get("crs"),
        lines=[
            types.SimpleNamespace(
                id=line["id"], name=line.get("name", ""),
                role=line.get("role", ""),
                active=line.get("active", True),
                # The REAL document model gives each line its OWN
                # target_horizon (default "") — no group fallback.
                target_horizon=line.get("target_horizon", ""),
                coordinates=[list(p) for p in line.get("coordinates", [])],
                azimuth_deg=line.get("azimuth_deg"),
                semi_major=line.get("semi_major"),
                semi_minor=line.get("semi_minor"),
                properties=line.get("properties", {}),
            )
            for line in group.get("lines", [])
        ],
    )


GROUP_G1 = {
    "id": "g1", "name": "断层约束A", "target_horizon": "H1", "crs": None,
    "lines": [
        {"id": "l1", "name": "F1-a", "role": "fault", "active": True,
         "coordinates": [[0.0, 0.0], [1.0, 1.0000000004], [2.0, 0.5]],
         "properties": {"constraint_kind": "fault", "layer_id": "lyr1"}},
        {"id": "l2", "name": "F1-b", "role": "fault", "active": True,
         "coordinates": [[5.0, 5.0], [6.0, 6.0]]},
        {"id": "l3", "active": False,
         "coordinates": [[9.0, 9.0], [9.1, 9.1]]},
        {"id": "l4", "active": True, "coordinates": []},
    ],
}
GROUP_G1_SHUFFLED = {
    "id": "g9", "name": "other name", "target_horizon": "H1",
    "lines": [
        {"id": "zz", "name": "F1-b", "role": "fault", "active": True,
         "coordinates": [[5.0, 5.0], [6.0, 6.0]]},
        {"id": "aa", "name": "F1-a", "role": "fault", "active": True,
         "coordinates": [[0.0, 0.0], [1.0, 1.0000000004], [2.0, 0.5]],
         "properties": {"constraint_kind": "fault", "layer_id": "lyr1"}},
    ],
}
GROUP_EMPTY = {"id": "g2", "name": "空", "target_horizon": "H2", "lines": []}
GROUP_G1_V2 = {
    "id": "g1", "name": "断层约束A", "target_horizon": "H1",
    "lines": [
        {"id": "l1", "name": "F1-a", "role": "fault", "active": True,
         "coordinates": [[0.0, 0.0], [1.0, 1.5], [2.0, 0.5]],
         "properties": {"constraint_kind": "fault", "layer_id": "lyr1"}},
        {"id": "l2", "name": "F1-b", "role": "fault", "active": True,
         "coordinates": [[5.0, 5.0], [6.0, 7.0]]},
    ],
}
GROUP_G1_V3 = {
    "id": "g1", "name": "断层约束A", "target_horizon": "H1",
    "lines": [
        {"id": "l1", "active": True, "role": "fault",
         "coordinates": [[0.0, 0.0], [3.0, 3.0]]},
    ],
}
GROUP_UTF8 = {
    "id": "群组–β", "name": "约束·层位Ⅲ", "target_horizon": "层位——H①",
    "lines": [
        {"id": "线–1", "name": "断裂α", "role": "断层", "active": True,
         "coordinates": [[1.25, 2.5], [3.75, 4.0]],
         "properties": {"constraint_kind": "断层面", "layer_id": "图层一"}},
    ],
}

for cid, group in [("cv_hash_g1", GROUP_G1),
                   ("cv_hash_shuffled", GROUP_G1_SHUFFLED),
                   ("cv_hash_empty", GROUP_EMPTY),
                   ("cv_hash_utf8", GROUP_UTF8)]:
    add(cid, "constraint.content_hash", {"group": group},
        capture(lambda group=group: cv.constraint_group_content_hash(
            group_ns(group))))


def setup_catalog(setup_groups: list[dict]) -> FakeCatalogService:
    cat = FakeCatalogService()
    for group in setup_groups:
        cv.commit_constraint_group(object(), cat, group_ns(group),
                                   actor="oracle-setup")
    return cat


def commit_case(cid: str, setup: list[dict], group: dict, actor: str = "",
                notes: str = ""):
    cat = setup_catalog(setup)
    add(cid, "constraint.commit",
        {"setup": setup, "group": group, "actor": actor, "notes": notes},
        capture(lambda: cv.commit_constraint_group(
            object(), cat, group_ns(group), actor=actor, notes=notes
        ).to_dict()))


commit_case("cv_commit_no_content", [], GROUP_EMPTY)
commit_case("cv_commit_first", [], GROUP_G1, actor="tester", notes="初版")
commit_case("cv_commit_unchanged", [GROUP_G1], GROUP_G1, actor="tester")
commit_case("cv_commit_changed", [GROUP_G1], GROUP_G1_V2, actor="tester",
            notes="改线")
commit_case("cv_commit_utf8", [], GROUP_UTF8, actor="测试者")

# setup for everything below: V1 then V2 committed.
SETUP_V2 = [GROUP_G1, GROUP_G1_V2]


def current_case(cid: str, group_id: str):
    cat = setup_catalog(SETUP_V2)
    add(cid, "constraint.current_version", {"setup": SETUP_V2,
                                            "group_id": group_id},
        capture(lambda: (lambda v: None if v is None else str(v.id))(
            cv.current_constraint_version(cat, group_id))))


current_case("cv_current_version", "g1")
current_case("cv_current_version_never", "g_missing")


def pins_case(cid: str, task: dict, project_groups: list[dict],
              with_catalog: bool):
    cat = setup_catalog(SETUP_V2)
    project = types.SimpleNamespace(
        constraint_layers=[group_ns(g) for g in project_groups])
    task_ns = types.SimpleNamespace(
        id=task.get("id", ""), name=task.get("name", ""),
        target_horizon=task.get("target_horizon", ""),
        parameters=task.get("parameters", {}))
    add(cid, "constraint.pins_for_task",
        {"setup": SETUP_V2, "task": task, "project_groups": project_groups,
         "with_catalog": with_catalog},
        capture(lambda: cv.constraint_pins_for_task(
            task_ns, project, cat if with_catalog else None)))


TASK_F1 = {"id": "task_f1", "name": "F1", "target_horizon": "H1",
           "parameters": {}}
TASK_OTHER_HORIZON = {"id": "task_x", "name": "X", "target_horizon": "H9",
                      "parameters": {}}

pins_case("cv_pins_for_task", TASK_F1, [GROUP_G1_V2], True)
pins_case("cv_pins_uncommitted", TASK_F1, [GROUP_G1_V3], True)
pins_case("cv_pins_horizon_scope", TASK_OTHER_HORIZON, [GROUP_G1_V2], True)
pins_case("cv_pins_no_catalog", TASK_F1, [GROUP_G1_V2], False)
pins_case("cv_pins_utf8",
          {"id": "任务一", "name": "任务·厚度", "target_horizon": "层位——H①",
           "parameters": {}},
          [GROUP_UTF8], False)


def staleness_case(cid: str, task: dict, project_groups: list[dict],
                   with_catalog: bool):
    cat = setup_catalog(SETUP_V2)
    project = types.SimpleNamespace(
        constraint_layers=[group_ns(g) for g in project_groups])
    task_ns = types.SimpleNamespace(
        id=task.get("id", ""), target_horizon=task.get("target_horizon", ""),
        parameters=task.get("parameters", {}))
    add(cid, "constraint.pins_staleness",
        {"setup": SETUP_V2, "task": task, "project_groups": project_groups,
         "with_catalog": with_catalog},
        capture(lambda: cv.constraint_pins_staleness(
            task_ns, project, cat if with_catalog else None)))


def pin_of(group: dict) -> dict:
    hash_, n = cv.constraint_group_content_hash(group_ns(group))
    return {"group_id": group["id"], "group_name": group.get("name", ""),
            "content_hash": hash_, "line_count": n, "version_id": None}


staleness_case(
    "cv_staleness_stale_content",
    {"id": "task_f1", "target_horizon": "H1",
     "parameters": {"constraint_pins": [pin_of(GROUP_G1)]}},
    [GROUP_G1_V3], True)
staleness_case(
    "cv_staleness_uncommitted_pin",
    {"id": "task_f1", "target_horizon": "H1",
     "parameters": {"constraint_pins": [pin_of(GROUP_G1_V3)]}},
    [GROUP_G1_V3], True)
staleness_case(
    "cv_staleness_current",
    {"id": "task_f1", "target_horizon": "H1",
     "parameters": {"constraint_pins": [pin_of(GROUP_G1_V2)]}},
    [GROUP_G1_V2], True)
staleness_case(
    "cv_staleness_stale_version",
    {"id": "task_f1", "target_horizon": "H1",
     "parameters": {"constraint_pins": [pin_of(GROUP_G1)]}},
    [GROUP_G1], True)
staleness_case("cv_staleness_unpinned",
               {"id": "task_f1", "target_horizon": "H1", "parameters": {}},
               [GROUP_G1_V3], True)
staleness_case(
    "cv_staleness_missing",
    {"id": "task_f1", "target_horizon": "H1",
     "parameters": {"constraint_pins": [
         {"group_id": "g_gone", "content_hash": "deadbeef",
          "line_count": 2, "version_id": "ver_000001"}]}},
    [], True)
staleness_case(
    "cv_staleness_no_catalog_version_pin",
    {"id": "task_f1", "target_horizon": "H1",
     "parameters": {"constraint_pins": [
         dict(pin_of(GROUP_G1_V2), version_id="ver_000002")]}},
    [GROUP_G1_V2], False)
staleness_case(
    "cv_staleness_no_catalog",
    {"id": "task_f1", "target_horizon": "H1",
     "parameters": {"constraint_pins": [pin_of(GROUP_G1_V2)]}},
    [GROUP_G1_V2], False)


def commit_all_case(cid: str, groups: list[dict], actor: str = ""):
    cat = FakeCatalogService()
    project = types.SimpleNamespace(
        constraint_layers=[group_ns(g) for g in groups])
    add(cid, "constraint.commit_all", {"groups": groups, "actor": actor},
        capture(lambda: [r.to_dict() for r in cv.commit_all_constraints(
            project, cat, actor=actor)]))


# true order-invariance: same names/horizon/group-name, only line ids and
# order differ -> hash EQUALS GROUP_G1's.
GROUP_G1_REORDERED = {
    "id": "gX", "name": "断层约束A", "target_horizon": "H1",
    "lines": [
        {"id": "zz-last", "name": "F1-b", "role": "fault", "active": True,
         "coordinates": [[5.0, 5.0], [6.0, 6.0]]},
        {"id": "aa-first", "name": "F1-a", "role": "fault", "active": True,
         "coordinates": [[0.0, 0.0], [1.0, 1.0000000004], [2.0, 0.5]],
         "properties": {"constraint_kind": "fault", "layer_id": "lyr1"}},
    ],
}
add("cv_hash_reordered_equal", "constraint.content_hash",
    {"group": GROUP_G1_REORDERED},
    capture(lambda: cv.constraint_group_content_hash(
        group_ns(GROUP_G1_REORDERED))))

# pins: explicit line target_horizon participates in identity.
GROUP_WITH_LINE_HORIZONS = {
    "id": "gH", "name": "层位约束", "target_horizon": "H1",
    "lines": [
        {"id": "h1", "active": True, "role": "fault",
         "target_horizon": "H2",
         "coordinates": [[0.0, 0.0], [1.0, 1.0]]},
    ],
}
add("cv_hash_line_horizon", "constraint.content_hash",
    {"group": GROUP_WITH_LINE_HORIZONS},
    capture(lambda: cv.constraint_group_content_hash(
        group_ns(GROUP_WITH_LINE_HORIZONS))))

commit_all_case("cv_commit_all", [GROUP_G1, GROUP_EMPTY], actor="批量")


def compare_case(cid: str, setup: list[dict], a_idx: int, b_idx: int):
    cat = setup_catalog(setup)
    versions = cat.list_versions(next(
        a for a in cat.assets
        if a.metadata.get("constraint_group_id") == setup[0]["id"]).id)
    a, b = versions[a_idx], versions[b_idx]
    add(cid, "constraint.compare",
        {"setup": setup, "a": a.id, "b": b.id},
        capture(lambda: cv.compare_constraint_versions(cat, a.id, b.id)))


compare_case("cv_compare", [GROUP_G1, GROUP_G1_V2], 0, -1)
# raise parity: version id unknown to the catalog.
add("cv_compare_missing_version", "constraint.compare",
    {"setup": SETUP_V2, "a": "ver_999999", "b": "ver_000001"},
    capture(lambda: cv.compare_constraint_versions(
        setup_catalog(SETUP_V2), "ver_999999", "ver_000001")))
# identical payloads -> identical=True (same version twice).
def compare_same_case(cid: str, setup: list[dict]):
    cat = setup_catalog(setup)
    versions = cat.list_versions(next(
        a for a in cat.assets
        if a.metadata.get("constraint_group_id") == setup[0]["id"]).id)
    add(cid, "constraint.compare",
        {"setup": setup, "a": versions[0].id, "b": versions[0].id},
        capture(lambda: cv.compare_constraint_versions(
            cat, versions[0].id, versions[0].id)))


compare_same_case("cv_compare_identical", [GROUP_G1])


def resolve_case(cid: str, project_groups: list[dict], ref: str,
                 with_catalog: bool):
    cat = setup_catalog(SETUP_V2)
    project = types.SimpleNamespace(
        constraint_layers=[group_ns(g) for g in project_groups])
    add(cid, "constraint.resolve_ref",
        {"setup": SETUP_V2, "project_groups": project_groups, "ref": ref,
         "with_catalog": with_catalog},
        capture(lambda: cv.resolve_constraint_ref(
            project, cat if with_catalog else None, ref)))


resolve_case("cv_ref_current_doc_dirty", [GROUP_G1_V3],
             "constraints:current", True)
resolve_case("cv_ref_current_matches", [GROUP_G1_V2],
             "constraints:current", True)


def pinned_ref_case(cid: str, project_groups: list[dict], pinned: str):
    """pinned: "latest" | "oldest" — the ref is frozen at generate time."""
    cat = setup_catalog(SETUP_V2)
    versions = cat.list_versions(next(
        a for a in cat.assets
        if a.metadata.get("constraint_group_id") == "g1").id)
    version_id = versions[-1].id if pinned == "latest" else versions[0].id
    project = types.SimpleNamespace(
        constraint_layers=[group_ns(g) for g in project_groups])
    add(cid, "constraint.resolve_ref",
        {"setup": SETUP_V2, "project_groups": project_groups,
         "ref": f"constraints:g1:{version_id}", "with_catalog": True},
        capture(lambda: cv.resolve_constraint_ref(
            project, cat, f"constraints:g1:{version_id}")))


resolve_case("cv_ref_current_never_committed", [GROUP_UTF8],
             "constraints:current", True)
add("cv_ref_pinned_no_version", "constraint.resolve_ref",
    {"setup": SETUP_V2, "project_groups": [GROUP_G1_V2],
     "ref": "constraints:g1", "with_catalog": True},
    capture(lambda: cv.resolve_constraint_ref(
        types.SimpleNamespace(
            constraint_layers=[group_ns(g) for g in [GROUP_G1_V2]]),
        setup_catalog(SETUP_V2), "constraints:g1")))
add("cv_ref_empty_constraints", "constraint.resolve_ref",
    {"setup": SETUP_V2, "project_groups": [], "ref": "constraints:current",
     "with_catalog": True},
    capture(lambda: cv.resolve_constraint_ref(
        types.SimpleNamespace(constraint_layers=[]),
        setup_catalog(SETUP_V2), "constraints:current")))
pinned_ref_case("cv_ref_pinned_latest", [GROUP_G1_V2], "latest")
pinned_ref_case("cv_ref_pinned_superseded", [GROUP_G1_V2], "oldest")
resolve_case("cv_ref_unknown_shape", [GROUP_G1_V2], "bogus:ref", True)
resolve_case("cv_ref_no_catalog", [GROUP_G1_V2], "constraints:current",
             False)

# ------------------------------------------------------------- provenance_graph
from paleo_workbench.workflow.provenance_graph import (  # noqa: E402
    build_product_lifecycle_graph,
)

PROV_PROJECT = {
    "map_products": [
        {"id": "prod1", "product_name": "沙三期古地理图", "frozen": True,
         "status": "published", "superseded_by": None,
         "factor_task_ids": ["task_f1"]},
    ],
    "factor_map_tasks": [
        {"id": "task_f1", "name": "砂岩厚度", "method": "idw",
         "source_kind": "samples", "grid_artifact_version_id": "ver_grid_1",
         "parameters": {"constraint_pins": [
             {"group_id": "g1", "group_name": "断层约束A",
              "content_hash": "h" * 64, "version_id": "ver_000001"},
         ]}},
    ],
}
PROV_RUNS = [
    {"id": "run_000009", "operation": "factor_fusion",
     "input_version_ids": ["ver_grid_1", "ver_grid_2"],
     "output_version_ids": ["ver_fusion_1"]},
    {"id": "run_000010", "operation": "factor_map",
     "input_version_ids": ["ver_h1"], "output_version_ids": ["ver_grid_2"]},
    {"id": "run_000011", "operation": "factor_fusion:confidence",
     "input_version_ids": ["ver_fusion_1"],
     "output_version_ids": ["ver_conf_1"]},
]
PROV_NO_GRID_PROJECT = {
    "map_products": [
        {"id": "prod2", "product_name": "无网格", "frozen": False,
         "status": "draft", "superseded_by": "prod3",
         "factor_task_ids": ["task_no_grid"]},
    ],
    "factor_map_tasks": [
        {"id": "task_no_grid", "name": "无网格任务", "method": "kriging",
         "source_kind": "samples", "grid_artifact_version_id": None,
         "parameters": {}},
    ],
}


def prov_case(cid: str, project: dict, runs: list[dict] | None,
              product_id: str | None = None):
    project_ns = types.SimpleNamespace(
        map_products=[types.SimpleNamespace(**r)
                      for r in project["map_products"]],
        factor_map_tasks=[types.SimpleNamespace(**t)
                          for t in project["factor_map_tasks"]],
    )
    catalog = None
    if runs is not None:
        catalog = types.SimpleNamespace(
            list_runs=lambda: [types.SimpleNamespace(
                id=r["id"], operation=r["operation"],
                input_version_ids=r["input_version_ids"],
                output_version_ids=r["output_version_ids"])
                for r in runs])
    add(cid, "provenance.lifecycle_graph",
        {"project": project, "runs": runs, "product_id": product_id},
        capture(lambda: build_product_lifecycle_graph(
            project_ns, catalog, product_id=product_id)))


prov_case("prov_lifecycle", PROV_PROJECT, PROV_RUNS)
prov_case("prov_lifecycle_one_product", PROV_PROJECT, PROV_RUNS, "prod1")
prov_case("prov_lifecycle_unknown_product", PROV_PROJECT, PROV_RUNS, "prodX")
prov_case("prov_lifecycle_gap", PROV_NO_GRID_PROJECT, PROV_RUNS)
prov_case("prov_lifecycle_no_catalog", PROV_PROJECT, None)

# ------------------------------------------------------------------ staleness
for cid, value in [
    ("stale_pin_current", "current"), ("stale_pin_unpinned", "unpinned"),
    ("stale_pin_unknown", "unknown"), ("stale_pin_missing", "missing"),
    ("stale_pin_stale_version", "stale_version"),
    ("stale_pin_stale_content", "stale_content"),
    ("stale_pin_uncommitted", "uncommitted"), ("stale_pin_junk", "wat"),
]:
    add(cid, "staleness.from_constraint_pin", {"state": value},
        {"result": from_constraint_pin(value).value})
for cid, value in [
    ("stale_ws_current", "current"), ("stale_ws_stale", "stale"),
    ("stale_ws_missing", "missing_input"), ("stale_ws_superseded",
                                            "superseded"),
    ("stale_ws_unknown", "unknown"), ("stale_ws_junk", "junk"),
]:
    add(cid, "staleness.from_workspace_status", {"status": value},
        {"result": from_workspace_status(value).value})
for cid, value in [
    ("stale_run_fresh", "fresh"), ("stale_run_stale", "stale"),
    ("stale_run_unknown", "unknown"), ("stale_run_missing", "missing"),
    ("stale_run_failed", "failed"), ("stale_run_running", "running"),
]:
    add(cid, "staleness.from_run_freshness", {"state": value},
        {"result": from_run_freshness(value).value})
verdict = ArtifactVerdict(
    artifact_key="mapproduct:p1", verdict=StalenessVerdict.STALE_VERSION,
    detail="上游已更新", upstream_culprits=("factor:t1", "factor:t2"))
add("stale_verdict_dict", "staleness.verdict_dict",
    {"artifact_key": "mapproduct:p1", "verdict": "stale_version",
     "detail": "上游已更新", "upstream_culprits": ["factor:t1", "factor:t2"]},
    capture(lambda: verdict.to_dict()))

# ----------------------------------------------------------------------- write
FIXTURE.parent.mkdir(parents=True, exist_ok=True)
FIXTURE.write_text(
    json.dumps({"cases": cases}, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"wrote {len(cases)} cases to {FIXTURE}")
