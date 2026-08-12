"""Inference job layer (P2): ModelRegistry-backed inference with honest runs.

Pure Python (no Qt). The flow is:

    start_inference(service, model_version_id, input_version_ids, parameters)
        → DataRun(status="running") with model_ref + reproducibility metadata
    execute_run(service, run_id)                      # called in a worker thread
        → provider.run(inputs, parameters)
        → result persisted as a DERIVED DataVersion with run linkage
        → update_run_status(complete, output_version_id, finished_at)
        → on provider error: update_run_status(failed, error) — NO fake output

:func:`materialize_prediction_task` turns a finished run's result back into the
domain :class:`~paleo_workbench.project.models.PredictionTask` the prediction
pages display (the pages keep their existing task list; the catalog run +
version provide the provenance).
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from paleo_workbench.catalog.models import CatalogError, DataRun, DataStage
from paleo_workbench.prediction.providers import get_provider
from paleo_workbench.project.models import PredictionTask, ProjectDocument

INFERENCE_GENERATOR = "inference-service-v1"

_RESERVED_KEYS = (
    "_finished_at",
    "_domain_task_id",
    "_input_snapshot_hash",
    "model_id",
    "model_version",
    "model_version_id",
    "provider",
    "demo_only",
    "error",
)


def _snapshot_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _input_info(service, version_id: str) -> dict[str, Any]:
    """Payload info for one declared input version (for the provider)."""
    version = service.get_version(version_id)
    asset = None
    for candidate in service.document.assets:
        if candidate.id == version.asset_id:
            asset = candidate
            break
    return {
        "path": service.resolve_path(version).as_posix(),
        "name": asset.name if asset is not None else version.asset_id,
        "asset_type": asset.type if asset is not None else "",
        "format": version.format,
        "version_id": version.id,
    }


def resolve_prediction_inputs(project: ProjectDocument, service) -> list[str]:
    """Version ids of a project's well-log/seismic resources + factor tasks.

    Mirrors the catalog legacy bridge: an asset whose id (or
    ``legacy_resource_id``) matches the resource id resolves to its current
    version. Factor-map tasks resolve through their registered runs (output
    versions, or propagated inputs for in-memory-only results). Degrades to an
    empty list when nothing is registered yet.

    Prefer :func:`resolve_inputs_for_model` when a ModelVersion is known so
    DataRun inputs match the model's declared schema (Stage 13).
    """
    from paleo_workbench.catalog.lifecycle import _versions_for_domain_tasks

    input_ids: list[str] = []
    seen: set[str] = set()
    for resource in project.resources:
        if getattr(resource, "type", "") not in ("well_log", "seismic"):
            continue
        version_id = _resolve_resource_version_id(service, resource.id)
        if version_id is not None and version_id not in seen:
            seen.add(version_id)
            input_ids.append(version_id)
    task_ids = [t.id for t in project.factor_map_tasks]
    for version_id in _versions_for_domain_tasks(task_ids, catalog=_ServiceRunView(service)):
        if version_id not in seen:
            seen.add(version_id)
            input_ids.append(version_id)
    return input_ids


def resolve_inputs_for_model(
    project: ProjectDocument,
    service,
    model_version_id: str,
    *,
    strict: bool = True,
) -> list[str]:
    """Schema-driven input resolution for a registered model version (Stage 13)."""
    from paleo_workbench.prediction.input_contract import resolve_model_inputs

    model_version = service.get_model_version_by_id(model_version_id)
    return resolve_model_inputs(project, service, model_version, strict=strict)


def _resolve_resource_version_id(service, resource_id: str) -> str | None:
    """Adapter-equivalent legacy bridge over the service document."""
    for asset in service.document.assets:
        if asset.id == resource_id or asset.legacy_resource_id == resource_id:
            if asset.current_version_id is not None:
                return asset.current_version_id
    return None


class _ServiceRunView:
    """Adapter-shaped view over the service for lifecycle run-graph helpers.

    :class:`DataRun` stores ``domain_task_id`` in ``parameters["_domain_task_id"]``
    (mirroring :class:`~paleo_workbench.catalog.adapter.CoreCatalogAdapter`), so
    the proxy exposes it as an attribute like the ``DataRunRef`` the lifecycle
    helpers expect.
    """

    def __init__(self, service):
        self._service = service

    def list_runs(self):
        return [_RunProxy(run) for run in self._service.document.runs]


class _RunProxy:
    __slots__ = ("_run",)

    def __init__(self, run):
        self._run = run

    @property
    def domain_task_id(self):
        return (self._run.parameters or {}).get("_domain_task_id")

    @property
    def output_version_ids(self):
        return self._run.output_version_ids

    @property
    def input_version_ids(self):
        return self._run.input_version_ids


def start_inference(
    service,
    *,
    model_version_id: str,
    input_version_ids: list[str] | None = None,
    parameters: dict[str, Any] | None = None,
    operation: str = "prediction",
    generator: str = INFERENCE_GENERATOR,
) -> DataRun:
    """Open a running inference DataRun bound to a registered model version.

    Raises :class:`CatalogError` when the model version is unknown. The run
    records ``model_ref`` + reproducibility metadata (seed, input snapshot
    hash, model identity) so the run is fully reproducible before any compute.
    """
    model_version = service.get_model_version_by_id(model_version_id)
    model = service.get_model(model_version.model_id)
    params = dict(parameters or {})
    seed = int(params.get("seed", 0) or 0)
    input_ids = list(input_version_ids or [])
    # Stage-13: computation identity includes model + preprocessing, not only inputs.
    snapshot = {
        "model_version_id": model_version_id,
        "model_id": model.model_id,
        "model_version": model_version.model_version,
        "input_version_ids": input_ids,
        "preprocessing_version": getattr(model_version, "preprocessing_version", "") or "",
        "artifact_checksum": getattr(model_version, "checksum", None) or "",
        "parameters": {k: v for k, v in params.items() if not k.startswith("_")},
    }
    run = service.register_run(
        operation=operation,
        input_version_ids=input_ids,
        parameters={
            "model_id": model.model_id,
            "model_version": model_version.model_version,
            "model_version_id": model_version.id,
            "provider": model.provider,
            "demo_only": bool(model_version.demo_only),
            "preprocessing_version": getattr(model_version, "preprocessing_version", "") or "",
            "seed": seed,
            "_input_snapshot_hash": _snapshot_hash(snapshot),
            **params,
        },
        generator=generator or model.provider,
        status="running",
        model_ref={
            "model_id": model.model_id,
            "model_version": model_version.model_version,
            "model_version_id": model_version.id,
        },
    )
    return run


def execute_run(service, run_id: str) -> dict[str, Any]:
    """Execute a running inference run and persist its outcome.

    Returns ``{"run", "result", "model", "model_version"}``. Provider errors
    are caught and recorded on the run (status ``failed`` + ``error``) with NO
    output version — a failed run never fabricates output. Catalog-level
    errors (unknown run/version, unpersistable result) propagate.
    """
    run = service.get_run(run_id)
    model_version_id = (run.parameters or {}).get("model_version_id")
    if not model_version_id:
        raise CatalogError(f"Run {run_id} has no model_version_id")
    model_version = service.get_model_version_by_id(model_version_id)
    model = service.get_model(model_version.model_id)
    provider = get_provider(model.provider)
    seed = int((run.parameters or {}).get("seed", 0) or 0)
    inputs = {
        version_id: _input_info(service, version_id)
        for version_id in run.input_version_ids
    }
    parameters = {
        k: v
        for k, v in (run.parameters or {}).items()
        if not k.startswith("_") and k not in _RESERVED_KEYS
    }
    parameters["seed"] = seed
    try:
        result = provider.run(inputs, parameters)
    except Exception as exc:  # noqa: BLE001 — surface into run status honestly
        _fail_run(service, run_id, exc)
        return {
            "run": service.get_run(run_id),
            "result": None,
            "model": model,
            "model_version": model_version,
        }

    # Stage-13: validate spatial output when the model declares a spatial schema.
    from paleo_workbench.prediction.spatial_result import (
        SpatialResultError,
        validate_spatial_result,
    )

    expected = (model_version.output_schema or {}).get("spatial_output_type")
    if expected and str(expected) not in ("", "NONE"):
        spatial_errors = validate_spatial_result(result, expected_type=str(expected))
        if spatial_errors:
            _fail_run(service, run_id, SpatialResultError("; ".join(spatial_errors)))
            return {
                "run": service.get_run(run_id),
                "result": None,
                "model": model,
                "model_version": model_version,
            }

    payload = {
        "schema_version": "1.0",
        "model": {
            "model_id": model.model_id,
            "model_version": model_version.model_version,
            "model_name": model.model_name,
            "demo_only": bool(model_version.demo_only),
            "preprocessing_version": getattr(model_version, "preprocessing_version", "")
            or "",
            "checksum": getattr(model_version, "checksum", None) or "",
            "model_version_id": model_version.id,
        },
        "generator_version": result.get("generator_version") or model.provider,
        "input_snapshot_hash": (run.parameters or {}).get("_input_snapshot_hash"),
        "input_version_ids": list(run.input_version_ids),
        "seed": seed,
        "parameters": parameters,
        "run_id": run_id,
        **result,
    }
    output_version = _persist_result(service, run_id, model, payload)
    finished = _now_iso()
    service.update_run_status(
        run_id,
        "complete",
        extra_parameters={
            "_finished_at": finished,
            "output_version_id": output_version.id,
        },
    )
    return {
        "run": service.get_run(run_id),
        "result": payload,
        "output_version": output_version,
        "model": model,
        "model_version": model_version,
    }


def _persist_result(service, run_id: str, model, payload: dict[str, Any]) -> Any:
    """Write *payload* to a temp file and register it as a DERIVED version."""
    fd, tmp_path = tempfile.mkstemp(prefix="inference_result_", suffix=".json")
    try:
        with open(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        # Single locked atomic operation: asset creation + version registration
        # + rollback on failure (worker-thread safe; never mutate
        # service.document.assets directly — review finding #4).
        output = service.register_result_asset(
            name=f"{model.model_name} 结果",
            type="prediction_result",
            format="json",
            asset_metadata={"kind": "prediction_result"},
            source_path=tmp_path,
            stage=DataStage.DERIVED,
            run_id=run_id,
            version_metadata={
                "source": payload.get("source", "inference"),
                "demo": bool(payload.get("demo", False)),
                "kind": "prediction_result",
                "format": "json",
            },
        )
    finally:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass
    return output


def _fail_run(service, run_id: str, exc: Exception) -> None:
    service.update_run_status(
        run_id,
        "failed",
        extra_parameters={
            "error": f"{exc.__class__.__name__}: {exc}",
            "error_type": exc.__class__.__name__,
            "_finished_at": _now_iso(),
        },
    )


def _now_iso() -> str:
    from paleo_workbench.catalog.types import _now_iso as _iso

    return _iso()


def link_run_to_domain_task(service, run_id: str, domain_task_id: str) -> DataRun:
    """Record the domain PredictionTask id on a run (for run-graph lineage)."""
    run = service.get_run(run_id)
    params = dict(run.parameters or {})
    params["_domain_task_id"] = domain_task_id
    run.parameters = params
    service._save()
    return run


def materialize_prediction_task(
    project: ProjectDocument,
    payload: dict[str, Any],
    *,
    name_prefix: str,
    workflow: str,
    target_horizon: str = "",
    factor_map_ids: list[str] | None = None,
    run_id: str = "",
    output_version_id: str = "",
) -> PredictionTask:
    """Build the domain PredictionTask a finished inference displays.

    The task carries the run's honest flags (``is_mock`` / ``demo`` /
    ``final_scientific_prediction`` / ``model_type``) plus model identity in
    ``model_metadata``. Does NOT append to the project — the caller owns the
    project object.
    """
    try:
        from paleo_workbench.prediction.spatial_result import bounded_result_summary

        result_summary = bounded_result_summary(payload)
    except Exception:
        result_summary = dict(payload.get("result_summary") or {})
    model = payload.get("model") or {}
    adapter_kind = payload.get("adapter_kind") or (
        "mock" if result_summary.get("is_mock") else "local"
    )
    horizon = target_horizon or (
        project.stratigraphy.target_horizon if project is not None else ""
    )
    resolved_run = run_id or str(payload.get("run_id") or "")
    resolved_out = output_version_id or str(
        (payload.get("parameters") or {}).get("output_version_id")
        or payload.get("output_version_id")
        or ""
    )
    task = PredictionTask(
        name=f"{name_prefix} · {horizon or 'demo'}",
        adapter_kind=adapter_kind,
        input_factor_map_ids=list(factor_map_ids or []),
        model_metadata={
            "workflow": workflow,
            "target_horizon": horizon,
            "adapter": adapter_kind,
            "model_id": model.get("model_id", ""),
            "model_version": model.get("model_version", ""),
            "model_name": model.get("model_name", ""),
            "model_version_id": model.get("model_version_id", ""),
            "preprocessing_version": model.get("preprocessing_version", ""),
            "demo_only": bool(model.get("demo_only", False)),
            "demo": bool(result_summary.get("demo", False)),
            "run_id": resolved_run,
            "output_version_id": resolved_out,
            "prediction_version_id": resolved_out,
        },
        result_summary=result_summary,
        probability_summary=dict(payload.get("probability_summary") or {}),
        evidence_contribution=list(payload.get("evidence_contribution") or []),
        review_areas=list(payload.get("review_areas") or []),
        status="complete",
        adapter_schema_version=str(payload.get("schema_version", "1.0")),
        input_snapshot_hash=payload.get("input_snapshot_hash") or "",
        generator_version=payload.get("generator_version"),
        seed=payload.get("seed"),
    )
    return task
