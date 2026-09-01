"""Well-domain harness actions (P2-C).

READ/COMPUTE risk. Well data loads through the production loader
(:func:`paleo_workbench.viz.well_log_load.load_well_log_from_path`, bounded
LRU cache + native LAS parser hook). ``well.create_display`` produces a
display *document* (pure data: tracks, curves, scale, template binding) —
the agent never drives widgets; the UI may render the document later.
"""
from __future__ import annotations

from typing import Any

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.spec import ActionRisk, ActionSpec

DEFAULT_TEMPLATE = {
    "template_id": "standard-3-track",
    "name": "标准三轨",
    "scale": {"top": 0.0, "bottom": None, "units": "m"},  # bottom None = full hole
    "tracks": [],
}


def register(registry) -> None:
    registry.register(
        ActionSpec(
            action_id="well.list",
            description="列出工区井（含坐标/井名），可选仅激活井。",
            handler=_list,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.1},
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "only_active": {"type": "boolean"},
                    "include_reference": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="well.open",
            description="打开一口井的测井数据（解析 LAS/XML，结果进入会话上下文）。",
            handler=_open,
            risk=ActionRisk.COMPUTE,
            category="background.io",
            resource_profile={"estimated_cpu_cores": 1.0, "io_weight": 1.0},
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "well": {"type": "string", "description": "井名或井 id"},
                },
                "required": ["well"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="well.list_curves",
            description="列出已打开井的曲线（名称/单位/范围/深度段）。",
            handler=_list_curves,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.0},
            input_schema={
                "type": "object",
                "properties": {"well": {"type": "string", "description": "缺省为激活井"}},
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="well.create_display",
            description="为井构建显示文档（选定曲线 → 轨道布局 → 模板绑定），纯数据、可被 UI 渲染。",
            handler=_create_display,
            risk=ActionRisk.COMPUTE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 0.0},
            input_schema={
                "type": "object",
                "properties": {
                    "well": {"type": "string"},
                    "curves": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "depth_top": {"type": "number"},
                    "depth_bottom": {"type": "number"},
                },
                "required": ["curves"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="well.apply_template",
            description="将显示模板应用到已存在的井显示文档（轨道编组/可见性）。",
            handler=_apply_template,
            risk=ActionRisk.COMPUTE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.0},
            input_schema={
                "type": "object",
                "properties": {
                    "well": {"type": "string"},
                    "template_id": {"type": "string"},
                },
                "required": ["template_id"],
                "additionalProperties": False,
            },
        )
    )


# ------------------------------------------------------------- helpers --
def _well_entity(context: ActionContext, name_or_id: str) -> Any:
    from paleo_workbench.project.domain import resolve_well

    well = None
    if name_or_id:
        outcome = resolve_well(context.project, name=name_or_id, well_id=name_or_id)
        if getattr(outcome, "matched", False) and getattr(outcome, "well_id", None):
            for candidate in context.project.wells:
                if candidate.id == outcome.well_id:
                    well = candidate
                    break
        if well is None:
            for candidate in context.project.wells:
                if name_or_id in candidate.match_keys() or name_or_id == candidate.id:
                    well = candidate
                    break
    if well is None:
        raise LookupError(f"well {name_or_id!r} not found in project")
    return well


def _well_resource_path(context: ActionContext, well: Any) -> str | None:
    from pathlib import Path

    def resolved(resource_path: Any) -> str:
        path = Path(str(resource_path)).expanduser()
        if path.is_absolute():
            return str(path)
        project_file = Path(context.project_path).expanduser() if context.project_path else None
        root_value = getattr(getattr(context.project, "meta", None), "project_root", "")
        root = Path(str(root_value or ".")).expanduser()
        if not root.is_absolute() and project_file is not None:
            root = project_file.parent / root
        elif not root.is_absolute():
            root = Path.cwd() / root
        return str((root / path).resolve())

    name = well.name
    for resource in getattr(context.project, "resources", []) or []:
        if getattr(resource, "type", "") != "well_log":
            continue
        if Path(str(resource.path)).stem.upper() == name.upper():
            return resolved(resource.path)
    # Fall back to any resource whose name contains the well name.
    for resource in getattr(context.project, "resources", []) or []:
        if getattr(resource, "type", "") == "well_log" and name.upper() in str(resource.name).upper():
            return resolved(resource.path)
    return None


# ------------------------------------------------------------- handlers --
def _list(context: ActionContext, parameters: dict) -> dict:
    include_reference = bool(parameters.get("include_reference", True))
    wells = []
    for well in context.project.wells:
        from paleo_workbench.project.domain import is_reference_well

        if not include_reference and is_reference_well(well):
            continue
        wells.append(
            {
                "well_id": well.id,
                "name": well.name,
                "x": well.project_x if well.project_x is not None else well.surface_x,
                "y": well.project_y if well.project_y is not None else well.surface_y,
                "crs": well.source_crs or "",
                "kb": well.kb,
                "td": well.td,
                "active": well.id == (context.active_well_id or context.selection.active_well_id),
            }
        )
    if parameters.get("only_active"):
        wells = [w for w in wells if w["active"]]
    return {"wells": wells, "count": len(wells)}


def _open(context: ActionContext, parameters: dict) -> dict:
    well = _well_entity(context, parameters["well"])
    path = _well_resource_path(context, well)
    if path is None:
        raise LookupError(f"no well-log file linked to well {well.name!r}")
    from paleo_workbench.viz.well_log_load import load_well_log_from_path

    data = load_well_log_from_path(path)
    if data is None:
        raise LookupError(f"could not parse well log {path!r}")
    context.well_logs[well.id] = data
    if context.active_well_id is None:
        context.active_well_id = well.id
    return {
        "well_id": well.id,
        "name": well.name,
        "path": path,
        "top_depth": data.top_depth,
        "bottom_depth": data.bottom_depth,
        "curve_count": len(data.curves),
        "curves": [c.name for c in data.curves],
    }


def _loaded_log(context: ActionContext, name: str | None) -> tuple[str, Any]:
    target = name or context.active_well_id or context.selection.active_well_id
    if target is None:
        if len(context.well_logs) == 1:
            target = next(iter(context.well_logs))
        else:
            raise LookupError("no well opened (call well.open first or set active_well_id)")
    if target in context.well_logs:
        return target, context.well_logs[target]
    well = _well_entity(context, target)
    if well.id in context.well_logs:
        return well.id, context.well_logs[well.id]
    raise LookupError(f"well {target!r} is not opened")


def _list_curves(context: ActionContext, parameters: dict) -> dict:
    well_id, data = _loaded_log(context, parameters.get("well"))
    curves = []
    for curve in data.curves:
        values = curve.values or []
        finite = [v for v in values if v == v]  # NaN != NaN
        curves.append(
            {
                "name": curve.name,
                "unit": curve.unit,
                "samples": len(values),
                "min": min(finite) if finite else None,
                "max": max(finite) if finite else None,
                "depth_min": min(curve.depth) if curve.depth else None,
                "depth_max": max(curve.depth) if curve.depth else None,
            }
        )
    return {"well_id": well_id, "curves": curves}


def _create_display(context: ActionContext, parameters: dict) -> dict:
    name = parameters.get("well")
    well_id, data = _loaded_log(context, name)
    requested = set(parameters["curves"])
    available = {c.name.upper(): c for c in data.curves}
    missing = [c for c in requested if c.upper() not in available]
    chosen = [available[c.upper()] for c in requested if c.upper() in available]
    if not chosen:
        raise LookupError(f"none of {sorted(requested)} exist; available: {sorted(available)}")
    from paleo_workbench.viz.well_log_track_layout import (
        curve_keys_for,
        default_curve_track_layout,
    )

    keys = curve_keys_for(chosen)
    layout = default_curve_track_layout(chosen)
    top = parameters.get("depth_top", data.top_depth)
    bottom = parameters.get("depth_bottom", data.bottom_depth)
    # Tracks: one DEPTH track + one per curve group (production layout keys
    # are stable "curve:<i>:<name>" identities, never raw names).
    tracks: list[dict] = [{"track_id": "track-0", "header": "DEPTH", "curves": []}]
    seen_groups: list[tuple[str, ...]] = []
    for key, curve in zip(keys, chosen):
        group = layout.group_for(key)
        if group not in seen_groups:
            seen_groups.append(group)
            tracks.append(
                {
                    "track_id": f"track-{len(tracks)}",
                    "header": curve.name,
                    "curves": [],
                }
            )
        tracks[-1]["curves"].append(
            {
                "name": curve.name,
                "unit": curve.unit,
                "display_range": list(curve.display_range),
                "color": curve.color,
                "visible": key in layout.visible_curve_keys,
            }
        )
    warnings = [f"curves not found: {missing}"] if missing else []
    display = {
        "display_id": f"well-display-{well_id[:8]}",
        "well_id": well_id,
        "well_name": data.well_name,
        "depth_range": [float(top), float(bottom)],
        "depth_unit": "m",
        "tracks": tracks,
        "template": dict(DEFAULT_TEMPLATE),
        "warnings": warnings,
    }
    context.well_displays[well_id] = display
    return {"display": display, "warnings": warnings, "well_id": well_id}


def _apply_template(context: ActionContext, parameters: dict) -> dict:
    name = parameters.get("well")
    well_id, _data = _loaded_log(context, name)
    display = context.well_displays.get(well_id)
    if display is None:
        raise LookupError(f"no display for well {well_id!r} (call well.create_display first)")
    template_id = parameters["template_id"]
    display["template"] = {
        **DEFAULT_TEMPLATE,
        "template_id": template_id,
        "name": template_id,
    }
    return {"well_id": well_id, "template": display["template"]}
