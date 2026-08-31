"""Workspace-domain harness actions (P2-C).

All READ-risk; they expose the catalog/workspace without ever touching
SQLite or the filesystem directly.
"""
from __future__ import annotations

from typing import Any

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.spec import ActionRisk, ActionSpec


def _catalog(context: ActionContext) -> Any:
    return context.require("catalog")


def register(registry) -> None:
    registry.register(
        ActionSpec(
            action_id="workspace.list_assets",
            description="列出当前工作区数据目录资产（可按 stage/type 过滤）。",
            handler=_list_assets,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.5},
            input_schema={
                "type": "object",
                "properties": {
                    "stage": {"type": "string", "enum": ["raw", "derived", "intermediate", "output"]},
                    "type": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
                },
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="workspace.search",
            description="按名称/标签/类型检索工作区资产。",
            handler=_search,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.5},
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "type": {"type": "string"},
                    "tag": {"type": "string"},
                },
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="workspace.get_lineage",
            description="查询某数据版本的血缘（ancestors=输入来源 / descendants=下游产品）。",
            handler=_lineage,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.5},
            input_schema={
                "type": "object",
                "properties": {
                    "version_id": {"type": "string"},
                    "direction": {"type": "string", "enum": ["ancestors", "descendants"]},
                },
                "required": ["version_id"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="workspace.get_versions",
            description="列出某资产的全部版本（不可变版本链）。",
            handler=_versions,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.5},
            input_schema={
                "type": "object",
                "properties": {"asset_id": {"type": "string"}},
                "required": ["asset_id"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="workspace.describe_context",
            description="读取当前会话上下文（工作区/选择/激活井/激活体/当前图），供 Agent 免检索复用。",
            handler=_describe,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.1, "io_weight": 0.0},
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )
    )


def _list_assets(context: ActionContext, parameters: dict) -> dict:
    catalog = _catalog(context)
    stage = parameters.get("stage")
    asset_type = parameters.get("type")
    limit = int(parameters.get("limit", 500))
    versions = catalog.list_versions(stage=stage) if stage else catalog.list_versions()
    rows = []
    for version in versions:
        if asset_type and (getattr(version, "kind", "") or "") != asset_type:
            continue
        rows.append(
            {
                "version_id": version.version_id,
                "asset_id": version.asset_id,
                "stage": getattr(version, "stage", ""),
                "name": getattr(version, "name", ""),
                "path": getattr(version, "path", ""),
                "format": getattr(version, "format", ""),
            }
        )
        if len(rows) >= limit:
            break
    return {"assets": rows, "count": len(rows)}


def _search(context: ActionContext, parameters: dict) -> dict:
    catalog = _catalog(context)
    search = getattr(catalog, "search_assets", None)
    if callable(search):
        assets = search(
            text=parameters.get("text") or None,
            type=parameters.get("type") or None,
            tag=parameters.get("tag") or None,
        )
    else:  # CatalogPort fallback: filter the version list
        text = (parameters.get("text") or "").lower()
        assets = []
        for version in catalog.list_versions():
            name = (getattr(version, "name", "") or "").lower()
            if text and text not in name:
                continue
            assets.append(version)
    return {
        "results": [
            {
                "asset_id": getattr(a, "asset_id", getattr(a, "id", "")),
                "name": getattr(a, "name", ""),
                "current_version_id": getattr(a, "current_version_id", None),
            }
            for a in assets
        ],
        "count": len(assets),
    }


def _lineage(context: ActionContext, parameters: dict) -> dict:
    catalog = _catalog(context)
    direction = parameters.get("direction", "ancestors")
    versions = catalog.query_lineage(parameters["version_id"], direction=direction)
    return {
        "direction": direction,
        "versions": [
            {
                "version_id": v.version_id,
                "asset_id": v.asset_id,
                "stage": getattr(v, "stage", ""),
                "name": getattr(v, "name", ""),
            }
            for v in versions
        ],
    }


def _versions(context: ActionContext, parameters: dict) -> dict:
    catalog = _catalog(context)
    versions = catalog.list_versions(asset_id=parameters["asset_id"])
    return {
        "asset_id": parameters["asset_id"],
        "versions": [
            {
                "version_id": v.version_id,
                "stage": getattr(v, "stage", ""),
                "path": getattr(v, "path", ""),
                "producing_run_id": getattr(v, "producing_run_id", None),
            }
            for v in versions
        ],
    }


def _describe(context: ActionContext, parameters: dict) -> dict:
    return {"context": context.snapshot_description()}
