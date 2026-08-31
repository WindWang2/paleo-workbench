"""Geology + workflow-domain harness actions (P2-C).

READ risk surface over project entities (horizons/faults/interpretations)
and the workflow dashboard. No mutations: interpretation creation stays a
UI-adjacent workflow (its lifecycle owns draft/version semantics); the
harness exposes reading until a guarded writer is justified.
"""
from __future__ import annotations

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.spec import ActionRisk, ActionSpec


def register(registry) -> None:
    registry.register(
        ActionSpec(
            action_id="geology.list_horizons",
            description="列出工区地层/层位框架（目标层、层序边界、适用井）。",
            handler=_list_horizons,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.0},
            required_context=("project",),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )
    )
    registry.register(
        ActionSpec(
            action_id="geology.list_faults",
            description="列出工区断层解释。",
            handler=_list_faults,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.0},
            required_context=("project",),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )
    )
    registry.register(
        ActionSpec(
            action_id="geology.create_interpretation",
            description="创建断层解释草稿并入库（真实 fault lifecycle：draft→项目引用→catalog 版本），带溯源。",
            handler=_create_fault_interpretation,
            risk=ActionRisk.WRITE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.5},
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "horizon": {"type": "string", "description": "关联层位"},
                    "crs": {"type": "string"},
                    "save": {"type": "boolean", "description": "是否写入项目文件（默认仅内存 draft+引用）"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="workflow.status",
            description="读取工作流仪表盘状态（各步骤完成度/证据）。",
            handler=_workflow_status,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.2},
            required_context=("project",),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )
    )


def _list_horizons(context: ActionContext, parameters: dict) -> dict:
    stratigraphy = getattr(context.project, "stratigraphy", None)
    horizons = list(getattr(stratigraphy, "sequence_boundaries", []) or [])
    return {
        "target_horizon": getattr(stratigraphy, "target_horizon", ""),
        "sequence_boundaries": horizons,
        "applicable_wells": list(getattr(stratigraphy, "applicable_wells", []) or []),
        "interpretations": [
            {
                "id": getattr(ref, "id", ""),
                "name": getattr(ref, "name", ""),
                "horizon": getattr(ref, "horizon", ""),
                "version": getattr(ref, "version_id", getattr(ref, "version", None)),
            }
            for ref in getattr(context.project, "horizon_interpretations", []) or []
        ],
    }


def _list_faults(context: ActionContext, parameters: dict) -> dict:
    faults = []
    for ref in getattr(context.project, "fault_interpretations", []) or []:
        faults.append(
            {
                "id": getattr(ref, "id", ""),
                "name": getattr(ref, "name", ""),
                "horizon": getattr(ref, "horizon", ""),
                "segments": len(getattr(ref, "segments", []) or []),
                "version": getattr(ref, "version_id", None),
            }
        )
    return {"faults": faults, "count": len(faults)}


def _create_fault_interpretation(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.fault_lifecycle import new_fault_draft, save_fault_draft

    draft = new_fault_draft(name=parameters["name"], crs=parameters.get("crs", ""))
    project_path = context.project_path or ""
    if parameters.get("save", False) and project_path:
        ref, message = save_fault_draft(
            draft, context.project, project_path, catalog=context.catalog
        )
        return {
            "saved": True,
            "interpretation_id": getattr(ref, "id", None),
            "version_id": getattr(ref, "version_id", None),
            "message": message,
            "trace_count": len(draft.traces),
        }
    # Session-scope draft: registered into the project document (WRITE
    # through the domain lifecycle), persistence stays on the project save
    # path exactly like the UI workflow.
    from paleo_workbench.project.models import FaultInterpretationRef

    ref = FaultInterpretationRef(
        name=draft.name,
        horizon=parameters.get("horizon", ""),
        version=getattr(draft, "version", None),
    )
    context.project.fault_interpretations.append(ref)
    return {
        "saved": False,
        "interpretation_id": getattr(ref, "id", None),
        "trace_count": len(draft.traces),
        "note": "session-scope draft; save=true persists with catalog provenance",
    }


def _workflow_status(context: ActionContext, parameters: dict) -> dict:
    try:
        from paleo_workbench.workflow.service import dashboard_state

        state = dashboard_state(context.project)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    if isinstance(state, dict):
        return {"dashboard": state}
    return {"dashboard": getattr(state, "to_dict", lambda: str(state))()}
