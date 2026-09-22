"""Reproduction contract (H12): explain how to re-run a workflow run from
the same facts — normalized parameters, input version ids, action/provider
versions, environment identity and output hashes.

This is an *explanation*, not a promise of cross-platform bit-identity:
providers record whether they are deterministic; outputs carry catalog
checksums; the environment block states the python/platform/build the run
actually used.
"""
from __future__ import annotations

from typing import Any

from paleo_workbench.workflow.dag.model import WorkflowRun


def describe_reproduction(run: WorkflowRun) -> dict[str, Any]:
    """Build the reproduction description for one persisted run."""
    nodes = []
    for node in run.workflow.nodes:
        node_run = run.node_runs.get(node.node_id)
        receipt = (node_run.receipt if node_run else None) or {}
        entry: dict[str, Any] = {
            "node_id": node.node_id,
            "action_id": node.action_id,
            "action_version": receipt.get("action_version"),
            "deterministic_action": None,
            "parameters": node_run.parameters if node_run else {},
            "input_version_ids": list(node_run.input_version_ids) if node_run else [],
            "output_version_ids": list(node_run.output_version_ids) if node_run else [],
            "provider_id": receipt.get("provider_id"),
            "provider_version": receipt.get("provider_version"),
            "cache_identity": receipt.get("cache_identity") or node_run.cache_identity
            if node_run
            else None,
            "from_cache": node_run.from_cache if node_run else None,
            "executed": node_run is not None
            and node_run.state.value == "succeeded"
            and not node_run.from_cache,
        }
        nodes.append(entry)
    environment = None
    for node_run in run.node_runs.values():
        if node_run.receipt and node_run.receipt.get("environment"):
            environment = node_run.receipt["environment"]
            break
    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow.workflow_id,
        "workflow_schema_version": run.workflow.schema_version,
        "spec_hash": run.spec_hash,
        "slot_values": dict(run.slot_values),
        "project": {"name": run.project_name, "path": run.project_path},
        "nodes": nodes,
        "environment": environment,
        "contract": {
            "bit_identity": (
                "promised only for nodes whose action/provider declares "
                "deterministic and whose input version ids match"
            ),
            "how_to_rerun": (
                "load the recipe saved from this run, rebind slots, and run "
                "through workflow.run — completed nodes with matching cache "
                "identity are reused, everything else re-executes"
            ),
        },
    }
