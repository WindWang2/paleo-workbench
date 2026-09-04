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
import inspect
import json
import logging
import tempfile
from pathlib import Path
from typing import Any, Callable

from paleo_workbench.catalog.models import CatalogError, DataRun, DataStage
from paleo_workbench.prediction.providers import get_provider
from paleo_workbench.project.models import PredictionTask, ProjectDocument

logger = logging.getLogger(__name__)

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

# #1152: envelope keys the SERVICE owns. A provider result dict is spread
# into the persisted payload, so without this filter any provider (or a
# tampered one) could relabel the run's model identity, seed, provenance
# hash or run linkage after the fact. Server-constructed values always win.
PAYLOAD_RESERVED_KEYS = frozenset(
    {
        "schema_version",
        "model",
        "generator_version",
        "input_snapshot_hash",
        "input_version_ids",
        "seed",
        "parameters",
        "run_id",
        "_finished_at",
        "output_version_id",
    }
)


def _snapshot_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _input_info(service, version_id: str) -> dict[str, Any]:
    """Payload info for one declared input version (for the provider)."""
    version = service.get_version(version_id)
    if getattr(version, "trashed", False):
        raise CatalogError(f"Input version {version_id} is trashed (H5-a)")
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


def resolve_prediction_inputs(
    project: ProjectDocument,
    service,
    *,
    resource_ids: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[str]:
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
    selected_ids = (
        {str(resource_id) for resource_id in resource_ids if str(resource_id)}
        if resource_ids is not None
        else None
    )
    for resource in project.resources:
        if selected_ids is not None and str(getattr(resource, "id", "")) not in selected_ids:
            continue
        if getattr(resource, "type", "") not in ("well_log", "seismic"):
            continue
        version_id = _resolve_resource_version_id(service, resource)
        if version_id is not None and version_id not in seen:
            seen.add(version_id)
            input_ids.append(version_id)
    # An explicit resource scope is a single-well request from the prediction
    # page. Do not silently add unrelated factor-map versions to that run.
    if selected_ids is None:
        task_ids = [t.id for t in project.factor_map_tasks]
        for version_id in _versions_for_domain_tasks(
            task_ids, catalog=_ServiceRunView(service)
        ):
            if version_id not in seen:
                seen.add(version_id)
                input_ids.append(version_id)
    return input_ids


def resolve_prediction_postprocess_inputs(
    project: ProjectDocument,
    service,
) -> list[str]:
    """Return catalogued per-well stratification inputs for prediction output.

    The model contract remains intentionally limited to its declared well-log
    input.  These optional versions provide reproducible formation boundaries
    for the persisted, local post-processing step after a remote prediction
    completes.
    """
    input_ids: list[str] = []
    seen: set[str] = set()
    for resource in project.resources:
        if getattr(resource, "type", "") != "well_stratification":
            continue
        version_id = _resolve_resource_version_id(service, resource)
        if version_id is not None and version_id not in seen:
            seen.add(version_id)
            input_ids.append(version_id)
    return input_ids


def resolve_inputs_for_model(
    project: ProjectDocument,
    service,
    model_version_id: str,
    *,
    strict: bool = True,
    resource_ids: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[str]:
    """Schema-driven input resolution for a registered model version (Stage 13)."""
    from paleo_workbench.prediction.input_contract import resolve_model_inputs

    model_version = service.get_model_version_by_id(model_version_id)
    return resolve_model_inputs(
        project,
        service,
        model_version,
        strict=strict,
        resource_ids=resource_ids,
    )


def _resolve_resource_version_id(service, resource_or_id) -> str | None:
    """Resolve a project resource to its current catalog version.

    The ordinary identity path is the catalog asset id / one-to-one legacy
    bridge.  A reimport may reuse an existing immutable catalog asset whose
    legacy bridge belongs to the first import, so newer ResourceItems also
    carry an explicit ``catalog_asset_id``.  Older project documents predate
    that field; for those, the catalog's canonical source URI provides a
    deterministic compatibility lookup.
    """
    resource_id = str(getattr(resource_or_id, "id", resource_or_id) or "")
    summary = getattr(resource_or_id, "parsed_summary", None) or {}
    catalog_asset_id = str(summary.get("catalog_asset_id") or "")

    for asset in service.document.assets:
        if (
            asset.id == resource_id
            or asset.legacy_resource_id == resource_id
            or (catalog_asset_id and asset.id == catalog_asset_id)
        ):
            if asset.current_version_id is not None:
                return asset.current_version_id

    raw_path = str(getattr(resource_or_id, "path", "") or "")
    if not raw_path:
        return None
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        return None
    source_uri = candidate.resolve(strict=False).as_posix()
    resource_type = str(getattr(resource_or_id, "type", "") or "")
    matches: list[str] = []
    for asset in service.document.assets:
        if resource_type and str(getattr(asset, "type", "") or "") != resource_type:
            continue
        version_id = asset.current_version_id
        if version_id is None:
            continue
        try:
            version = service.get_version(version_id)
        except Exception:
            continue
        if getattr(version, "trashed", False):
            continue
        if str(getattr(version, "source_uri", "") or "") == source_uri:
            matches.append(version.id)
    if len(matches) == 1:
        return matches[0]
    return None


# Shared adapter-shaped run view (single implementation; audit #848).
from paleo_workbench.catalog.service_view import (  # noqa: E402
    RunProxy as _RunProxy,
    ServiceRunView as _ServiceRunView,
)


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
    # Canonicalize input order + duplicates so the reproducibility snapshot is
    # permutation-invariant (H5-e): the same input SET yields the same hash.
    input_ids = sorted({str(v) for v in (input_version_ids or [])})
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


def _provider_accepts_cancel(provider) -> bool:
    """True when the provider's ``run`` exposes the cancel seam (#1167)."""
    try:
        signature = inspect.signature(provider.run)
    except (TypeError, ValueError):  # pragma: no cover - exotic callables
        return False
    if any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in signature.parameters.values()
    ):
        return True
    return "cancel" in signature.parameters


def _cancel_run(service, run_id: str, partial: dict[str, Any] | None) -> None:
    """Record a cooperative cancellation as the run's terminal state (#1167).

    Cancelled is not failed: the run may resume (tiled providers keep
    per-tile markers), and it produced no consumable output version.
    """
    extra = {"_finished_at": _now_iso()}
    if isinstance(partial, dict):
        if partial.get("tiles"):
            extra["tiles_done"] = partial["tiles"]
        if partial.get("elapsed_s") is not None:
            extra["elapsed_s"] = partial["elapsed_s"]
    service.update_run_status(run_id, "cancelled", extra_parameters=extra)


def execute_run(
    service,
    run_id: str,
    *,
    cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Execute a running inference run and persist its outcome.

    Returns ``{"run", "result", "model", "model_version"}`` (plus
    ``"cancelled": True`` for a cooperatively cancelled run). Any error —
    provider, schema, lookup or persistence — is recorded on the run
    (status ``failed`` + ``error``) so a run never strands in "running".
    A failed run never fabricates output.

    *cancel* is checked cooperatively: it is offered to providers whose
    ``run`` accepts a ``cancel`` keyword, and a provider result flagged
    ``cancelled`` ends the run in the terminal ``cancelled`` state (not
    ``failed``, and no output version is registered).
    """
    run = service.get_run(run_id)
    if (run.status or "").lower() != "running":
        # Late/duplicate execution must not touch a terminal run — and must
        # not be swallowed into a "failed" relabel of a completed run (round-3).
        raise CatalogError(
            f"execute_run requires a running run; {run_id} is {run.status!r}"
        )
    try:
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
        # #1176: server-constructed registered-model identity. Providers
        # that bind their executable artifact to the catalog's ModelVersion
        # (e.g. tiled ONNX checksum verification) consume this; the leading
        # underscore keeps it out of the persisted payload parameters.
        parameters["_registered_model"] = {
            "model_id": model.model_id,
            "model_version": model_version.model_version,
            "model_version_id": model_version.id,
            "artifact_uri": str(getattr(model_version, "artifact_uri", "") or ""),
            "checksum": str(getattr(model_version, "checksum", "") or ""),
        }
        try:
            if cancel is not None and _provider_accepts_cancel(provider):
                result = provider.run(inputs, parameters, cancel=cancel)
            else:
                result = provider.run(inputs, parameters)
        except Exception as exc:  # noqa: BLE001 — surface into run status honestly
            from paleo_workbench.runtime.task_scheduler import TaskCancelled

            if isinstance(exc, TaskCancelled):
                _cancel_run(service, run_id, None)
                return {
                    "run": service.get_run(run_id),
                    "result": None,
                    "model": model,
                    "model_version": model_version,
                    "cancelled": True,
                }
            _fail_run(service, run_id, exc)
            return {
                "run": service.get_run(run_id),
                "result": None,
                "model": model,
                "model_version": model_version,
            }

        # #1167: a cooperatively cancelled provider result is a cancellation,
        # not a completion — terminal state "cancelled", no output version.
        if isinstance(result, dict) and result.get("cancelled"):
            _cancel_run(service, run_id, result)
            return {
                "run": service.get_run(run_id),
                "result": None,
                "model": model,
                "model_version": model_version,
                "cancelled": True,
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

        # Align DataRun.generator with provider/result generator_version so Stage-9
        # expected_identity (from PredictionTask.generator_version) does not flag
        # GENERATOR_CHANGED immediately after a successful run.
        provider_generator = str(
            result.get("generator_version") or model.provider or run.generator or ""
        )
        if provider_generator:
            run.generator = provider_generator

        # #1152: envelope reserved keys are SERVICE-owned. Filter them out
        # of the provider result before merging so a provider dict can never
        # relabel model identity, seed, provenance hash or run linkage.
        provider_payload = {
            k: v for k, v in result.items() if k not in PAYLOAD_RESERVED_KEYS
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
            "generator_version": provider_generator or result.get("generator_version"),
            "input_snapshot_hash": (run.parameters or {}).get("_input_snapshot_hash"),
            "input_version_ids": list(run.input_version_ids),
            "seed": seed,
            "parameters": {
                k: v for k, v in parameters.items() if not k.startswith("_")
            },
            "run_id": run_id,
            **provider_payload,
        }
        # Prefer the aligned identity (result may re-set generator_version via **result).
        if provider_generator:
            payload["generator_version"] = provider_generator
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
    except Exception as exc:  # noqa: BLE001 — prelude/persist failures must not strand a running run
        # If the failure happened AFTER an output version was registered, the
        # run DID produce; mark it complete (best-effort) so the catalog never
        # shows a failed run with a current, consumable output (Agent L P2).
        try:
            after = service.get_run(run_id)
            if after.output_version_ids:
                service.update_run_status(
                    run_id,
                    "complete",
                    extra_parameters={
                        "error": f"{exc.__class__.__name__}: {exc}",
                        "_finished_at": _now_iso(),
                    },
                )
                return {
                    "run": service.get_run(run_id),
                    "result": None,
                    "model": None,
                    "model_version": None,
                }
        except Exception:
            pass
        _fail_run(service, run_id, exc)
        return {
            "run": service.get_run(run_id),
            "result": None,
            "model": None,
            "model_version": None,
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
    # Volume outputs (tiled ONNX, #1085): register the class/prob zarr
    # stores as DERIVED versions with lineage through the same run.
    for spec in payload.get("volume_outputs") or []:
        try:
            store = Path(str(spec.get("path", "")))
            if not store.is_dir():
                continue
            service.register_derived_store(
                name=str(spec.get("name") or "inference volume"),
                store_path=store,
                run_id=run_id,
                type="prediction-volume",
                format="zarr-v3",
                version_metadata={
                    "kind": spec.get("kind", "volume"),
                    "dtype": spec.get("dtype", ""),
                    "device_mode": payload.get("device_mode", ""),
                    "model_id": model.model_id,
                },
            )
        except Exception:
            logger.exception(
                "volume output registration failed for run %s", run_id
            )
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
    """Record the domain PredictionTask id on a run (for run-graph lineage).

    Uses the public ``update_run_status`` surface (with the run's existing
    status) instead of reaching into ``service._save()`` (audit #848).
    """
    run = service.get_run(run_id)
    return service.update_run_status(
        run_id,
        (run.status or "running"),
        extra_parameters={"_domain_task_id": domain_task_id},
    )


def materialize_prediction_task(
    project: ProjectDocument,
    payload: dict[str, Any],
    *,
    name_prefix: str,
    workflow: str,
    target_horizon: str = "",
    factor_map_ids: list[str] | None = None,
    well_log_resource_ids: list[str] | None = None,
    seismic_resource_ids: list[str] | None = None,
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
        input_refs={
            "well_log_resource_ids": list(
                dict.fromkeys(str(resource_id) for resource_id in (well_log_resource_ids or []))
            ),
            "seismic_resource_ids": list(
                dict.fromkeys(str(resource_id) for resource_id in (seismic_resource_ids or []))
            ),
        },
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
