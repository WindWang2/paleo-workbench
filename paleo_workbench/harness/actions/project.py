"""Project-domain actions (Harness 2.0, H8): read-only inspection and
health reporting over the live ProjectDocument and the catalog.

Every handler maps a real production object — the project document the
host injected into the context and the catalog port. Nothing here opens
files or databases by itself.
"""
from __future__ import annotations

from typing import Any

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.spec import ActionRisk, ActionSpec

_NO_PARAMS = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}


def register(registry) -> None:
    registry.register(
        ActionSpec(
            action_id="project.inspect",
            description="查看当前工程的结构概览（井/地震/地层/解释/图件任务的计数与标识）。",
            handler=_inspect,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 0.2, "estimated_ram_bytes": 0, "io_weight": 0.1},
            required_context=("project",),
            domain_tags=("project", "inventory"),
            output_schema={
                "type": "object",
                "properties": {
                    "project_name": {"type": ["string", "null"]},
                    "counts": {"type": "object"},
                },
                "required": ["counts"],
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="project.health",
            description="体检当前工程：资源缺失、解释引用完整性、目录可达性等真实检查结果。",
            handler=_health,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 0.5, "estimated_ram_bytes": 0, "io_weight": 0.5},
            required_context=("project",),
            domain_tags=("project", "health"),
            verifier=_verify_health,
        )
    )


def _inspect(context: ActionContext, parameters: dict) -> dict:
    project = context.require("project")
    meta = getattr(project, "meta", None)
    wells = getattr(project, "wells", []) or []
    surveys = getattr(project, "seismic_surveys", []) or []
    return {
        "project_name": getattr(meta, "name", None),
        "schema_version": getattr(project, "schema_version", None),
        "counts": {
            "wells": len(wells),
            "seismic_surveys": len(surveys),
            "well_tables": len(getattr(project, "well_tables", []) or []),
            "factor_map_tasks": len(getattr(project, "factor_map_tasks", []) or []),
            "map_products": len(getattr(project, "map_products", []) or []),
            "contour_drafts": len(getattr(project, "contour_drafts", []) or []),
            "horizon_interpretations": len(getattr(project, "horizon_interpretations", []) or []),
            "fault_interpretations": len(getattr(project, "fault_interpretations", []) or []),
            "prediction_tasks": len(getattr(project, "prediction_tasks", []) or []),
            "resources": len(getattr(project, "resources", []) or []),
        },
    }


def _health(context: ActionContext, parameters: dict) -> dict:
    project = context.require("project")
    checks: list[dict[str, Any]] = []

    # Resource backing: project-declared resources whose files are gone.
    missing_resources = []
    from pathlib import Path

    for resource in getattr(project, "resources", []) or []:
        path = getattr(resource, "path", None)
        if path and not Path(path).exists():
            missing_resources.append(str(path))
    checks.append(
        {
            "check": "resource_backing",
            "ok": not missing_resources,
            "detail": missing_resources[:20],
        }
    )

    # Interpretation referential integrity: refs pointing at unknown wells.
    well_ids = {getattr(w, "id", None) or getattr(w, "name", None) for w in getattr(project, "wells", []) or []}
    dangling = []
    for ref in getattr(project, "horizon_interpretations", []) or []:
        for wid in [getattr(ref, "well_id", None)]:
            if wid and well_ids and wid not in well_ids:
                dangling.append(f"horizon:{getattr(ref, 'id', '?')}→{wid}")
    checks.append(
        {"check": "interpretation_refs", "ok": not dangling, "detail": dangling[:20]}
    )

    # Catalog reachability (absence is a degraded, honestly-reported state).
    catalog_ok = context.catalog is not None
    checks.append({"check": "catalog_available", "ok": catalog_ok, "detail": []})

    ok = all(c["ok"] for c in checks)
    return {"ok": ok, "checks": checks}


def _verify_health(payload: dict, parameters: dict, context: ActionContext) -> dict:
    """Custom verifier: a health report must actually carry checks."""
    checks = payload.get("checks")
    if not isinstance(checks, list) or not checks:
        return {"verdict": "fail", "reasons": ["health report carries no checks"]}
    return {"verdict": "pass", "reasons": []}
