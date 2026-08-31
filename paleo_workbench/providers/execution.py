"""Guarded provider execution: validate → admit → execute → provenance (P2-B).

This is the only sanctioned way to run a capability provider:

1. **resolve**: provider looked up by id (unknown → ``UnknownProviderError``);
2. **validate**: parameters checked against the descriptor's JSON schema
   (a pragmatic subset — see :func:`validate_parameters`); inputs checked to
   be typed refs the provider declares;
3. **admit**: a ResourceGovernor lease is taken from the descriptor's
   resource profile (pressure shedding and CPU/IO caps apply);
4. **execute**: the provider runs with a :class:`ProviderContext` carrying
   the catalog port, cancellation and progress; provider exceptions are
   wrapped (isolation) and never leak partial provenance;
5. **provenance**: when the context has a catalog and the provider declares
   data outputs, a DataRun wraps the execution (begin/complete/fail) —
   providers themselves register artifacts through the same port inside
   ``execute``, keeping the catalog the single write authority.

The executor never imports vendor SDKs, never opens files by path (inputs
arrive as refs), and never bypasses the catalog.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from paleo_workbench.providers.base import CapabilityProvider, ProviderContext
from paleo_workbench.providers.contracts import ProviderDescriptor
from paleo_workbench.providers.errors import (
    InvalidParametersError,
    ProviderError,
    ProviderExecutionError,
    ProviderRejectedInputError,
)
from paleo_workbench.providers.refs import ProviderResult

logger = logging.getLogger(__name__)

_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def validate_parameters(schema: Mapping[str, Any], parameters: Mapping[str, Any]) -> list[str]:
    """Validate ``parameters`` against the JSON-schema subset the SDK allows.

    Supported: type, required, properties, enum, minimum/maximum,
    minItems/maxItems, items. Intentionally dependency-free (no jsonschema
    import) — descriptors are small and fully under our control.
    """
    problems: list[str] = []

    def check(value: Any, sub: Mapping[str, Any], path: str) -> None:
        expected = sub.get("type")
        if expected is not None:
            allowed = _JSON_TYPES.get(str(expected))
            if allowed is not None and not isinstance(value, allowed):
                problems.append(f"{path}: expected {expected}, got {type(value).__name__}")
                return
            if str(expected) in ("integer", "number") and isinstance(value, bool):
                problems.append(f"{path}: expected {expected}, got boolean")
                return
        if "enum" in sub and value not in sub["enum"]:
            problems.append(f"{path}: {value!r} not in enum {sub['enum']!r}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in sub and value < sub["minimum"]:
                problems.append(f"{path}: {value} < minimum {sub['minimum']}")
            if "maximum" in sub and value > sub["maximum"]:
                problems.append(f"{path}: {value} > maximum {sub['maximum']}")
        if isinstance(value, list):
            if "minItems" in sub and len(value) < sub["minItems"]:
                problems.append(f"{path}: {len(value)} items < minItems {sub['minItems']}")
            if "maxItems" in sub and len(value) > sub["maxItems"]:
                problems.append(f"{path}: {len(value)} items > maxItems {sub['maxItems']}")
            items = sub.get("items")
            if isinstance(items, dict):
                for i, item in enumerate(value):
                    check(item, items, f"{path}[{i}]")
        if isinstance(value, dict) and isinstance(sub.get("properties"), dict):
            for key, sub_sub in sub["properties"].items():
                if key in value:
                    check(value[key], sub_sub, f"{path}.{key}")

    if schema.get("type", "object") == "object":
        if not isinstance(parameters, dict):
            problems.append("parameters: expected object")
            return problems
        for key in schema.get("required", []):
            if key not in parameters:
                problems.append(f"parameters.{key}: required")
        for key, value in parameters.items():
            sub = (schema.get("properties") or {}).get(key)
            if sub is None:
                if schema.get("additionalProperties") is False:
                    problems.append(f"parameters.{key}: not declared and additionalProperties false")
                continue
            check(value, sub, f"parameters.{key}")
    return problems


def _validate_inputs(descriptor: ProviderDescriptor, inputs: Mapping[str, Any]) -> None:
    declared = set(descriptor.input_types)
    if not declared:
        return
    for name, value in inputs.items():
        type_name = type(value).__name__
        if type_name not in declared:
            raise ProviderRejectedInputError(
                descriptor.provider_id,
                f"input {name!r} has type {type_name}, declared input types: {sorted(declared)}",
            )


def _governor_lease(descriptor: ProviderDescriptor, provider_id: str):
    """Admission lease for the execution (best-effort: no governor → run)."""
    try:
        from paleo_workbench.runtime.resource_governor import (
            ResourceExhausted,
            TaskRequest,
            get_governor,
        )
        from paleo_workbench.runtime.task_categories import TaskCategory

        profile = descriptor.resource_profile
        category = TaskCategory(profile.category)
        request = TaskRequest(
            category=category,
            title=f"provider:{provider_id}",
            estimated_cpu_cores=profile.estimated_cpu_cores,
            estimated_ram_bytes=profile.estimated_ram_bytes,
            estimated_vram_bytes=profile.estimated_vram_bytes,
            io_weight=profile.io_weight,
        )
        return get_governor().admit(request)
    except ImportError:
        return None
    # ResourceExhausted propagates: pressure shedding is a first-class outcome.


def execute_provider(
    registry_or_provider: Any,
    provider_id: str | None = None,
    *,
    inputs: Mapping[str, Any] | None = None,
    parameters: Mapping[str, Any] | None = None,
    context: ProviderContext | None = None,
) -> ProviderResult:
    """Run one provider through the guarded pipeline.

    ``registry_or_provider`` may be a registry (with ``provider_id``) or a
    provider instance (``provider_id`` then only used for error messages).
    """
    if provider_id is None and hasattr(registry_or_provider, "descriptor"):
        provider: CapabilityProvider = registry_or_provider
        provider_id = provider.descriptor.provider_id
    else:
        provider = registry_or_provider.get(provider_id)  # type: ignore[union-attr]
    descriptor = provider.descriptor

    inputs = dict(inputs or {})
    parameters = dict(parameters or {})

    problems = validate_parameters(descriptor.parameters_schema, parameters)
    if problems:
        raise InvalidParametersError(descriptor.provider_id, problems)
    _validate_inputs(descriptor, inputs)

    lease = _governor_lease(descriptor, descriptor.provider_id)
    run_ref = None
    catalog = context.catalog if context is not None else None
    operation = f"provider.{descriptor.family.value}.{descriptor.provider_id}"
    t0 = time.perf_counter()
    try:
        if catalog is not None and getattr(catalog, "begin_run", None) is not None:
            input_version_ids = [
                v.version_id
                for v in inputs.values()
                if hasattr(v, "version_id") and getattr(v, "version_id", None)
            ]
            try:
                run_ref = catalog.begin_run(
                    operation=operation,
                    input_version_ids=input_version_ids,
                    parameters=_jsonable(parameters),
                    generator_version=descriptor.version,
                )
            except Exception:
                logger.exception("provider run begin failed (continuing without run record)")
                run_ref = None
        if context is not None and run_ref is not None:
            context.run_id = getattr(run_ref, "run_id", None) or getattr(run_ref, "id", None)
        result = provider.execute(inputs, parameters, context or ProviderContext())
    except BaseException as exc:
        if run_ref is not None and getattr(catalog, "complete_run", None) is not None:
            try:
                catalog.complete_run(getattr(run_ref, "run_id", None) or getattr(run_ref, "id", None), status="failed")
            except Exception:
                logger.exception("provider run failure-status update failed")
        if isinstance(exc, ProviderError):
            # Contract errors (rejected inputs, provider-raised SDK errors)
            # pass through unwrapped — they already carry their semantics.
            raise
        raise ProviderExecutionError(descriptor.provider_id, exc) from exc
    finally:
        if lease is not None:
            lease.release()

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    result.metrics.setdefault("elapsed_ms", round(elapsed_ms, 3))
    result.provenance.setdefault("provider_id", descriptor.provider_id)
    result.provenance.setdefault("provider_version", descriptor.version)
    result.provenance.setdefault("operation", operation)
    if parameters:
        result.provenance.setdefault("parameters", _jsonable(parameters))
    if run_ref is not None and getattr(catalog, "complete_run", None) is not None:
        run_id = getattr(run_ref, "run_id", None) or getattr(run_ref, "id", None)
        try:
            catalog.complete_run(run_id, status="complete")
            result.provenance["run_id"] = run_id
        except Exception:
            logger.exception("provider run completion failed")
    return result


def _jsonable(value: Any) -> Any:
    """Best-effort conversion for provenance records (JSON-schema space)."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "to_dict"):
        try:
            return value.to_dict()
        except Exception:
            pass
    return str(value)
