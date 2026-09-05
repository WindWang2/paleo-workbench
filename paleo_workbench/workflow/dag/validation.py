"""Static + runtime validation for workflow DAGs (H2, fail-closed).

``validate_workflow_spec`` is the registration/run gate: unknown actions,
duplicate or missing nodes, cycles, dangling references, malformed
conditions and impossible bindings are all rejected *before* anything
executes. ``bind_parameters`` resolves typed markers into concrete values
at run time and re-checks them against the action's input schema.
"""
from __future__ import annotations

import re
from typing import Any

from paleo_workbench.harness.registry import ActionRegistry
from paleo_workbench.providers.execution import validate_parameters
from paleo_workbench.workflow.dag.model import (
    NodeCondition,
    NodeSpec,
    WorkflowSpec,
    validate_condition_tree,
)

_NODE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SLOT_RE = re.compile(r"^[a-z][a-z0-9_]*$")

#: Whitelist of context fields a ``{"$context": ...}`` binding may read.
CONTEXT_BINDING_WHITELIST = frozenset(
    {
        "workspace_id",
        "project_path",
        "active_survey_id",
        "active_well_id",
        "current_map_id",
        "selection.active_well_id",
        "selection.selected_well_ids",
        "selection.seismic_cursor",
        "selection.depth_range",
    }
)


def validate_workflow_spec(spec: WorkflowSpec, registry: ActionRegistry) -> list[str]:
    problems: list[str] = []
    if not spec.workflow_id or not re.match(r"^[a-z][a-z0-9_.-]{1,63}$", spec.workflow_id):
        problems.append(f"workflow_id {spec.workflow_id!r} must match ^[a-z][a-z0-9_.-]{{1,63}}$")
    if not spec.nodes:
        problems.append("workflow needs at least one node")
    if spec.max_concurrency < 1:
        problems.append("max_concurrency must be >= 1")

    seen: dict[str, NodeSpec] = {}
    for node in spec.nodes:
        if not _NODE_ID_RE.match(node.node_id):
            problems.append(f"node_id {node.node_id!r} must match {_NODE_ID_RE.pattern}")
        if node.node_id in seen:
            problems.append(f"duplicate node id {node.node_id!r}")
            continue
        seen[node.node_id] = node
        try:
            action = registry.get(node.action_id)
        except LookupError:
            problems.append(f"node {node.node_id!r}: unknown action {node.action_id!r}")
            continue
        if action.risk.value == "destructive":  # pragma: no cover - registry refuses these
            problems.append(f"node {node.node_id!r}: DESTRUCTIVE actions cannot appear in workflows")
        if node.retry.max_attempts < 1:
            problems.append(f"node {node.node_id!r}: retry.max_attempts must be >= 1")
        if node.condition is not None:
            problems.extend(
                f"node {node.node_id!r}: {p}"
                for p in validate_condition_tree(node.condition)
            )

    slot_names = {s.name for s in spec.slots}
    for slot in spec.slots:
        if not _SLOT_RE.match(slot.name):
            problems.append(f"slot name {slot.name!r} must match {_SLOT_RE.pattern}")
    if len(slot_names) != len(spec.slots):
        problems.append("duplicate slot names")

    for node in spec.nodes:
        for dep in node.depends_on:
            if dep not in seen:
                problems.append(f"node {node.node_id!r}: dependency {dep!r} does not exist")
            elif dep == node.node_id:
                problems.append(f"node {node.node_id!r}: self-dependency")
        if node.condition is not None:
            for ref in _condition_nodes(node.condition):
                if ref not in seen:
                    problems.append(
                        f"node {node.node_id!r}: condition references unknown node {ref!r}"
                    )
        for problem in _binding_problems(node, seen, slot_names):
            problems.append(f"node {node.node_id!r}: {problem}")

    problems.extend(_cycle_problems(spec))
    return problems


def _condition_nodes(condition: NodeCondition) -> set[str]:
    refs: set[str] = set()
    if condition.node:
        refs.add(condition.node)
    for sub in condition.conditions:
        refs |= _condition_nodes(sub)
    if condition.condition is not None:
        refs |= _condition_nodes(condition.condition)
    return refs


def _binding_problems(node: NodeSpec, seen: dict[str, NodeSpec], slot_names: set[str]) -> list[str]:
    problems: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if set(value.keys()) == {"$slot"}:
                name = value["$slot"]
                if not isinstance(name, str) or name not in slot_names:
                    problems.append(f"binding $slot {name!r} is not a declared slot")
            elif set(value.keys()) == {"$ref"}:
                ref = value["$ref"]
                if not isinstance(ref, str) or ref not in seen:
                    problems.append(f"binding $ref {ref!r} is not a node in this workflow")
                elif ref not in node.depends_on:
                    problems.append(
                        f"binding $ref {ref!r} must be listed in depends_on "
                        "(data dependencies are explicit)"
                    )
            elif set(value.keys()) == {"$context"}:
                key = value["$context"]
                if not isinstance(key, str) or key not in CONTEXT_BINDING_WHITELIST:
                    problems.append(
                        f"binding $context {key!r} is not whitelisted {sorted(CONTEXT_BINDING_WHITELIST)}"
                    )
            elif "$ref" in value or "$slot" in value or "$context" in value:
                problems.append(
                    "binding objects must be exactly one of "
                    '{"$slot": name} / {"$ref": node} / {"$context": key}'
                )
            else:
                for v in value.values():
                    walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(node.parameters)
    return problems


def _cycle_problems(spec: WorkflowSpec) -> list[str]:
    """Kahn's algorithm; every leftover node is part of a cycle."""
    indegree = {n.node_id: 0 for n in spec.nodes}
    consumers: dict[str, list[str]] = {n.node_id: [] for n in spec.nodes}
    for node in spec.nodes:
        for dep in node.depends_on:
            if dep in indegree:
                indegree[node.node_id] += 1
                consumers[dep].append(node.node_id)
    queue = sorted(n for n, d in indegree.items() if d == 0)
    visited = 0
    while queue:
        current = queue.pop()
        visited += 1
        for consumer in consumers[current]:
            indegree[consumer] -= 1
            if indegree[consumer] == 0:
                queue.append(consumer)
    if visited == len(spec.nodes):
        return []
    cyclic = sorted(n for n, d in indegree.items() if d > 0)
    return [f"dependency cycle among nodes {cyclic}"]


class BindingError(ValueError):
    """A binding could not be resolved at run time (fail-closed)."""


def _context_value(context: Any, key: str) -> Any:
    if "." in key:
        head, tail = key.split(".", 1)
        base = getattr(context, head, None)
        value = getattr(base, tail, None) if base is not None else None
    else:
        value = getattr(context, key, None)
    if value is None:
        raise BindingError(f"context binding {key!r} is not available in this session")
    if isinstance(value, tuple):
        value = list(value)
    return value


def resolve_value(value: Any, *, run: Any, results: dict[str, Any]) -> Any:
    """Recursively resolve one parameter value.

    ``run`` provides slot values; ``results`` maps node_id → the node's
    receipt outputs (dict). Unresolvable bindings raise BindingError.
    """
    if isinstance(value, dict):
        keys = set(value.keys())
        if keys == {"$slot"}:
            name = value["$slot"]
            if name not in run.slot_values:
                raise BindingError(f"slot {name!r} has no bound value")
            return run.slot_values[name]
        if keys == {"$ref"}:
            node_id = value["$ref"]
            if node_id not in results:
                raise BindingError(f"reference {node_id!r} has no resolved output yet")
            return results[node_id]
        if keys == {"$context"}:
            return _context_value(run.context, value["$context"])
        return {k: resolve_value(v, run=run, results=results) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_value(v, run=run, results=results) for v in value]
    return value


def bind_parameters(
    node: NodeSpec, *, run: Any, results: dict[str, Any]
) -> dict[str, Any]:
    """Concrete parameters for one node execution (markers resolved)."""
    return resolve_value(node.parameters, run=run, results=results)


def slot_schema_problems(spec: WorkflowSpec, slot_values: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    known = {s.name for s in spec.slots}
    for name in slot_values:
        if name not in known:
            problems.append(f"unknown slot {name!r} (declared: {sorted(known)})")
    for slot in spec.slots:
        if slot.name in slot_values:
            problems.extend(
                validate_parameters(slot.schema, slot_values[slot.name], label=f"slot {slot.name}")
            )
        elif slot.required and slot.default is None:
            problems.append(f"required slot {slot.name!r} has no value")
    return problems


def materialize_slot_defaults(spec: WorkflowSpec, slot_values: dict[str, Any]) -> dict[str, Any]:
    """Fill declared defaults for absent slots (explicit values win)."""
    values = dict(slot_values)
    for slot in spec.slots:
        if slot.name not in values and slot.default is not None:
            values[slot.name] = slot.default
    return values
