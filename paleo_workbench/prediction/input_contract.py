"""Schema-driven prediction input resolution (Stage 13).

When a :class:`ModelVersion.input_schema` declares required asset types,
only those versions are included in the inference DataRun. An empty schema
falls back to the legacy project-wide well/seismic/factor gather for
heuristic compatibility — production packages must declare schemas.
"""

from __future__ import annotations

from typing import Any

from paleo_workbench.project.models import ProjectDocument


class InputContractError(ValueError):
    """Required model inputs cannot be resolved from the project/catalog."""


# Keys parse_input_schema understands; anything else is unknown vocabulary.
_RECOGNIZED_SCHEMA_KEYS = frozenset(
    {
        "required_asset_types",
        "asset_types",
        "optional_asset_types",
        "required_curves",
        "curves",
        "require_target_horizon",
        "require_correlation",
        "require_horizon_interpretation",
        "require_fault_interpretation",
        "min_wells",
    }
)


def parse_input_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize input_schema keys used by resolve_model_inputs."""
    schema = dict(schema or {})
    required_types = schema.get("required_asset_types") or schema.get("asset_types") or []
    if isinstance(required_types, str):
        required_types = [required_types]
    optional_types = schema.get("optional_asset_types") or []
    if isinstance(optional_types, str):
        optional_types = [optional_types]
    curves = schema.get("required_curves") or schema.get("curves") or []
    if isinstance(curves, str):
        curves = [curves]
    return {
        "required_asset_types": [str(t).strip() for t in required_types if str(t).strip()],
        "optional_asset_types": [str(t).strip() for t in optional_types if str(t).strip()],
        "required_curves": [str(c).strip() for c in curves if str(c).strip()],
        "require_target_horizon": bool(schema.get("require_target_horizon", False)),
        "require_correlation": bool(schema.get("require_correlation", False)),
        "require_horizon_interpretation": bool(
            schema.get("require_horizon_interpretation", False)
        ),
        "require_fault_interpretation": bool(
            schema.get("require_fault_interpretation", False)
        ),
        "min_wells": int(schema.get("min_wells") or 0),
        "raw": schema,
    }


def resolve_model_inputs(
    project: ProjectDocument,
    service,
    model_version,
    *,
    strict: bool = True,
) -> list[str]:
    """Resolve exact DataVersion ids for a model version's input_schema.

    Returns the list that must be stored on the inference DataRun.
    Raises :class:`InputContractError` when strict and required inputs missing.
    """
    from paleo_workbench.prediction.inference_service import (
        resolve_prediction_inputs,
        _resolve_resource_version_id,
    )
    from paleo_workbench.catalog.lifecycle import _versions_for_domain_tasks

    schema = parse_input_schema(getattr(model_version, "input_schema", None) or {})
    required_types = schema["required_asset_types"]

    # Empty schema → legacy global gather (heuristic / unscoped models).
    if not required_types and not any(
        (
            schema["require_correlation"],
            schema["require_horizon_interpretation"],
            schema["require_fault_interpretation"],
            schema["require_target_horizon"],
            schema["min_wells"] > 0,
        )
    ):
        raw_schema = getattr(model_version, "input_schema", None) or {}
        if strict and raw_schema and not (set(raw_schema) & _RECOGNIZED_SCHEMA_KEYS):
            # A schema that declares something we cannot interpret must not
            # silently fall back to the project-wide gather (H5-b).
            raise InputContractError(
                "input_schema 使用了未识别的结构，无法按契约解析输入："
                + ", ".join(sorted(str(k) for k in raw_schema.keys()))
            )
        input_ids = resolve_prediction_inputs(project, service)
        if schema["required_curves"] and strict:
            _enforce_required_curves(project, service, input_ids, schema["required_curves"])
        return input_ids

    input_ids: list[str] = []
    seen: set[str] = set()
    wells_count = 0

    def _add(vid: str | None) -> None:
        if vid and vid not in seen:
            seen.add(vid)
            input_ids.append(vid)

    collect_types = set(required_types) | set(schema["optional_asset_types"])
    # Resource types only (not abstract interpretation roles).
    resource_types = {
        t for t in collect_types if t in {"well_log", "seismic", "factor_map"}
    }

    for resource in project.resources:
        rtype = getattr(resource, "type", "") or ""
        if rtype not in resource_types:
            continue
        version_id = _resolve_resource_version_id(service, resource.id)
        if version_id is None:
            continue
        _add(version_id)
        if rtype == "well_log":
            wells_count += 1

    if "factor_map" in collect_types:
        task_ids = [
            t.id
            for t in project.factor_map_tasks
            if getattr(t, "status", "") == "complete"
        ]
        for version_id in _versions_for_domain_tasks(
            task_ids, catalog=_ServiceRunView(service)
        ):
            _add(version_id)

    if schema["require_correlation"] or "correlation" in required_types:
        found = False
        for ref in getattr(project, "correlation_interpretations", None) or []:
            vid = getattr(ref, "current_version_id", None)
            if vid:
                _add(str(vid))
                found = True
        if strict and schema["require_correlation"] and not found:
            raise InputContractError("模型要求对比解释版本，但工程中未选中对比解释")

    if schema["require_horizon_interpretation"] or "horizon" in required_types:
        found = False
        for ref in getattr(project, "horizon_interpretations", None) or []:
            vid = getattr(ref, "current_version_id", None)
            if vid:
                _add(str(vid))
                found = True
        if strict and schema["require_horizon_interpretation"] and not found:
            raise InputContractError("模型要求层位解释版本，但工程中未选中层位解释")

    if schema["require_fault_interpretation"] or "fault" in required_types:
        found = False
        for ref in getattr(project, "fault_interpretations", None) or []:
            vid = getattr(ref, "current_version_id", None)
            if vid:
                _add(str(vid))
                found = True
        if strict and schema["require_fault_interpretation"] and not found:
            raise InputContractError("模型要求断层解释版本，但工程中未选中断层解释")

    if schema["require_target_horizon"] and strict:
        th = getattr(getattr(project, "stratigraphy", None), "target_horizon", "") or ""
        if not str(th).strip():
            try:
                from paleo_workbench.workflow.correlation_lifecycle import (
                    resolve_correlation_target_horizon,
                )

                th = resolve_correlation_target_horizon(project) or ""
            except Exception:
                th = ""
        if not str(th).strip():
            raise InputContractError("模型要求目标层位，但工程未设置目标层位")

    if schema["min_wells"] and wells_count < schema["min_wells"] and strict:
        raise InputContractError(
            f"模型要求至少 {schema['min_wells']} 口井，当前可解析 {wells_count} 口"
        )

    if required_types and strict:
        present_types: set[str] = set()
        for vid in input_ids:
            info = _asset_type_for_version(service, vid)
            if info:
                present_types.add(info)
        missing: list[str] = []
        for t in required_types:
            if t in {"correlation", "horizon", "fault"}:
                continue
            if t == "factor_map":
                # The contract requires an ACTUALLY resolved factor version:
                # a task marked complete whose latest run failed does not
                # satisfy it (H5-c).
                if "factor_map" not in present_types and "factor_grid" not in present_types:
                    missing.append("factor_map")
                continue
            if t not in present_types:
                missing.append(t)
        if missing:
            raise InputContractError(
                f"模型缺少必需输入类型: {', '.join(missing)}"
            )

    if schema["required_curves"] and strict:
        _enforce_required_curves(project, service, input_ids, schema["required_curves"])

    return input_ids


def _enforce_required_curves(
    project: ProjectDocument,
    service,
    input_ids: list[str],
    required_curves: list[str],
) -> None:
    """Raise :class:`InputContractError` when resolved inputs lack required curves.

    Curve availability is best-effort: recorded ``parsed_summary["curves"]``
    first, otherwise the LAS header is read via the shared lightweight preview
    loader. Fail closed: unreadable or missing well-log inputs cannot satisfy
    the contract.
    """
    names, inspected = _resolved_well_curve_names(project, service, input_ids)
    required = [str(curve) for curve in required_curves]
    missing = [curve for curve in required if curve.upper() not in names]
    if not missing:
        return
    if inspected == 0:
        raise InputContractError(
            f"模型要求曲线 {', '.join(required)}，但未解析到提供曲线的测井输入"
        )
    available = ", ".join(sorted(names)) or "无"
    raise InputContractError(
        f"模型缺少必需曲线: {', '.join(missing)}（测井输入可用曲线: {available}）"
    )


def _resolved_well_curve_names(
    project: ProjectDocument,
    service,
    input_ids: list[str],
) -> tuple[set[str], int]:
    """Return (curve mnemonics, inspected well-log input count) for resolved inputs."""
    from paleo_workbench.prediction.inference_service import _resolve_resource_version_id
    from paleo_workbench.prediction.adapters import _resolve_resource_path

    resolved = set(input_ids)
    names: set[str] = set()
    inspected = 0
    for resource in project.resources:
        if getattr(resource, "type", "") != "well_log":
            continue
        version_id = _resolve_resource_version_id(service, resource.id)
        if version_id is None or version_id not in resolved:
            continue
        inspected += 1
        for curve in (getattr(resource, "parsed_summary", None) or {}).get("curves") or []:
            name = (
                curve
                if isinstance(curve, str)
                else str(
                    (curve.get("mnemonic") if isinstance(curve, dict) else None)
                    or (curve.get("name") if isinstance(curve, dict) else None)
                    or getattr(curve, "mnemonic", "")
                    or getattr(curve, "name", "")
                )
            ).strip()
            if name:
                names.add(name.upper())
        path = _resolve_resource_path(resource, project)
        if path is None:
            continue
        try:
            from geoviz import load_las_preview

            data = load_las_preview(str(path), fast=True)
        except Exception:
            continue
        for curve in getattr(data, "curves", None) or []:
            name = str(
                getattr(curve, "name", "") or getattr(curve, "mnemonic", "") or ""
            ).strip()
            if name:
                names.add(name.upper())
    return names, inspected


def _asset_type_for_version(service, version_id: str) -> str:
    try:
        version = service.get_version(version_id)
    except Exception:
        return ""
    for asset in service.document.assets:
        if asset.id == version.asset_id:
            return str(asset.type or "")
    return str(getattr(version, "metadata", {}) or {}).get("kind", "")


class _ServiceRunView:
    def __init__(self, service):
        self._service = service

    def list_runs(self):
        return [_RunProxy(run) for run in self._service.document.runs]

    def resolve_version(self, version_id):
        try:
            return self._service.get_version(version_id)
        except Exception:
            return None


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

    @property
    def status(self):
        return self._run.status
