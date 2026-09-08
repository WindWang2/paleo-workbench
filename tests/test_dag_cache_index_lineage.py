"""V8 M7 — DAG cache index (no full-history rescan) + run lineage."""

from __future__ import annotations

import json

import pytest

from paleo_workbench.workflow.dag.model import (
    NodeRun,
    NodeState,
    RunState,
    WorkflowRun,
)
from paleo_workbench.workflow.dag.store import (
    WorkflowRunStore,
    find_reusable_node,
    run_lineage,
)


def _spec_dict(node_ids):
    return {
        "workflow_id": "wf-test",
        "name": "wf-test",
        "nodes": [
            {"node_id": nid, "action_id": "seismic.compute_attribute", "inputs": {}}
            for nid in node_ids
        ],
        "edges": [],
    }


def _run(run_id, nodes, *, state=RunState.COMPLETED, parent=None):
    from paleo_workbench.workflow.dag.model import WorkflowSpec

    spec = WorkflowSpec.from_dict(_spec_dict(nodes))
    run = WorkflowRun.create(spec, {})
    run.run_id = run_id
    run.state = state
    run.parent_run_id = parent
    for nid in nodes:
        nr = NodeRun(node_id=nid, state=NodeState.SUCCEEDED)
        nr.cache_identity = f"identity-{nid}"
        nr.output_version_ids = (f"ver-{run_id}-{nid}",)
        run.node_runs[nid] = nr
    return run


class TestCacheIndex:
    def test_lookup_avoids_full_history_rescan(self, tmp_path, monkeypatch):
        store = WorkflowRunStore(tmp_path)
        for i in range(30):
            store.save(_run(f"run{i:02d}", ["n1"]))

        # warm the index first: the counted phase is the LOOKUP, not the
        # one-time build scan
        store.candidates_for_identity("identity-n1")
        loads = {"count": 0}
        real_load = store.load

        def counting_load(run_id):
            loads["count"] += 1
            return real_load(run_id)

        monkeypatch.setattr(store, "load", counting_load)
        found = find_reusable_node(store, cache_identity="identity-n1")
        assert found is not None
        # newest-first: the first candidate matches, so exactly ONE run file
        # is deserialized (the old path parsed all 30).
        assert loads["count"] == 1
        assert found.output_version_ids[0] == "ver-run29-n1"

    def test_index_updated_incrementally_on_save(self, tmp_path):
        store = WorkflowRunStore(tmp_path)
        store.save(_run("r1", ["n1"]))
        # force index build
        assert store.candidates_for_identity("identity-n1")
        # a new run saved AFTER the build lands in the index without rebuild
        store.save(_run("r2", ["n2"]))
        assert store.candidates_for_identity("identity-n2") == [("r2", "n2")]

    def test_index_skips_running_and_from_cache_nodes(self, tmp_path):
        store = WorkflowRunStore(tmp_path)
        running = _run("running", ["n1"], state=RunState.RUNNING)
        store.save(running)
        store.rebuild_cache_index()
        assert store.candidates_for_identity("identity-n1") == []

        cached = _run("cached", ["n1"])
        cached.node_runs["n1"].from_cache = True
        store.save(cached)
        store.rebuild_cache_index()
        assert store.candidates_for_identity("identity-n1") == []

    def test_identity_miss_is_cheap(self, tmp_path, monkeypatch):
        store = WorkflowRunStore(tmp_path)
        store.save(_run("r1", ["n1"]))
        store.candidates_for_identity("identity-n1")  # warm the index
        loads = {"count": 0}
        real_load = store.load

        def counting_load(run_id):
            loads["count"] += 1
            return real_load(run_id)

        monkeypatch.setattr(store, "load", counting_load)
        assert find_reusable_node(store, cache_identity="identity-missing") is None
        assert loads["count"] == 0  # no candidate → zero deserializations

    def test_lookup_result_matches_old_scan_semantics(self, tmp_path):
        """Index candidates still pass the full validation contract."""
        store = WorkflowRunStore(tmp_path)
        store.save(_run("r1", ["n1"]))
        # a candidate whose outputs are NOT resolvable is skipped (catalog None
        # short-circuits; simulate by empty output ids)
        bad = _run("r2", ["n1"])
        bad.node_runs["n1"].output_version_ids = ()
        store.save(bad)
        found = find_reusable_node(store, cache_identity="identity-n1")
        assert found is not None
        assert found.output_version_ids[0] == "ver-r1-n1"


class TestRunLineage:
    def test_rerun_chain_walks_parents(self, tmp_path):
        store = WorkflowRunStore(tmp_path)
        store.save(_run("orig", ["n1"]))
        store.save(_run("child", ["n1"], parent="orig"))
        store.save(_run("grandchild", ["n1"], parent="child"))
        assert run_lineage(store, "grandchild") == ["orig", "child", "grandchild"]
        assert run_lineage(store, "orig") == ["orig"]

    def test_missing_parent_stops_chain(self, tmp_path):
        store = WorkflowRunStore(tmp_path)
        store.save(_run("orphan", ["n1"], parent="vanished"))
        assert run_lineage(store, "orphan") == ["vanished", "orphan"] or (
            run_lineage(store, "orphan") == ["orphan"]
        )

    def test_cycle_guard(self, tmp_path):
        store = WorkflowRunStore(tmp_path)
        store.save(_run("a", ["n1"], parent="b"))
        store.save(_run("b", ["n1"], parent="a"))
        chain = run_lineage(store, "a")
        assert chain[-1] == "a" and len(chain) == 2

    def test_persisted_parent_field_roundtrips(self, tmp_path):
        store = WorkflowRunStore(tmp_path)
        store.save(_run("with-parent", ["n1"], parent="source"))
        loaded = store.load("with-parent")
        assert loaded.parent_run_id == "source"
        # serialized form carries the field
        data = json.loads((tmp_path / "run-with-parent.json").read_text("utf-8"))
        assert data["parent_run_id"] == "source"
