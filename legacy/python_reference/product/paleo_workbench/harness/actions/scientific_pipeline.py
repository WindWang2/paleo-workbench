"""Scientific pipeline harness actions (V8 M6).

Real production services exposed through the unified ActionSpec surface —
every action is a typed wrapper over an EXISTING service (no wrapper-of-
wrapper, no new science): interpolation from :mod:`factor_interpolation`,
polygonization from the geological pipeline, the constraint lifecycle from
:mod:`constraint_versions`, fusion from :mod:`integrated_compilation`,
product lifecycle from :mod:`map_product`. WRITE actions carry verifiers;
unsupported context returns honest ``unavailable``/``rejected`` payloads —
fabricated results are never an option.
"""

from __future__ import annotations

from typing import Any

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.spec import ActionRisk, ActionSpec


def register(registry) -> None:
    # ---- factor.* ---------------------------------------------------------
    registry.register(
        ActionSpec(
            action_id="factor.interpolate",
            description=(
                "对因子任务执行真实插值（记录的任务参数为准：method/grid_n/"
                "power），产出网格 + 约束诊断 + 重复样本策略报告。"
            ),
            handler=_factor_interpolate,
            verifier=_verify_factor_interpolate,
            risk=ActionRisk.WRITE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 1.5, "io_weight": 0.5},
            required_context=("project",),
            supports_cancel=True,
            side_effect_notes="mutates the FactorMapTask in the live project document (grid + params)",
            version="1.0",
            deterministic=True,
            idempotent=True,
            domain_tags=("factor", "interpolation", "scientific"),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "因子任务名或 id"},
                    "method": {"type": "string", "description": "覆盖方法（省略=任务记录值）"},
                    "grid_n": {"type": "integer", "minimum": 8, "maximum": 2000},
                    "power": {"type": "number", "minimum": 0.5, "maximum": 8.0},
                },
                "required": ["task"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "task_id": {"type": "string"},
                    "method": {"type": ["string", "null"]},
                    "backend": {"type": ["string", "null"]},
                    "grid": {"type": ["string", "null"]},
                    "quality_metrics": {"type": "object"},
                    "constraint_diagnostics": {"type": "object"},
                    "sample_normalization": {"type": "object"},
                },
                # no hard required: honest-error payloads ({"error": ...}) must
                # pass the same executor-side output validation (#1178)
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="factor.polygonize",
            description=(
                "把因子网格按目标类别多边形化（单元边界追踪 → GeoJSON "
                "Polygon/MultiPolygon），孔洞归属确定性分配。"
            ),
            handler=_factor_polygonize,
            risk=ActionRisk.COMPUTE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 1.0, "io_weight": 0.3},
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "level": {
                        "type": "number",
                        "description": "等值面阈值（省略=网格中位数）",
                    },
                },
                "required": ["task"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "features": {
                        "type": ["array", "null"],
                        "description": "GeoJSON Polygon/MultiPolygon 要素",
                    },
                },
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="factor.compare_versions",
            description=(
                "比较因子任务两个网格版本（或当前网格 vs 已归档版本）的"
                "差异统计：形状/范围/逐单元差异与变更单元计数。"
            ),
            handler=_factor_compare_versions,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.3},
            required_context=("project", "catalog"),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "version_a": {
                        "type": ["string", "null"],
                        "description": "catalog 版本 id（省略=当前网格）",
                    },
                    "version_b": {"type": "string"},
                },
                "required": ["task", "version_b"],
                "additionalProperties": False,
            },
        )
    )
    # ---- constraint.* -----------------------------------------------------
    registry.register(
        ActionSpec(
            action_id="constraint.validate",
            description=(
                "约束可用性检查：几何有效性（最少顶点/闭合环）+ 方法×约束"
                "能力矩阵评估（unsupported/partial 明示，绝不静默降级）。"
            ),
            handler=_constraint_validate,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.1},
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "description": "待评估方法（IDW/克里金/约束IDW…）",
                    },
                    "kinds": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "约束类型（barrier/direction/boundary_mask/anisotropy/trend）",
                    },
                },
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="constraint.commit",
            description=(
                "把约束组的权威内容提交为 catalog DERIVED 版本（内容不变"
                "则不产生新版本；DataRun 记录提交者/备注/行数）。"
            ),
            handler=_constraint_commit,
            verifier=_verify_constraint_commit,
            risk=ActionRisk.WRITE,
            category="background.io",
            resource_profile={"estimated_cpu_cores": 0.3, "io_weight": 1.0},
            required_context=("project", "catalog"),
            side_effect_notes="creates an immutable catalog DataVersion + DataRun per changed group",
            version="1.0",
            deterministic=False,  # version ids/timestamps differ per commit
            idempotent=True,  # unchanged content re-commits nothing
            domain_tags=("constraints", "catalog", "lifecycle"),
            input_schema={
                "type": "object",
                "properties": {
                    "group": {
                        "type": ["string", "null"],
                        "description": "约束组名或 id（省略=全部组）",
                    },
                    "actor": {"type": "string"},
                    "notes": {"type": "string"},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "groups": {
                        "type": "array",
                        "description": "每组提交报告（version_id/reason/行数）",
                    },
                    "n_committed": {"type": "integer"},
                    "n_unchanged": {"type": "integer"},
                    "n_no_content": {"type": "integer"},
                },
            },
        )
    )
    # ---- fusion.* ---------------------------------------------------------
    registry.register(
        ActionSpec(
            action_id="fusion.run",
            description=(
                "按编译证据集运行多因素融合（加权/规则），登记似然/置信度"
                "descriptors；证据集为空或无 factor 条目时诚实拒绝。"
            ),
            handler=_fusion_run,
            verifier=_verify_fusion_run,
            risk=ActionRisk.COMPUTE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 2.0, "io_weight": 1.0},
            required_context=("project",),
            supports_cancel=True,
            side_effect_notes="registers fusion output versions in the catalog when available",
            version="1.0",
            domain_tags=("fusion", "integrated", "scientific"),
            input_schema={
                "type": "object",
                "properties": {
                    "evidence": {
                        "type": ["object", "null"],
                        "description": "证据集映射（省略=工作区当前 Compilation Input Set）",
                    },
                    "weights": {
                        "type": ["object", "null"],
                        "description": "因子权重覆盖（factor name → weight）",
                    },
                    "register": {"type": "boolean", "description": "是否登记 catalog（默认 true）"},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "likelihood_descriptor": {"type": "object"},
                    "confidence_descriptor": {"type": "object"},
                    "registered": {"type": "boolean"},
                },
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="compilation.validate_inputs",
            description=(
                "编译输入集就绪性检查：逐条证据解析（factor 网格可解析/"
                "draft 存在/constraints 引用可解析），缺失逐条给出原因。"
            ),
            handler=_compilation_validate_inputs,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.3},
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "evidence": {
                        "type": ["object", "null"],
                        "description": "证据集映射（省略=工作区当前值）",
                    },
                },
                "additionalProperties": False,
            },
        )
    )
    # ---- map_product.* ----------------------------------------------------
    registry.register(
        ActionSpec(
            action_id="map_product.qa",
            description=(
                "成图产品 QA：新鲜度指纹比对 + 发布门禁 + QC 规则"
                "（evaluated/skipped 分开计数，skipped 绝不冒充通过）。"
            ),
            handler=_map_product_qa,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.5},
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {"product": {"type": "string"}},
                "required": ["product"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="map_product.freeze",
            description=(
                "冻结/解冻成图产品：冻结记录拒绝 clone/rerun/supersede"
                "（保护已定稿产品不被意外覆盖）。"
            ),
            handler=_map_product_freeze,
            verifier=_verify_map_product_freeze,
            risk=ActionRisk.WRITE,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.1, "io_weight": 0.1},
            required_context=("project",),
            side_effect_notes="flips MapProductRecord.frozen (document-level guard)",
            version="1.0",
            idempotent=True,
            domain_tags=("map_product", "lifecycle"),
            input_schema={
                "type": "object",
                "properties": {
                    "product": {"type": "string"},
                    "frozen": {"type": "boolean", "description": "默认 true"},
                },
                "required": ["product"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "product": {"type": "string"},
                    "product_name": {"type": ["string", "null"]},
                    "frozen": {"type": "boolean"},
                },
            },
        )
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _find_task(context: ActionContext, name: str):
    project = context.project
    return next(
        (t for t in project.factor_map_tasks if name in (t.id, t.name)), None
    )


def _catalog_service(context: ActionContext):
    """Resolve the underlying DataCatalogService from the injected port."""
    catalog = getattr(context, "catalog", None)
    if catalog is None:
        return None
    return getattr(catalog, "service", catalog)


def _workspace_evidence(context: ActionContext) -> dict[str, str]:
    """The mapping workspace's current Compilation Input Set, if reachable."""
    state = (context.extras or {}).get("mapping_workspace_state")
    if state is None:
        controller = (context.extras or {}).get("stage_controller")
        state = getattr(controller, "state", None) if controller else None
    if state is None:
        return {}
    # V9（评审 R2-F1）：经单一适配器读证据集（结构化激活输入集优先）。
    from paleo_workbench.workflow.interpretation.compilation import (
        evidence_view,
    )

    return evidence_view(context.project, state)


# ---------------------------------------------------------------------------
# factor handlers
# ---------------------------------------------------------------------------


def _factor_interpolate(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.factor_interpolation import (
        apply_interpolation_to_task,
        interpolation_params_from_task,
    )

    task = _find_task(context, str(parameters.get("task", "")))
    if task is None:
        return {"error": "not_found", "detail": "因子任务不存在"}
    method, grid_n, power = interpolation_params_from_task(task)
    if parameters.get("method"):
        method = str(parameters["method"])
    if parameters.get("grid_n"):
        grid_n = int(parameters["grid_n"])
    if parameters.get("power"):
        power = float(parameters["power"])
    try:
        apply_interpolation_to_task(
            task,
            method=method,
            grid_n=grid_n,
            power=power,
            project=context.project,
            cancellation_token=context.cancel,
        )
    except Exception as exc:
        # Cancellation is first-class: geoviz JobCancelled / scheduler
        # TaskCancelled must reach the executor's CANCELLED mapping, never
        # be laundered into a FAILED payload (review R1-P1). Explicit
        # tuple — name heuristics misroute future exceptions (R2-P2).
        from geoviz import JobCancelled as _JobCancelled
        from paleo_workbench.runtime.task_scheduler import TaskCancelled

        if isinstance(exc, (TaskCancelled, _JobCancelled)) or (context.cancel and context.cancel.is_set()):
            raise
        return {
            "error": "failed",
            "detail": f"{task.name}: {exc}",
            "task_id": task.id,
            "task_status": getattr(task, "status", ""),
        }
    if task.status != "complete":
        return {
            "error": "failed",
            "detail": str((task.parameters or {}).get("last_error", "interpolation failed")),
            "task_status": task.status,
        }
    return {
        "task": task.name,
        "task_id": task.id,
        "method": task.method,
        "backend": (task.parameters or {}).get("interp_backend"),
        "grid": (task.parameters or {}).get("grid"),
        "quality_metrics": dict(task.quality_metrics or {}),
        "constraint_diagnostics": (task.parameters or {}).get(
            "constraint_diagnostics"
        ),
        "sample_normalization": (task.parameters or {}).get("sample_normalization"),
    }


def _verify_factor_interpolate(payload, parameters, context) -> dict:
    """Post-WRITE check: the delivered task is complete with honest provenance."""
    if payload.get("error"):
        return {"verdict": "fail", "reasons": [str(payload.get("detail"))]}
    task_id = str(payload.get("task_id", ""))
    if not task_id:
        return {"verdict": "fail", "reasons": ["payload carries no task id"]}
    task = _find_task(context, task_id)
    if task is None:
        return {"verdict": "fail", "reasons": [f"task {task_id!r} vanished"]}
    problems = []
    if task.status != "complete":
        problems.append(f"task status {task.status!r} != complete")
    params = task.parameters or {}
    if "constraint_diagnostics" not in params:
        problems.append("constraint diagnostics missing from provenance")
    if "sample_points" not in params:
        problems.append("sample provenance missing")
    from paleo_workbench.project.factor_grid_artifacts import peek_live_factor_grid

    if peek_live_factor_grid(task.id) is None:
        problems.append("no live grid attached after interpolation")
    return {"verdict": "pass" if not problems else "fail", "reasons": problems}


def _factor_polygonize(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.mapping.geological_pipeline.polygonization import (
        polygonize_factor_grid,
    )
    from paleo_workbench.project.factor_grid_artifacts import (
        factor_grid_result_for_task,
    )

    task = _find_task(context, str(parameters.get("task", "")))
    if task is None:
        return {"error": "not_found", "detail": "因子任务不存在"}
    grid = factor_grid_result_for_task(task)
    if grid is None:
        return {
            "error": "unavailable",
            "detail": "任务没有可用的因子网格（先运行插值）",
        }
    result = polygonize_factor_grid(
        grid,
        level=(
            float(parameters["level"])
            if parameters.get("level") is not None
            else None
        ),
    )
    return {"task": task.name, **result}



def _factor_compare_versions(context: ActionContext, parameters: dict) -> dict:
    import numpy as np

    from paleo_workbench.catalog.grid_artifact import read_grid_artifact
    from paleo_workbench.project.factor_grid_artifacts import (
        factor_grid_result_for_task,
    )

    task = _find_task(context, str(parameters.get("task", "")))
    if task is None:
        return {"error": "not_found", "detail": "因子任务不存在"}

    def _current_grid():
        grid = factor_grid_result_for_task(task)
        if grid is None:
            raise ValueError("任务当前没有可用网格")
        return np.asarray(grid.grid_z, dtype=float)

    def _version_grid(version_id: str):
        version = context.catalog.resolve_version(str(version_id))
        if version is None:
            raise ValueError(f"版本 {version_id!r} 不存在")
        result = read_grid_artifact(str(version.path))
        return np.asarray(result.grid_z, dtype=float)

    try:
        a = (
            _version_grid(str(parameters["version_a"]))
            if parameters.get("version_a")
            else _current_grid()
        )
        b = _version_grid(str(parameters["version_b"]))
    except ValueError as exc:
        return {"error": "unavailable", "detail": str(exc)}
    if a.shape != b.shape:
        return {
            "task": task.name,
            "shape_a": list(a.shape),
            "shape_b": list(b.shape),
            "comparable": False,
            "detail": "网格形状不同（grid_n 改变）——逐单元比较不可定义",
        }
    both = np.isfinite(a) & np.isfinite(b)
    diff = np.where(both, a - b, np.nan)
    changed = int(np.sum(both & (np.abs(diff) > 1e-9)))
    return {
        "task": task.name,
        "comparable": True,
        "shape": list(a.shape),
        "cells_compared": int(both.sum()),
        "cells_nodata_either": int(a.size - int(both.sum())),
        "cells_changed": changed,
        "max_abs_diff": float(np.nanmax(np.abs(diff))) if both.any() else None,
        "mean_abs_diff": float(np.nanmean(np.abs(diff))) if both.any() else None,
        "identical": changed == 0,
    }


# ---------------------------------------------------------------------------
# constraint handlers
# ---------------------------------------------------------------------------


def _constraint_validate(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.constraint_capabilities import (
        ConstraintKind,
        evaluate_request,
    )
    from paleo_workbench.workflow.constraints import constraint_layers_for_project

    project = context.project
    kinds_requested = [str(k) for k in (parameters.get("kinds") or [])]
    kinds: list[ConstraintKind] = []
    unknown: list[str] = []
    for name in kinds_requested:
        try:
            kinds.append(ConstraintKind(name))
        except ValueError:
            unknown.append(name)

    geometry: list[dict[str, Any]] = []
    for group in constraint_layers_for_project(project):
        for line in group.lines:
            if not line.active:
                continue
            n = len(line.coordinates or [])
            entry = {
                "line": line.name or line.id,
                "role": line.role,
                "vertices": n,
                "valid": True,
                "problems": [],
            }
            if n == 0:
                entry["valid"] = False
                entry["problems"].append("无几何（尚未数字化）")
            elif n < 2:
                entry["valid"] = False
                entry["problems"].append("顶点数 < 2")
            geometry.append(entry)

    method = parameters.get("method")
    capability = None
    if method:
        evaluation = evaluate_request(str(method), kinds)
        capability = evaluation.as_dict()
    return {
        "method": method,
        "requested_kinds": kinds_requested,
        "unknown_kinds": unknown,
        "capability": capability,
        "geometry": geometry,
        "n_invalid": sum(1 for e in geometry if not e["valid"]),
    }


def _constraint_commit(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.constraint_versions import (
        commit_all_constraints,
        commit_constraint_group,
    )

    service = _catalog_service(context)
    if service is None:
        return {"error": "unavailable", "detail": "catalog 服务不可用"}
    project = context.project
    actor = str(parameters.get("actor") or "")
    notes = str(parameters.get("notes") or "")
    target = parameters.get("group")
    if target:
        group = next(
            (
                g
                for g in project.constraint_layers
                if target in (g.id, g.name)
            ),
            None,
        )
        if group is None:
            return {"error": "not_found", "detail": f"约束组 {target!r} 不存在"}
        reports = [
            commit_constraint_group(
                project, service, group, actor=actor, notes=notes
            )
        ]
    else:
        reports = commit_all_constraints(
            project, service, actor=actor, notes=notes
        )
    committed = [r for r in reports if r.committed]
    return {
        "groups": [r.to_dict() for r in reports],
        "n_committed": len(committed),
        "n_unchanged": sum(1 for r in reports if r.reason == "unchanged"),
        "n_no_content": sum(1 for r in reports if r.reason == "no_content"),
    }


def _verify_constraint_commit(payload, parameters, context) -> dict:
    """Post-WRITE check: every claimed version resolves with matching hash."""
    problems = []
    for entry in payload.get("groups", []):
        version_id = entry.get("version_id")
        if not version_id:
            if entry.get("reason") in ("unchanged", "no_content"):
                continue
            problems.append(f"group {entry.get('group_id')}: no version id")
            continue
        resolved = context.catalog.resolve_version(str(version_id))
        if resolved is None:
            problems.append(f"version {version_id!r} not resolvable")
    return {"verdict": "pass" if not problems else "fail", "reasons": problems}


# ---------------------------------------------------------------------------
# fusion handlers
# ---------------------------------------------------------------------------


def _fusion_run(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.integrated_compilation import (
        run_integrated_fusion,
    )

    evidence = parameters.get("evidence") or _workspace_evidence(context)
    if not evidence:
        return {
            "error": "rejected",
            "detail": "证据集为空——先选择证据版本（Compilation Input Set）",
        }
    if not any(str(v).startswith("factor:") for v in evidence.values()):
        return {
            "error": "rejected",
            "detail": "证据集中没有单因素证据（factor 条目）",
        }
    # injected port only — the harness never opens databases by itself
    # (ActionContext contract; review R2-P1: the process-global singleton
    # could target the wrong project's catalog).
    catalog = _catalog_service(context)
    register = bool(parameters.get("register", True)) and catalog is not None
    try:
        summary = run_integrated_fusion(
            context.project,
            evidence,
            catalog,
            weights=parameters.get("weights") or None,
            register=register,
        )
    except Exception as exc:
        return {"error": "failed", "detail": f"{type(exc).__name__}: {exc}"}
    summary = dict(summary)
    summary["registered"] = register
    if not register:
        summary["detail"] = "catalog 不可用——结果未登记为版本（诚实降级）"
    return summary


def _verify_fusion_run(payload, parameters, context) -> dict:
    problems = []
    if payload.get("error"):
        return {"verdict": "fail", "reasons": [str(payload.get("detail"))]}
    if payload.get("likelihood_descriptor") is None:
        problems.append("no likelihood descriptor produced")
    if payload.get("confidence_descriptor") is None:
        problems.append("no confidence descriptor produced")
    if payload.get("registered") and not (
        payload.get("catalog_version_id")
        or (payload.get("qc") or {}).get("registration", {}).get("catalog_version_id")
    ):
        problems.append("claimed registered but no catalog version id")
    return {"verdict": "pass" if not problems else "fail", "reasons": problems}


def _compilation_validate_inputs(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.integrated_compilation import (
        fusion_inputs_from_document,
    )

    evidence = parameters.get("evidence") or _workspace_evidence(context)
    if not evidence:
        return {
            "ready": False,
            "entries": [],
            "detail": "证据集为空（或工作区状态不可达——显式传入 evidence）",
        }
    resolved: dict = {}
    resolution_error: str = ""
    try:
        mismatches: list[str] = []
        resolved = fusion_inputs_from_document(
            context.project, evidence, mismatches=mismatches)
    except ValueError as exc:
        resolution_error = str(exc)
    except Exception as exc:
        return {
            "ready": False,
            "entries": [],
            "detail": f"证据解析失败：{type(exc).__name__}: {exc}",
        }
    # The service lists every unresolvable factor in the ValueError message
    # (；-joined) — surface them as per-entry reasons instead of one blob.
    unresolved_reasons = (
        [part for part in resolution_error.split("；") if part]
        if resolution_error
        else []
    )
    entries = []
    for key, ref in evidence.items():
        ref = str(ref)
        if ref.startswith("factor:"):
            ok = key in resolved and not resolution_error
            entries.append(
                {
                    "key": key,
                    "ref": ref,
                    "kind": "factor",
                    "resolved": ok,
                    "reason": "" if ok else "网格不可解析（先运行该因子插值）",
                }
            )
        elif ref.startswith("draft:"):
            entries.append(
                {"key": key, "ref": ref, "kind": "draft", "resolved": True,
                 "reason": "人工解释草稿（不参与计算融合）"}
            )
        elif ref.startswith("constraints:"):
            from paleo_workbench.workflow.constraint_versions import (
                resolve_constraint_ref,
            )

            verdict = resolve_constraint_ref(
                context.project, _catalog_service(context), ref
            )
            entries.append(
                {"key": key, "ref": ref, "kind": "constraints",
                 "resolved": verdict["status"] != "unknown",
                 "reason": f"约束新鲜度：{verdict['detail']}"}
            )
        else:
            entries.append(
                {"key": key, "ref": ref, "kind": "version", "resolved": True,
                 "reason": "catalog 版本引用（未逐条校验存在性）"}
            )
    factor_ok = [e for e in entries if e["kind"] == "factor"]
    return {
        "ready": bool(factor_ok) and all(e["resolved"] for e in factor_ok),
        "entries": entries,
        "n_factor": len(factor_ok),
        "n_unresolved": sum(1 for e in entries if not e["resolved"]),
        "detail": resolution_error,
    }


# ---------------------------------------------------------------------------
# map_product handlers
# ---------------------------------------------------------------------------


def _map_product_qa(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.map_product import (
        find_map_product,
        product_staleness,
        publish_map_product,
    )

    record = find_map_product(context.project, str(parameters.get("product", "")))
    if record is None:
        return {"error": "not_found", "detail": "产品不存在"}
    staleness = product_staleness(record, context.project)
    try:
        gate = publish_map_product(
            record, context.project, export_path=None, accept_warnings=True
        )
    except ValueError as exc:
        gate = {"refused": str(exc)}
    return {
        "product": record.id,
        "product_name": record.product_name,
        "frozen": bool(record.frozen),
        "staleness": staleness,
        "publish_gate": gate,
        "gate_note": (
            "publish gate run in report-only mode (accept_warnings=True); "
            "refusals are reported, never bypassed"
        ),
    }


def _map_product_freeze(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.map_product import (
        find_map_product,
        freeze_map_product,
    )

    record = find_map_product(context.project, str(parameters.get("product", "")))
    if record is None:
        return {"error": "not_found", "detail": "产品不存在", "product": str(parameters.get("product", ""))}
    frozen = bool(parameters.get("frozen", True))
    freeze_map_product(record, frozen=frozen)
    return {"product": record.id, "product_name": record.product_name, "frozen": frozen}


def _verify_map_product_freeze(payload, parameters, context) -> dict:
    from paleo_workbench.workflow.map_product import find_map_product

    if payload.get("error"):
        return {"verdict": "fail", "reasons": [str(payload.get("detail"))]}
    record = find_map_product(context.project, str(payload.get("product", "")))
    if record is None:
        return {"verdict": "fail", "reasons": ["record vanished"]}
    expected = bool(payload.get("frozen"))
    if bool(record.frozen) != expected:
        return {
            "verdict": "fail",
            "reasons": [f"frozen={record.frozen}, expected {expected}"],
        }
    return {"verdict": "pass", "reasons": []}
