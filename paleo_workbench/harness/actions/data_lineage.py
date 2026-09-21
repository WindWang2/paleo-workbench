"""Data-lineage actions (V13 W-S): the agent surface for ingest / working
copies / map usage / recompute.

与 UI 共用同一 domain 实现（goal §9/§21 红线）：

- ingest → ``resources/ingest_plan.build/execute_ingest_plan``（与
  IngestPlanDialog 完全相同的服务函数）；
- working copy → ``catalog/service`` + ``catalog/lifecycle`` manual-edit
  助手（与 EditSession/DataLifecycleController 相同）；
- map usage → ``mapping_workspace/source_usage``（与 InspectorPanel 的
  provider 相同）；
- recompute → ``workflow/recompute_plan.PlanExecutor`` + factor_map
  handler（与 workflow_controller 相同的领域调用）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from paleo_workbench.catalog.models import DataStage
from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.spec import ActionRisk, ActionSpec

_STAGE_VALUES = [s.value for s in DataStage]


def register(registry) -> None:
    registry.register(
        ActionSpec(
            action_id="data.ingest_plan",
            description=(
                "构建导入计划（零副作用）：扫描目录→分类→身份匹配→角色推断"
                "→查重，返回可编辑的逐项决策视图。与规划导入 UI 同一服务。"
            ),
            handler=_ingest_plan,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 0.5, "estimated_ram_bytes": 0,
                              "io_weight": 0.8},
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "root": {"type": "string", "minLength": 1},
                    "limit_items": {"type": "integer", "minimum": 1,
                                    "maximum": 5000},
                },
                "required": ["root"],
                "additionalProperties": False,
            },
            domain_tags=("data", "ingest"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="data.ingest",
            description=(
                "执行导入：重建计划（确定性）→ 应用 decisions（缺省接受全部"
                "非重复项）→ 分块登记 + 实体绑定 + primary。幂等可重跑。"
            ),
            handler=_ingest,
            risk=ActionRisk.WRITE,
            category="background.io",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 1.0, "estimated_ram_bytes": 0,
                              "io_weight": 1.0},
            # #1428: registry policy gates require WRITE actions to declare
            # side effects and all producing actions a typed output shape.
            side_effect_notes=(
                "writes catalog versions + entity bindings into the project "
                "store; idempotent — re-running skips already-imported paths"
            ),
            output_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "object"},
                    "decisions_applied": {"type": "integer"},
                    "imported_version_ids": {"type": "array",
                                           "items": {"type": "string"}},
                    "skipped": {"type": "array"},
                    "bound_links": {"type": "integer"},
                    # IngestExecuteReport.created_entities is an int count
                    # (wells_created + entity upserts), not a list.
                    "created_entities": {"type": "integer"},
                    "issues": {"type": "array"},
                    "cancelled": {"type": "boolean"},
                },
                "required": ["imported_version_ids"],
            },
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "root": {"type": "string", "minLength": 1},
                    "decisions": {
                        "type": "object",
                        "description": "path → accept|skip|as_new_version",
                    },
                    "bind": {"type": "boolean", "default": True},
                },
                "required": ["root"],
                "additionalProperties": False,
            },
            domain_tags=("data", "ingest"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="data.create_working_copy",
            description=(
                "为版本创建可编辑工作副本（复用活动副本，绝不覆盖——#1211 契约）。"
            ),
            handler=_create_working_copy,
            risk=ActionRisk.WRITE,
            category="background.io",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 0.2, "estimated_ram_bytes": 0,
                              "io_weight": 0.5},
            # #1428: materializes a mutable file copy + registry row; never
            # overwrites an existing working copy (#1211 contract).
            side_effect_notes=(
                "materializes a working-copy file on disk and registers it "
                "in the catalog working_copies table (reuses an active copy)"
            ),
            output_schema={
                "type": "object",
                "properties": {"working_path": {"type": "string"}},
                "required": ["working_path"],
            },
            input_schema={
                "type": "object",
                "properties": {"version_id": {"type": "string", "minLength": 1}},
                "required": ["version_id"],
                "additionalProperties": False,
            },
            domain_tags=("data", "working_copy"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="data.commit_working_copy",
            description=(
                "提交工作副本为新不可变版本，并登记 manual_edit DataRun"
                "（人工修改不再是血缘黑洞）。"
            ),
            handler=_commit_working_copy,
            risk=ActionRisk.WRITE,
            category="background.io",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 1.0, "estimated_ram_bytes": 0,
                              "io_weight": 1.0},
            # #1428: commits a new immutable version + manual_edit DataRun.
            side_effect_notes=(
                "commits the working copy as a new immutable catalog version "
                "(same-asset bump or new asset) and registers a manual_edit "
                "DataRun; removes the working-copy registry row"
            ),
            output_schema={
                "type": "object",
                "properties": {
                    "version_id": {"type": "string"},
                    "asset_id": {"type": "string"},
                    "stage": {"type": "string", "enum": _STAGE_VALUES},
                    "run_id": {"type": "string"},
                },
                "required": ["version_id", "asset_id"],
            },
            input_schema={
                "type": "object",
                "properties": {
                    "working_path": {"type": "string", "minLength": 1},
                    "name": {"type": "string"},
                    "stage": {"type": "string", "enum": _STAGE_VALUES},
                    "actor": {"type": "string"},
                    "note": {"type": "string"},
                    "asset_id": {
                        "type": "string",
                        "description": (
                            "目标资产 id：缺省=同资产升版（取注册行源资产，"
                            "与 UI/EditSession 一致）；\"new\"=另立新资产"),
                    },
                },
                "required": ["working_path"],
                "additionalProperties": False,
            },
            domain_tags=("data", "working_copy"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="data.map_usage",
            description=(
                "反查版本/资产的地图用途：哪些编图图层、综合编图输入集、"
                "成图产品正在引用它（派生投影，与数据页检查器同源）。"
            ),
            handler=_map_usage,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 0.3, "estimated_ram_bytes": 0,
                              "io_weight": 0.3},
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "version_id": {"type": "string"},
                    "asset_id": {"type": "string"},
                },
                "additionalProperties": False,
            },
            domain_tags=("data", "lineage", "mapping"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="data.recompute_stale",
            description=(
                "对过期成果构建并执行重算计划（当前支持 factor_map；与 UI "
                "工作流控制器共用同一领域调用）。返回逐步骤执行结果。"
            ),
            handler=_recompute_stale,
            risk=ActionRisk.COMPUTE,
            category="background.compute",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 4.0, "estimated_ram_bytes": 0,
                              "io_weight": 1.0},
            # #1428: COMPUTE actions must declare their output shape; the
            # payload differs between dry_run (plan only) and execution.
            output_schema={
                "type": "object",
                "properties": {
                    "dry_run": {"type": "boolean"},
                    "steps": {"type": "array"},
                    "completed_run_ids": {"type": "array",
                                          "items": {"type": "string"}},
                    "failed_run_ids": {"type": "array",
                                       "items": {"type": "string"}},
                    "skipped_run_ids": {"type": "array",
                                        "items": {"type": "string"}},
                    "messages": {"type": "array"},
                    "stopped_early": {"type": "boolean"},
                    "updated_tasks": {"type": "array"},
                },
                "required": ["dry_run"],
            },
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "dry_run": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            domain_tags=("data", "recompute"),
        )
    )


# ---------------------------------------------------------------------------
# helpers


def _service(context: ActionContext):
    from paleo_workbench.catalog.runtime import get_catalog_service

    return get_catalog_service()


def _workspace_state(context: ActionContext):
    from paleo_workbench.mapping_workspace.stage_state import (
        MappingWorkspaceState,
    )

    return MappingWorkspaceState.from_dict(
        getattr(context.project, "mapping_workspace", None) or {})


# ---------------------------------------------------------------------------
# handlers


def _ingest_plan(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.resources.ingest_plan import build_ingest_plan

    service = _service(context)
    if service is None:
        raise RuntimeError("无活动数据目录（catalog 未桥接）")
    limit = int(parameters.get("limit_items", 500))
    plan = build_ingest_plan(
        Path(parameters["root"]), context.project, service=service)
    items = []
    for item in plan.items[:limit]:
        items.append({
            "path": str(item.path),
            "type": item.type,
            "role": item.role,
            "entity": {
                "type": item.identity.entity_type,
                "id": item.identity.entity_id,
                "name": item.identity.entity_name,
                "new": item.identity.new_entity,
                "strategy": item.identity.strategy,
                "confidence": item.identity.confidence,
            },
            "primary": item.primary,
            "duplicate_of": item.duplicate_of_version,
            "decision": item.decision,
            "bundle": bool(item.bundle),
        })
    return {
        "summary": plan.summary(),
        "items": items,
        "truncated": len(plan.items) > len(items),
        "issues": list(plan.issues),
    }


def _ingest(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.resources.ingest_plan import (
        build_ingest_plan,
        execute_ingest_plan,
    )

    service = _service(context)
    if service is None:
        raise RuntimeError("无活动数据目录（catalog 未桥接）")
    plan = build_ingest_plan(
        Path(parameters["root"]), context.project, service=service)
    decisions = parameters.get("decisions") or {}

    def _norm(path_key: str) -> str:
        # 决策键归一：大小写（Win32）+ 正斜杠——调用方回显 plan 输出的
        # 路径可能被 JSON/手工改写分隔符，静默不匹配比报错更糟。
        import os

        normalized = str(path_key).replace("\\", "/")
        return os.path.normcase(normalized)

    normalized_decisions = {_norm(k): v for k, v in decisions.items()}
    applied = 0
    for item in plan.items:
        key = _norm(item.path)
        if key in normalized_decisions:
            value = str(normalized_decisions[key])
            if value in ("accept", "skip", "as_new_version", "pending"):
                item.decision = value
                applied += 1
        elif not item.duplicate_of_version:
            # 缺省接受非重复项（agent 显式调用即确认；与 UI 的
            # execute_unconfirmed=False 契约不同——UI 有人工确认环节）。
            item.decision = "accept"
    report = execute_ingest_plan(
        plan, service, context.project, bind=bool(parameters.get("bind", True)))
    return {
        "summary": plan.summary(),
        "decisions_applied": applied,
        "imported_version_ids": list(report.imported_version_ids),
        "skipped": list(report.skipped),
        "bound_links": report.bound_links,
        "created_entities": report.created_entities,
        "issues": list(report.issues),
        "cancelled": report.cancelled,
    }


def _create_working_copy(context: ActionContext, parameters: dict) -> dict:
    service = _service(context)
    if service is None:
        raise RuntimeError("无活动数据目录（catalog 未桥接）")
    path = service.create_working_copy(str(parameters["version_id"]))
    return {"working_path": str(path)}


def _commit_working_copy(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.catalog.lifecycle import (
        complete_manual_edit_run,
        register_manual_edit_run,
    )

    service = _service(context)
    if service is None:
        raise RuntimeError("无活动数据目录（catalog 未桥接）")
    working_path = str(parameters["working_path"])
    stage_value = str(parameters.get("stage") or "derived")
    stage = DataStage(stage_value)
    # 源版本/源资产来自副本注册行（不信任调用方回传——working_copies 是
    # 权威）。缺省同资产升版（与 UI/EditSession 语义一致）；
    # asset_id="new" 显式另立新资产。
    state = service.working_copy_state(Path(working_path))
    source_version_id = (state or {}).get("source_version_id") or ""
    source_asset_id = (state or {}).get("asset_id") or ""
    if not source_asset_id and source_version_id:
        try:
            source_asset_id = service.get_version(
                source_version_id).asset_id
        except Exception:
            source_asset_id = ""
    requested = str(parameters.get("asset_id") or "")
    if requested == "new":
        target_asset_id: str | None = None
    elif requested:
        target_asset_id = requested
    else:
        target_asset_id = source_asset_id or None
    run_id = None
    try:
        run = register_manual_edit_run(
            service,
            source_version_ids=[source_version_id] if source_version_id else [],
            actor=str(parameters.get("actor") or "agent"),
            note=str(parameters.get("note") or ""),
        )
        run_id = run.id
    except Exception:
        run_id = None
    try:
        version = service.commit_working_copy(
            working_path,
            asset_id=target_asset_id,
            name=str(parameters.get("name") or "") or None,
            stage=stage,
            run_id=run_id,
        )
    except Exception:
        if run_id:
            try:
                service.update_run_status(run_id, "failed")
            except Exception:
                pass
        raise
    if run_id:
        complete_manual_edit_run(
            service, run_id, committed_version_ids=[version.id])
    return {
        "version_id": version.id,
        "asset_id": version.asset_id,
        "stage": version.stage.value,
        "run_id": run_id or "",
    }


def _map_usage(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.mapping_workspace.source_usage import (
        usage_counts,
        usages_of_asset,
        usages_of_version,
    )

    service = _service(context)
    version_id = str(parameters.get("version_id") or "")
    asset_id = str(parameters.get("asset_id") or "")
    if not version_id and not asset_id:
        raise ValueError("需要 version_id 或 asset_id")
    workspace = _workspace_state(context)
    if version_id:
        report = usages_of_version(
            version_id, workspace=workspace, project=context.project,
            catalog=service)
    else:
        report = usages_of_asset(
            asset_id, workspace=workspace, project=context.project,
            catalog=service)
    return {
        "counts": usage_counts(report),
        "usages": [
            {"kind": u.kind, "ref_id": u.ref_id, "label": u.label,
             "stage": u.stage, "role": u.role, "status": u.status}
            for u in report.usages
        ],
        "truncated": report.truncated,
    }


def _recompute_stale(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.factor_interpolation import (
        apply_interpolation_to_task,
        interpolation_params_from_task,
    )
    from paleo_workbench.workflow.recompute_plan import PlanExecutor
    from paleo_workbench.workflow.service import build_affected_products_plan

    project = context.project
    plan = build_affected_products_plan(project)
    if parameters.get("dry_run"):
        return {
            "steps": [
                {"operation": s.operation, "run_id": s.run_id,
                 "domain_task_id": s.domain_task_id,
                 "action": s.action.value, "label": s.label}
                for s in plan.steps
            ],
            "dry_run": True,
        }
    updated_tasks: list[dict] = []

    def _factor_map_handler(step) -> None:
        task_id = step.domain_task_id
        task = next(
            (t for t in project.factor_map_tasks if str(t.id) == str(task_id)),
            None,
        )
        if task is None:
            raise RuntimeError(f"未找到单因素任务 {task_id!r}")
        method, grid_n, power = interpolation_params_from_task(task)
        apply_interpolation_to_task(
            task, project=project, method=method, grid_n=grid_n, power=power)
        updated_tasks.append({"task_id": str(task.id), "method": str(method)})

    result = PlanExecutor(
        handlers={"factor_map": _factor_map_handler}).execute(plan)
    return {
        "completed_run_ids": list(plan.completed_run_ids),
        "failed_run_ids": list(plan.failed_run_ids),
        "skipped_run_ids": list(plan.skipped_run_ids),
        "messages": list(result.messages),
        "stopped_early": result.stopped_early,
        "updated_tasks": updated_tasks,
        "dry_run": False,
    }
