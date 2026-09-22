"""Workflow-domain actions (Harness 2.0, H8): the agent's sanctioned
surface onto the DAG engine and recipes.

These actions wrap :class:`paleo_workbench.workflow.dag.WorkflowEngine` —
the same engine the host uses — so an agent can create, validate, run,
resume, cancel and describe workflows (and save/load/clone recipes)
without ever touching the scheduler, the project file or the catalog
directly. The engine owns every guard: static validation, governor
admission (per action), checkpoints, the project-switch probe.
"""
from __future__ import annotations

from typing import Any

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.spec import ActionRisk, ActionSpec
from paleo_workbench.workflow.dag import (
    RunState,
    WorkflowEngine,
    WorkflowSpec,
)
from paleo_workbench.workflow.dag.reproduction import describe_reproduction
from paleo_workbench.workflow.dag.store import WorkflowRunStore
from paleo_workbench.workflow.recipe import (
    RecipeDocument,
    clone_recipe,
    inspect_recipe,
    load_recipe,
    recipe_from_run,
    save_recipe,
)

#: Shared engine for workflow actions. The host (or tests) may install a
#: custom engine; the default lazily builds one over the default store.
_ENGINE: WorkflowEngine | None = None


def get_workflow_engine(context: ActionContext | None = None) -> WorkflowEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = WorkflowEngine()
    return _ENGINE


def set_workflow_engine(engine: WorkflowEngine | None) -> None:
    """Host/test injection point; ``None`` resets to the lazy default."""
    global _ENGINE
    _ENGINE = engine


def register(registry) -> None:
    registry.register(
        ActionSpec(
            action_id="workflow.validate",
            description="静态校验一个工作流定义（环/缺失依赖/未知动作/绑定），不执行。",
            handler=_validate,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            required_context=("catalog",),
            domain_tags=("workflow", "validate"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="workflow.run",
            output_schema={"type": "object", "properties": {"run_id": {"type": "string"}, "workflow_id": {"type": "string"}, "state": {"type": "string"}, "nodes": {"type": "object"}, "progress": {"type": "number"}}, "required": ["run_id", "state"]},
            description="执行一个工作流：在当前任务内同步驱动整个 DAG，节点逐一经 harness 守卫管线执行；宿主任务取消令牌会传播到引擎。",
            handler=_run,
            risk=ActionRisk.COMPUTE,
            category="background.compute",
            version="1.0",
            supports_cancel=True,
            required_context=("catalog",),
            resource_profile={"estimated_cpu_cores": 1.0, "estimated_ram_bytes": 0, "io_weight": 1.0},
            input_schema=_RUN_SCHEMA,
            domain_tags=("workflow", "run"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="workflow.resume",
            output_schema={"type": "object", "properties": {"run_id": {"type": "string"}, "state": {"type": "string"}, "nodes": {"type": "object"}, "progress": {"type": "number"}}, "required": ["run_id", "state"]},
            description="恢复一个中断的工作流：已完成节点保留，被打断的节点安全重跑。",
            handler=_resume,
            risk=ActionRisk.COMPUTE,
            category="background.compute",
            version="1.0",
            supports_cancel=True,
            required_context=("catalog",),
            input_schema={
                "type": "object",
                "properties": {"run_id": {"type": "string", "minLength": 1}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
            domain_tags=("workflow", "resume"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="workflow.cancel",
            output_schema={"type": "object", "properties": {"run_id": {"type": "string"}, "cancel_signalled": {"type": "boolean"}}, "required": ["run_id", "cancel_signalled"]},
            description="协作取消一个运行中的工作流（运行节点在安全点停止，待执行节点标记取消）。",
            handler=_cancel,
            risk=ActionRisk.COMPUTE,
            category="interactive.query",
            version="1.0",
            input_schema={
                "type": "object",
                "properties": {"run_id": {"type": "string", "minLength": 1}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
            domain_tags=("workflow", "cancel"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="workflow.describe",
            description="查看一个工作流运行的状态：节点状态、进度、receipt 摘要与依赖。",
            handler=_describe,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            input_schema={
                "type": "object",
                "properties": {"run_id": {"type": "string", "minLength": 1}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
            domain_tags=("workflow", "describe"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="workflow.describe_reproduction",
            description="说明如何在相同输入与版本下复现一次工作流运行（规范化参数、输入版本、环境身份）。",
            handler=_describe_reproduction,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            input_schema={
                "type": "object",
                "properties": {"run_id": {"type": "string", "minLength": 1}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
            domain_tags=("workflow", "reproduction"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="recipe.save",
            output_schema={"type": "object", "properties": {"recipe_id": {"type": "string"}, "path": {"type": "string"}, "source_run_id": {"type": "string"}}, "required": ["recipe_id", "path"]},
            description="把一个工作流运行保存为可移植 recipe（*.paleo-workflow.json），拒绝携带秘密/绝对路径/代码。",
            handler=_recipe_save,
            risk=ActionRisk.WRITE,
            category="background.compute",
            version="1.0",
            side_effect_notes="writes a recipe file into project-managed workflow storage",
            input_schema={
                "type": "object",
                "properties": {"run_id": {"type": "string", "minLength": 1}},
                "required": ["run_id"],
                "additionalProperties": False,
            },
            domain_tags=("recipe", "save"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="recipe.load",
            description="读取一个 recipe 文件（结构安全门：秘密/绝对路径/SQL/代码一律拒绝）。",
            handler=_recipe_load,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1}},
                "required": ["path"],
                "additionalProperties": False,
            },
            domain_tags=("recipe", "load"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="recipe.clone",
            output_schema={"type": "object", "properties": {"recipe_id": {"type": "string"}, "path": {"type": "string"}, "cloned_from": {"type": "string"}}, "required": ["recipe_id", "path"]},
            description="克隆一个 recipe（新身份、可编辑副本）。",
            handler=_recipe_clone,
            risk=ActionRisk.COMPUTE,
            category="interactive.query",
            version="1.0",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "minLength": 1}},
                "required": ["path"],
                "additionalProperties": False,
            },
            domain_tags=("recipe", "clone"),
        )
    )


# --------------------------------------------------------------- helpers --


def _engine(context: ActionContext) -> WorkflowEngine:
    """The shared engine. The store stays UNGLOBAL: without an explicit
    test/host injection it resolves per session (``store_for(context)``),
    so each project's runs land in that project's own artifacts tree."""
    return get_workflow_engine(context)


def _store_root(context: ActionContext):
    from paleo_workbench.workflow.dag.store import default_store_root

    return default_store_root(context)


def _probe(context: ActionContext):
    """Project identity probe: the live document the host injected."""
    return lambda: context.project


def _run_summary(run: Any) -> dict[str, Any]:
    labels = {n.node_id: (n.description or n.node_id) for n in run.workflow.nodes}
    return {
        "run_id": run.run_id,
        "workflow_id": run.workflow.workflow_id,
        "name": run.workflow.name,
        "state": run.state.value,
        "nodes": {
            node_id: {
                "label": labels.get(node_id, node_id),
                "state": nr.state.value,
                "from_cache": nr.from_cache,
                "attempt": nr.attempt,
                "error": nr.error,
                "skip_reason": nr.skip_reason,
                "receipt_status": (nr.receipt or {}).get("status"),
            }
            for node_id, nr in run.node_runs.items()
        },
        "progress": _progress(run),
    }


def _progress(run: Any) -> float:
    from paleo_workbench.workflow.dag.model import NodeState, TERMINAL_NODE_STATES

    total = len(run.node_runs)
    if not total:
        return 0.0
    terminal = sum(
        1
        for nr in run.node_runs.values()
        if nr.state in TERMINAL_NODE_STATES
    )
    return round(terminal / total, 3)


# --------------------------------------------------------------- handlers --


def _validate(context: ActionContext, parameters: dict) -> dict:
    engine = _engine(context)
    spec = _spec_from_recipe_param(context, parameters)
    from paleo_workbench.workflow.dag import validate_workflow_spec

    problems = validate_workflow_spec(spec, engine.registry)
    return {"workflow_id": spec.workflow_id, "valid": not problems, "problems": problems}


def _spec_from_recipe_param(context: ActionContext, parameters: dict) -> WorkflowSpec:
    path = parameters.get("recipe_path")
    if path:
        return load_recipe(path).workflow
    inline = parameters.get("workflow")
    if isinstance(inline, dict):
        return WorkflowSpec.from_dict(inline)
    raise LookupError("workflow.run needs 'recipe_path' or an inline 'workflow' definition")


_RUN_SCHEMA = {
    "type": "object",
    "properties": {
        "recipe_path": {"type": "string"},
        "workflow": {"type": "object"},
        "slot_values": {"type": "object"},
        "use_cache": {
            "type": "boolean",
            "description": "允许复用此前确定性执行（默认 true；false 强制全部重跑）",
        },
    },
    "additionalProperties": False,
}


def _progress_streamer(context: ActionContext):
    """Stream engine node updates onto the session progress surface (H11).

    The Task Center / agent panel receives (ratio, "当前节点") updates
    through the action context — never through widgets or engine internals.
    """
    def on_update(live_run) -> None:
        if context.progress is None:
            return
        from paleo_workbench.workflow.dag.plan_view import WorkflowPlanView

        view = WorkflowPlanView.from_run(live_run)
        current = view.current_node()
        message = f"{view.name} · {current}" if current else view.state_label()
        try:
            context.progress(view.progress, message)
        except Exception:
            pass  # progress must never kill the run

    return on_update


def _run(context: ActionContext, parameters: dict) -> dict:
    engine = _engine(context)
    spec = _spec_from_recipe_param(context, parameters)
    run = engine.create_run(
        spec, slot_values=dict(parameters.get("slot_values") or {}), context=context
    )
    done = engine.run(
        run.run_id,
        context=context,
        project_probe=_probe(context),
        on_update=_progress_streamer(context),
        use_cache=bool(parameters.get("use_cache", True)),
        external_cancel=context.cancel,
    )
    return _run_summary(done)


def _resume(context: ActionContext, parameters: dict) -> dict:
    engine = _engine(context)
    done = engine.resume(
        parameters["run_id"],
        context=context,
        project_probe=_probe(context),
        on_update=_progress_streamer(context),
        external_cancel=context.cancel,
    )
    return _run_summary(done)


def _cancel(context: ActionContext, parameters: dict) -> dict:
    engine = _engine(context)
    cancelled = engine.cancel(parameters["run_id"])
    return {"run_id": parameters["run_id"], "cancel_signalled": cancelled}


def _describe(context: ActionContext, parameters: dict) -> dict:
    engine = _engine(context)
    run = engine.store_for(context).load(parameters["run_id"])
    summary = _run_summary(run)
    summary["node_receipts"] = {
        node_id: (nr.receipt or {}) for node_id, nr in run.node_runs.items() if nr.receipt
    }
    return summary


def _describe_reproduction(context: ActionContext, parameters: dict) -> dict:
    engine = _engine(context)
    run = engine.store_for(context).load(parameters["run_id"])
    return describe_reproduction(run)


def _recipe_save(context: ActionContext, parameters: dict) -> dict:
    engine = _engine(context)
    run = engine.store_for(context).load(parameters["run_id"])
    recipe = recipe_from_run(run)
    path = save_recipe(
        recipe,
        _store_root(context) / f"{recipe.recipe_id}.paleo-workflow.json",
        registry=engine.registry,
    )
    return {"recipe_id": recipe.recipe_id, "path": str(path), "source_run_id": run.run_id}


def _contained_recipe_path(context: ActionContext, raw: str) -> str:
    """Harness path boundary: recipe files load only from the project's
    managed workflow store (or its subtree). Anything else is refused —
    an agent never gets an arbitrary-path file probe."""
    from pathlib import Path

    root = Path(_store_root(context)).resolve()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if root != candidate and root not in candidate.parents:
        raise PermissionError(
            f"recipe path {raw!r} is outside the project workflow store"
        )
    return str(candidate)


def _recipe_load(context: ActionContext, parameters: dict) -> dict:
    path = _contained_recipe_path(context, parameters["path"])
    recipe = load_recipe(path)
    return inspect_recipe(recipe)


def _recipe_clone(context: ActionContext, parameters: dict) -> dict:
    recipe = load_recipe(_contained_recipe_path(context, parameters["path"]))
    clone = clone_recipe(recipe)
    engine = _engine(context)
    path = save_recipe(
        clone,
        _store_root(context) / f"{clone.recipe_id}.paleo-workflow.json",
        registry=engine.registry,
    )
    return {"recipe_id": clone.recipe_id, "path": str(path), "cloned_from": recipe.recipe_id}
