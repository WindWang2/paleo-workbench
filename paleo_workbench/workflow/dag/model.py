"""Workflow DAG data model (Harness 2.0, H2/H3).

A :class:`WorkflowSpec` is a static, validated, serialisable DAG of
professional actions; a :class:`WorkflowRun` is one persisted execution of
it with per-node checkpoints (:class:`NodeRun`). Design rules:

- **Specs are data, never code**: parameters are JSON literals or typed
  bindings (``{"$slot": ...}`` / ``{"$ref": ...}`` / ``{"$context": ...}``);
  conditions are declarative trees — there is no eval anywhere.
- **Runs checkpoint every node**: spec version, bound parameters, input
  version ids, the cache identity, timings and the scientific receipt —
  enough to resume after a crash without re-executing complete nodes and
  without mistaking an incomplete one for complete.
- **Persistence references the catalog**: node outputs are recorded as
  canonical version ids; lineage stays in the catalog, never copied here.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

WORKFLOW_SCHEMA_VERSION = "1.0"


class NodeState(str, Enum):
    PENDING = "pending"          # waiting on dependencies
    RUNNING = "running"
    SUCCEEDED = "succeeded"      # includes degraded executions (see receipt)
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"          # condition false, or an upstream failure
    UNAVAILABLE = "unavailable"  # action's production capability missing


#: Node states that will not re-execute on resume.
TERMINAL_NODE_STATES = frozenset(
    {NodeState.SUCCEEDED, NodeState.FAILED, NodeState.CANCELLED, NodeState.SKIPPED, NodeState.UNAVAILABLE}
)


class RunState(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"      # all nodes terminal, no failure
    FAILED = "failed"            # ≥1 node failed/unavailable
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"  # process/Project ended mid-run; resumable


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Fixed-backoff retry for *retryable* outcomes: plain execution
    failures and governor resource-shed refusals. Guard rejections
    (schema/permission/context), cancellations and unavailability never
    retry — retrying them would just re-burn attempts on a permanent
    answer."""

    max_attempts: int = 1
    backoff_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"max_attempts": self.max_attempts, "backoff_seconds": self.backoff_seconds}


@dataclass(frozen=True, slots=True)
class NodeCondition:
    """Declarative, safe skip-condition tree (no eval, ever).

    kinds:
      ``node_succeeded``      — {node}
      ``node_output_equals``  — {node, key, value}
      ``node_state``          — {node, state}   (NodeState value)
      ``all_of`` / ``any_of`` — {conditions: [...]}
      ``not``                 — {condition: {...}}
    """

    kind: str
    node: str | None = None
    key: str | None = None
    value: Any = None
    state: str | None = None
    conditions: tuple["NodeCondition", ...] = ()
    condition: "NodeCondition | None" = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind}
        for name in ("node", "key", "state"):
            v = getattr(self, name)
            if v is not None:
                d[name] = v
        if self.value is not None:
            d["value"] = self.value
        if self.conditions:
            d["conditions"] = [c.to_dict() for c in self.conditions]
        if self.condition is not None:
            d["condition"] = self.condition.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeCondition":
        kind = str(data.get("kind", ""))
        conditions = tuple(
            cls.from_dict(c) for c in data.get("conditions", []) or []
        )
        condition = cls.from_dict(data["condition"]) if isinstance(data.get("condition"), dict) else None
        return cls(
            kind=kind,
            node=data.get("node"),
            key=data.get("key"),
            value=data.get("value"),
            state=data.get("state"),
            conditions=conditions,
            condition=condition,
        )


_CONDITION_KINDS = {
    "node_succeeded",
    "node_output_equals",
    "node_state",
    "all_of",
    "any_of",
    "not",
}


def validate_condition_tree(condition: NodeCondition) -> list[str]:
    if condition.kind not in _CONDITION_KINDS:
        return [f"condition kind {condition.kind!r} is not one of {sorted(_CONDITION_KINDS)}"]
    problems: list[str] = []
    if condition.kind in ("node_succeeded", "node_output_equals", "node_state") and not condition.node:
        problems.append(f"condition {condition.kind!r} requires a node reference")
    if condition.kind == "node_output_equals" and not condition.key:
        problems.append("node_output_equals requires an output key")
    if condition.kind == "node_state" and not condition.state:
        problems.append("node_state requires a state value")
    if condition.kind in ("all_of", "any_of"):
        if not condition.conditions:
            problems.append(f"{condition.kind} requires conditions")
        for sub in condition.conditions:
            problems.extend(validate_condition_tree(sub))
    if condition.kind == "not":
        if condition.condition is None:
            problems.append("'not' requires a condition")
        else:
            problems.extend(validate_condition_tree(condition.condition))
    return problems


@dataclass(frozen=True, slots=True)
class NodeSpec:
    """One node of the static workflow graph."""

    node_id: str
    action_id: str
    parameters: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[str, ...] = ()
    condition: NodeCondition | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "action_id": self.action_id,
            "parameters": self.parameters,
            "depends_on": list(self.depends_on),
            "condition": self.condition.to_dict() if self.condition else None,
            "retry": self.retry.to_dict(),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeSpec":
        retry_raw = data.get("retry") or {}
        return cls(
            node_id=str(data["node_id"]),
            action_id=str(data["action_id"]),
            parameters=dict(data.get("parameters") or {}),
            depends_on=tuple(data.get("depends_on") or ()),
            condition=NodeCondition.from_dict(data["condition"])
            if isinstance(data.get("condition"), dict)
            else None,
            retry=RetryPolicy(
                max_attempts=int(retry_raw.get("max_attempts", 1)),
                backoff_seconds=float(retry_raw.get("backoff_seconds", 0.0)),
            ),
            description=str(data.get("description") or ""),
        )


@dataclass(frozen=True, slots=True)
class SlotSpec:
    """A typed workflow input slot (rerun-with-new-inputs contract)."""

    name: str
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "string"})
    required: bool = True
    default: Any = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "schema": self.schema,
            "required": self.required,
            "default": self.default,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlotSpec":
        return cls(
            name=str(data["name"]),
            schema=dict(data.get("schema") or {"type": "string"}),
            required=bool(data.get("required", True)),
            default=data.get("default"),
            description=str(data.get("description") or ""),
        )


@dataclass(frozen=True, slots=True)
class WorkflowSpec:
    """Static DAG of professional actions (the recipe body)."""

    workflow_id: str
    name: str
    nodes: tuple[NodeSpec, ...]
    slots: tuple[SlotSpec, ...] = ()
    schema_version: str = WORKFLOW_SCHEMA_VERSION
    max_concurrency: int = 1  # structural bound; resources stay governor-owned
    description: str = ""

    def node(self, node_id: str) -> NodeSpec:
        for n in self.nodes:
            if n.node_id == node_id:
                return n
        raise KeyError(f"workflow {self.workflow_id!r} has no node {node_id!r}")

    @property
    def spec_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "max_concurrency": self.max_concurrency,
            "slots": [s.to_dict() for s in self.slots],
            "nodes": [n.to_dict() for n in self.nodes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowSpec":
        return cls(
            workflow_id=str(data["workflow_id"]),
            name=str(data["name"]),
            nodes=tuple(NodeSpec.from_dict(n) for n in data.get("nodes", [])),
            slots=tuple(SlotSpec.from_dict(s) for s in data.get("slots", [])),
            schema_version=str(data.get("schema_version", WORKFLOW_SCHEMA_VERSION)),
            max_concurrency=int(data.get("max_concurrency", 1)),
            description=str(data.get("description") or ""),
        )


@dataclass(slots=True)
class NodeRun:
    """Checkpoint of one node execution (persisted, crash-safe)."""

    node_id: str
    state: NodeState = NodeState.PENDING
    attempt: int = 0
    action_status: str | None = None  # canonical ActionResult status last seen
    from_cache: bool = False
    parameters: dict[str, Any] = field(default_factory=dict)  # bound, concrete
    input_version_ids: tuple[str, ...] = ()
    cache_identity: str | None = None
    output_version_ids: tuple[str, ...] = ()
    outputs: dict[str, Any] = field(default_factory=dict)  # JSON-able projection for $ref after resume
    receipt: dict[str, Any] | None = None  # scientific execution receipt
    skip_reason: str | None = None
    error: str | None = None
    started_at: float | None = None  # epoch seconds
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "state": self.state.value,
            "attempt": self.attempt,
            "action_status": self.action_status,
            "from_cache": self.from_cache,
            "parameters": self.parameters,
            "input_version_ids": list(self.input_version_ids),
            "cache_identity": self.cache_identity,
            "output_version_ids": list(self.output_version_ids),
            "outputs": self.outputs,
            "receipt": self.receipt,
            "skip_reason": self.skip_reason,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NodeRun":
        return cls(
            node_id=str(data["node_id"]),
            state=NodeState(data.get("state", "pending")),
            attempt=int(data.get("attempt", 0)),
            action_status=data.get("action_status"),
            from_cache=bool(data.get("from_cache", False)),
            parameters=dict(data.get("parameters") or {}),
            input_version_ids=tuple(data.get("input_version_ids") or ()),
            cache_identity=data.get("cache_identity"),
            output_version_ids=tuple(data.get("output_version_ids") or ()),
            outputs=dict(data.get("outputs") or {}),
            receipt=data.get("receipt"),
            skip_reason=data.get("skip_reason"),
            error=data.get("error"),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
        )


@dataclass(slots=True)
class WorkflowRun:
    """One persisted execution of a WorkflowSpec."""

    run_id: str
    workflow: WorkflowSpec
    state: RunState = RunState.RUNNING
    slot_values: dict[str, Any] = field(default_factory=dict)
    node_runs: dict[str, NodeRun] = field(default_factory=dict)
    project_name: str | None = None
    project_path: str | None = None
    created_at: float | None = None
    updated_at: float | None = None
    spec_hash: str | None = None
    #: V8 M7 run lineage: the run this one was derived from (rerun / resume
    #: chains). None = an original execution. Provenance walks it instead of
    #: losing the derivation relationship between successive runs.
    parent_run_id: str | None = None

    @classmethod
    def create(cls, workflow: WorkflowSpec, slot_values: dict[str, Any]) -> "WorkflowRun":
        now = _now()
        run = cls(
            run_id=uuid.uuid4().hex[:16],
            workflow=workflow,
            slot_values=dict(slot_values),
            created_at=now,
            updated_at=now,
            spec_hash=workflow.spec_hash,
        )
        run.node_runs = {n.node_id: NodeRun(node_id=n.node_id) for n in workflow.nodes}
        return run

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow": self.workflow.to_dict(),
            "state": self.state.value,
            "slot_values": self.slot_values,
            "node_runs": [nr.to_dict() for nr in self.node_runs.values()],
            "project_name": self.project_name,
            "project_path": self.project_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "spec_hash": self.spec_hash,
            "parent_run_id": self.parent_run_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowRun":
        run = cls(
            run_id=str(data["run_id"]),
            workflow=WorkflowSpec.from_dict(data["workflow"]),
            state=RunState(data.get("state", "running")),
            slot_values=dict(data.get("slot_values") or {}),
            project_name=data.get("project_name"),
            project_path=data.get("project_path"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            spec_hash=data.get("spec_hash"),
            parent_run_id=data.get("parent_run_id"),
        )
        run.node_runs = {
            nr.node_id: nr for nr in (NodeRun.from_dict(d) for d in data.get("node_runs", []))
        }
        for node in run.workflow.nodes:  # tolerate store schema drift
            run.node_runs.setdefault(node.node_id, NodeRun(node_id=node.node_id))
        return run


# ----------------------------------------------------------------- helpers --


def canonical_hash(value: Any) -> str:
    """Stable hash of JSON-able data (cache identity, spec identity)."""
    payload = json.dumps(_normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "to_dict"):
        try:
            return _normalize(value.to_dict())
        except Exception:
            pass
    return str(value)


def _now() -> float:
    import time

    return time.time()
