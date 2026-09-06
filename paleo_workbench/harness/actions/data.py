"""Data-domain actions (Harness 2.0, H8): catalog search/describe/lineage/
verify over the injected CatalogPort. READ-only — the catalog is queried
through its port, never opened directly.
"""
from __future__ import annotations

from typing import Any

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.spec import ActionRisk, ActionSpec


def register(registry) -> None:
    registry.register(
        ActionSpec(
            action_id="data.search",
            description="按名称/类型/标签搜索目录中的数据资产（真实 catalog 查询，过滤条件始终生效）。",
            handler=_search,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 0.3, "estimated_ram_bytes": 0, "io_weight": 0.3},
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "type": {"type": "string"},
                    "tag": {"type": "string"},
                    "stage": {"type": "string", "enum": ["raw", "derived", "intermediate", "output"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
                },
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "versions": {"type": "array"},
                    "filters_applied": {"type": "object"},
                },
                "required": ["count", "versions", "filters_applied"],
            },
            domain_tags=("data", "search"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="data.describe_version",
            description="描述一个目录数据版本的全部元数据（asset、checksum、来源 run、标签）。",
            handler=_describe_version,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 0.3, "estimated_ram_bytes": 0, "io_weight": 0.2},
            required_context=("catalog",),
            input_schema={
                "type": "object",
                "properties": {"version_id": {"type": "string", "minLength": 1}},
                "required": ["version_id"],
                "additionalProperties": False,
            },
            domain_tags=("data", "describe"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="data.lineage",
            description="查询数据版本的血缘（上游祖先或下游后代），引用目录权威 lineage。",
            handler=_lineage,
            risk=ActionRisk.READ,
            category="interactive.query",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 0.3, "estimated_ram_bytes": 0, "io_weight": 0.3},
            required_context=("catalog",),
            input_schema={
                "type": "object",
                "properties": {
                    "version_id": {"type": "string", "minLength": 1},
                    "direction": {"type": "string", "enum": ["ancestors", "descendants"]},
                },
                "required": ["version_id"],
                "additionalProperties": False,
            },
            domain_tags=("data", "lineage"),
        )
    )
    registry.register(
        ActionSpec(
            action_id="data.verify",
            description="校验数据版本完整性（checksum 实读核对；结果如实返回，从不覆写 checksum）。",
            handler=_verify,
            risk=ActionRisk.READ,
            category="background.compute",
            version="1.0",
            resource_profile={"estimated_cpu_cores": 0.5, "estimated_ram_bytes": 0, "io_weight": 1.5},
            required_context=("catalog",),
            input_schema={
                "type": "object",
                "properties": {"version_id": {"type": "string", "minLength": 1}},
                "required": ["version_id"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "version_id": {"type": "string"},
                    "integrity": {"type": "string"},
                },
                "required": ["version_id", "integrity"],
            },
            domain_tags=("data", "integrity"),
        )
    )


def _catalog(context: ActionContext):
    catalog = context.require("catalog")
    return catalog


def _search(context: ActionContext, parameters: dict) -> dict:
    catalog = _catalog(context)
    text = parameters.get("text")
    type_filter = parameters.get("type")
    tag = parameters.get("tag")
    stage = parameters.get("stage")
    limit = int(parameters.get("limit", 500))
    filters_applied = {
        "text": bool(text),
        "type": bool(type_filter),
        "tag": bool(tag),
        "stage": bool(stage),
    }

    search_assets = getattr(catalog, "search_assets", None)
    if callable(search_assets):
        results = search_assets(
            text=text, type=type_filter, tag=tag, stage=stage, limit=limit
        )
        results = list(results or [])
    else:
        # Honest degrade: the port surface is narrower than the search here
        # declares, so the filters that cannot run server-side are applied
        # locally and REPORTED — silent filtering loss is a fake result.
        results = list(catalog.list_versions(stage=stage) or [])
        if text:
            needle = text.lower()
            results = [v for v in results if needle in (getattr(v, "name", "") or "").lower()]
        if type_filter:
            results = [v for v in results if (getattr(v, "kind", "") or getattr(v, "format", "")) == type_filter]
        if tag:
            results = [v for v in results if tag in (getattr(v, "tags", []) or [])]
        results = results[:limit]
    versions = [_version_brief(v) for v in results]
    return {
        "count": len(versions),
        "versions": versions,
        "filters_applied": filters_applied,
    }


def _describe_version(context: ActionContext, parameters: dict) -> dict:
    catalog = _catalog(context)
    version_id = parameters["version_id"]
    ref = catalog.resolve_version(version_id)
    if ref is None:
        raise LookupError(f"catalog has no version {version_id!r}")
    run = None
    run_id = getattr(ref, "producing_run_id", None)
    if run_id and getattr(catalog, "resolve_run", None):
        run = catalog.resolve_run(run_id)
    brief = _version_brief(ref)
    brief["producing_run"] = (
        {
            "run_id": run_id,
            "operation": getattr(run, "operation", None),
            "status": getattr(run, "status", None),
            "parameters": getattr(run, "parameters", None),
            "generator_version": getattr(run, "generator_version", None),
        }
        if run is not None
        else None
    )
    return brief


def _lineage(context: ActionContext, parameters: dict) -> dict:
    catalog = _catalog(context)
    version_id = parameters["version_id"]
    direction = parameters.get("direction", "ancestors")
    edges = catalog.query_lineage(version_id, direction=direction)
    items = []
    for edge in edges or []:
        items.append(
            {
                "source_version_id": getattr(edge, "source_version_id", None),
                "target_version_id": getattr(edge, "target_version_id", None),
                "run_id": getattr(edge, "run_id", None),
            }
        )
    return {"version_id": version_id, "direction": direction, "edges": items, "count": len(items)}


def _verify(context: ActionContext, parameters: dict) -> dict:
    catalog = _catalog(context)
    version_id = parameters["version_id"]
    if catalog.resolve_version(version_id) is None:
        raise LookupError(f"catalog has no version {version_id!r}")
    status = catalog.verify_integrity(version_id)
    integrity = getattr(status, "value", None) or str(status)
    return {"version_id": version_id, "integrity": integrity.lower()}


def _version_brief(version: Any) -> dict[str, Any]:
    to_dict = getattr(version, "to_dict", None)
    if callable(to_dict):
        try:
            data = to_dict()
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {
        "version_id": getattr(version, "version_id", None),
        "asset_id": getattr(version, "asset_id", None),
        "name": getattr(version, "name", None),
        "stage": getattr(getattr(version, "stage", None), "value", None) or getattr(version, "stage", None),
        "checksum": getattr(version, "checksum", None),
        "kind": getattr(version, "kind", None),
    }
