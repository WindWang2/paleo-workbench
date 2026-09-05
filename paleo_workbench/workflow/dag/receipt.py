"""Scientific execution receipt (H6): the standard, serialisable record of
what one workflow node (or harness action) actually did.

A receipt *references* canonical facts — catalog run ids, data version ids,
action/provider versions — and never copies lineage or re-states data
content. Consumers: Task Center / Agent panel display, project history,
reproduction instructions, and the workflow cache (identity + outputs).
"""
from __future__ import annotations

import platform
import sys
import time
from dataclasses import dataclass, field
from typing import Any

RECEIPT_SCHEMA_VERSION = "1.0"


@dataclass(slots=True)
class ExecutionReceipt:
    """Standard receipt of one node/action execution."""

    schema_version: str = RECEIPT_SCHEMA_VERSION
    node_id: str | None = None
    workflow_run_id: str | None = None
    action_id: str = ""
    action_version: str = ""
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)   # bound, concrete
    input_version_ids: tuple[str, ...] = ()
    provider_id: str | None = None
    provider_version: str | None = None
    resource_category: str | None = None
    estimated_resources: dict[str, Any] = field(default_factory=dict)
    status: str = "success"  # canonical ActionResult status
    started_at: float | None = None
    finished_at: float | None = None
    duration_ms: float = 0.0
    output_version_ids: tuple[str, ...] = ()
    outputs_summary: dict[str, Any] = field(default_factory=dict)
    catalog_run_id: str | None = None
    verification: dict[str, Any] = field(default_factory=dict)
    qc_metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    degraded_reason: str | None = None
    error: str | None = None
    cache_identity: str | None = None
    from_cache: bool = False
    attempt: int = 1
    environment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "node_id": self.node_id,
            "workflow_run_id": self.workflow_run_id,
            "action_id": self.action_id,
            "action_version": self.action_version,
            "description": self.description,
            "parameters": self.parameters,
            "input_version_ids": list(self.input_version_ids),
            "provider_id": self.provider_id,
            "provider_version": self.provider_version,
            "resource_category": self.resource_category,
            "estimated_resources": self.estimated_resources,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 3),
            "output_version_ids": list(self.output_version_ids),
            "outputs_summary": self.outputs_summary,
            "catalog_run_id": self.catalog_run_id,
            "verification": self.verification,
            "qc_metrics": self.qc_metrics,
            "warnings": list(self.warnings),
            "degraded_reason": self.degraded_reason,
            "error": self.error,
            "cache_identity": self.cache_identity,
            "from_cache": self.from_cache,
            "attempt": self.attempt,
            "environment": dict(self.environment),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionReceipt":
        return cls(
            schema_version=str(data.get("schema_version", RECEIPT_SCHEMA_VERSION)),
            node_id=data.get("node_id"),
            workflow_run_id=data.get("workflow_run_id"),
            action_id=str(data.get("action_id", "")),
            action_version=str(data.get("action_version", "")),
            description=str(data.get("description", "")),
            parameters=dict(data.get("parameters") or {}),
            input_version_ids=tuple(data.get("input_version_ids") or ()),
            provider_id=data.get("provider_id"),
            provider_version=data.get("provider_version"),
            resource_category=data.get("resource_category"),
            estimated_resources=dict(data.get("estimated_resources") or {}),
            status=str(data.get("status", "success")),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            duration_ms=float(data.get("duration_ms", 0.0)),
            output_version_ids=tuple(data.get("output_version_ids") or ()),
            outputs_summary=dict(data.get("outputs_summary") or {}),
            catalog_run_id=data.get("catalog_run_id"),
            verification=dict(data.get("verification") or {}),
            qc_metrics=dict(data.get("qc_metrics") or {}),
            warnings=list(data.get("warnings") or []),
            degraded_reason=data.get("degraded_reason"),
            error=data.get("error"),
            cache_identity=data.get("cache_identity"),
            from_cache=bool(data.get("from_cache", False)),
            attempt=int(data.get("attempt", 1)),
            environment=dict(data.get("environment") or {}),
        )


def environment_identity() -> dict[str, Any]:
    """Reasonable-scope reproduction environment (H12): not a promise of
    cross-platform bit-identity — the facts a re-runner should match."""
    return {
        "python": sys.version.split(" ", 1)[0],
        "platform": platform.platform(),
        "workbench": _workbench_version(),
    }


def _workbench_version() -> str:
    try:
        from importlib.metadata import version

        return version("paleo-workbench")
    except Exception:
        try:
            from paleo_workbench import __version__

            return str(__version__)
        except Exception:
            return "unknown"


def build_receipt(
    result: Any,
    *,
    node_id: str | None,
    workflow_run_id: str | None,
    action_id: str,
    action_version: str,
    description: str,
    parameters: dict[str, Any],
    input_version_ids: tuple[str, ...],
    estimated_resources: dict[str, Any] | None = None,
    resource_category: str | None = None,
    cache_identity: str | None = None,
    from_cache: bool = False,
    attempt: int = 1,
    started_at: float | None = None,
) -> ExecutionReceipt:
    """Build a receipt from a :class:`harness.executor.ActionResult`."""
    provenance = result.metrics.get("provenance") or {}
    output_version_ids = _collect_output_version_ids(result)
    status = result.status
    degraded_reason = None
    if status == "degraded":
        degraded_reason = "; ".join(result.warnings) or "verification warnings"
    return ExecutionReceipt(
        node_id=node_id,
        workflow_run_id=workflow_run_id,
        action_id=action_id,
        action_version=action_version,
        description=description,
        parameters=parameters,
        input_version_ids=tuple(input_version_ids),
        provider_id=provenance.get("provider_id"),
        provider_version=provenance.get("provider_version"),
        resource_category=resource_category,
        estimated_resources=dict(estimated_resources or {}),
        status=status,
        started_at=started_at,
        finished_at=time.time(),
        duration_ms=result.elapsed_ms,
        output_version_ids=output_version_ids,
        outputs_summary=_summarize_outputs(result.outputs),
        catalog_run_id=provenance.get("run_id"),
        verification=dict(result.verification or {}),
        qc_metrics={
            k: v for k, v in result.metrics.items() if k != "provenance"
        },
        warnings=list(result.warnings),
        degraded_reason=degraded_reason,
        error=result.error,
        cache_identity=cache_identity,
        from_cache=from_cache,
        attempt=attempt,
        environment=environment_identity(),
    )


def _collect_output_version_ids(result: Any) -> tuple[str, ...]:
    """Pull canonical data version ids out of an action result.

    Provider artifacts carry ``version`` (a DataVersionRef or dict); plain
    handler outputs may declare a ``version_ids`` list. Nothing else counts:
    receipts reference the catalog, they do not invent identities.
    """
    ids: list[str] = []
    outputs = getattr(result, "outputs", {}) or {}
    artifacts = outputs.get("artifacts")
    if isinstance(artifacts, list):
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            version = artifact.get("version")
            if isinstance(version, dict) and version.get("version_id"):
                ids.append(str(version["version_id"]))
            elif hasattr(version, "version_id") and version.version_id:
                ids.append(str(version.version_id))
    declared = outputs.get("version_ids")
    if isinstance(declared, list):
        ids.extend(str(v) for v in declared if v)
    seen: set[str] = set()
    ordered = []
    for v in ids:
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    return tuple(ordered)


def _summarize_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    """Small, scalar summary for display — never the payload itself."""
    summary: dict[str, Any] = {}
    for key, value in outputs.items():
        if key == "artifacts":
            summary["artifact_count"] = (
                len(value) if isinstance(value, list) else None
            )
            continue
        if key in ("values", "map_document", "document", "composition"):
            summary[key] = "<in-process handle>"
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            summary[key] = value
        elif isinstance(value, list):
            summary[key] = f"<{len(value)} items>"
        elif isinstance(value, dict):
            summary[key] = f"<{len(value)} keys>"
        else:
            summary[key] = type(value).__name__
    return summary
