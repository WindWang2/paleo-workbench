"""Scientific harness actions (V6 §19).

Real scientific services exposed to the agent surface — every action is a
typed, honest wrapper over an existing production service (no new science,
no new authority): unit truth from :mod:`well_science`, method evaluation
from :mod:`interpolation_evaluation`, product description/publishing from
:mod:`map_product`. Unsupported science returns unavailable/degraded —
fabricated data is never an option.
"""

from __future__ import annotations

from typing import Any

from paleo_workbench.harness.context import ActionContext
from paleo_workbench.harness.spec import ActionRisk, ActionSpec


def register(registry) -> None:
    registry.register(
        ActionSpec(
            action_id="well.describe_units",
            description=(
                "报告已打开井的深度单位真值（m/ft/未声明），"
                "含 declared 标志 — 未知即未知，绝不猜米。"
            ),
            handler=_describe_units,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.1},
            input_schema={
                "type": "object",
                "properties": {
                    "well": {
                        "type": "string",
                        "description": "井名或井 id（省略=全部已打开井）",
                    },
                },
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="seismic.describe_calibration",
            description=(
                "报告井震时深标定状态：每口井的标定来源/范围，"
                "未标定的井明确列为 no_calibration（不猜测速度）。"
            ),
            handler=_describe_calibration,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.2, "io_weight": 0.1},
            required_context=("project",),
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        )
    )
    registry.register(
        ActionSpec(
            action_id="factor.evaluate_methods",
            description=(
                "同一因子样本上做空间 K 折交叉验证比较插值方法，"
                "返回带能力矩阵警示的推荐报告（忽略约束的方法不因指标好而被推荐）。"
            ),
            handler=_evaluate_methods,
            risk=ActionRisk.COMPUTE,
            category="background.compute",
            resource_profile={"estimated_cpu_cores": 1.5, "io_weight": 0.5},
            required_context=("project",),
            input_schema={
                "type": "object",
                "properties": {
                    "factor": {"type": "string", "description": "因子任务名或 id"},
                    "methods": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "参与比较的方法（UI 标签，如 克里金/IDW/约束IDW）",
                    },
                    "requested_constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "需要尊重的约束类型（boundary_mask/barrier/direction/anisotropy/trend）",
                    },
                    "k": {"type": "integer", "minimum": 2, "maximum": 10},
                },
                "required": ["factor"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="map.describe_product",
            description="描述一个成图产品：因子快照、血缘、QC 与新鲜度（缺失引用给出原因，不伪造）。",
            handler=_describe_product,
            risk=ActionRisk.READ,
            category="interactive.query",
            resource_profile={"estimated_cpu_cores": 0.3, "io_weight": 0.3},
            required_context=("project", "catalog"),
            input_schema={
                "type": "object",
                "properties": {"product": {"type": "string", "description": "产品 id 或名称"}},
                "required": ["product"],
                "additionalProperties": False,
            },
        )
    )
    registry.register(
        ActionSpec(
            action_id="map.publish",
            description=(
                "成图产品发布门禁：陈旧/被取代/QC 错误/CRS 未声明 → 拒绝；"
                "单位未声明/约束被忽略/缺不确定性 → 警告并记录（可拒绝）。"
            ),
            handler=_publish_product,
            risk=ActionRisk.WRITE,
            category="background.io",
            resource_profile={"estimated_cpu_cores": 0.5, "io_weight": 1.5},
            required_context=("project", "catalog"),
            input_schema={
                "type": "object",
                "properties": {
                    "product": {"type": "string"},
                    "export_path": {"type": ["string", "null"]},
                    "accept_warnings": {"type": "boolean"},
                },
                "required": ["product"],
                "additionalProperties": False,
            },
        )
    )


def _loaded_logs(context: ActionContext):
    return dict(getattr(context, "well_logs", None) or {})


def _describe_units(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.well_science import depth_unit_of

    logs = _loaded_logs(context)
    target = parameters.get("well")
    if target:
        logs = {
            key: value
            for key, value in logs.items()
            if target in (key, str(getattr(value, "well_name", "") or ""))
        }
        if not logs:
            return {"wells": [], "warning": f"未打开匹配的井 {target!r}"}
    wells = []
    for well_id, data in logs.items():
        info = depth_unit_of(data)
        wells.append(
            {
                "well_id": well_id,
                "well_name": str(getattr(data, "well_name", "") or ""),
                "depth_unit": info.unit,  # None = unknown, never a guess
                "declared": info.declared,
                "raw": info.raw,
            }
        )
    return {"wells": wells}


def _describe_calibration(context: ActionContext, parameters: dict) -> dict:
    project = context.project
    wells = []
    # The hub is not part of ActionContext today (review R2-P0: reading a
    # nonexistent attr fabricated no_calibration for every well). When a hub
    # has NOT been injected the honest answer is per-well UNKNOWN — never a
    # fabricated "no calibration" statement.
    hub = getattr(context, "coordinate_hub", None)
    calibrations = {}
    if hub is not None and hasattr(hub, "time_depth_calibration"):
        # public accessor only — never the hub's private dict
        for well in getattr(project, "wells", None) or []:
            cal = hub.time_depth_calibration(well.id)
            if cal is not None:
                calibrations[well.id] = cal
    for well in getattr(project, "wells", None) or []:
        entry = {
            "well_id": well.id,
            "well_name": well.name,
            "calibration": "unknown" if hub is None else "no_calibration",
        }
        cal = calibrations.get(well.id)
        if cal is not None:
            pairs = list(getattr(cal, "pairs", []) or [])
            entry.update(
                {
                    "calibration": str(getattr(cal, "provenance", "") or "declared"),
                    "md_range": [pairs[0][0], pairs[-1][0]] if pairs else None,
                    "twt_range_ms": [pairs[0][1], pairs[-1][1]] if pairs else None,
                    "policy": "interpolate inside range only; fail closed outside",
                }
            )
        wells.append(entry)
    return {
        "wells": wells,
        "hub_available": hub is not None,
        "policy": "time-depth conversion requires a calibration; velocity is never guessed",
    }


def _evaluate_methods(context: ActionContext, parameters: dict) -> dict:
    import numpy as np

    from paleo_workbench.workflow.interpolation_evaluation import (
        recommend_interpolation_methods,
    )

    project = context.project
    factor = str(parameters.get("factor", "")).strip()
    task = next(
        (t for t in project.factor_map_tasks if factor in (t.id, t.name)),
        None,
    )
    if task is None:
        return {"error": "not_found", "detail": f"因子任务 {factor!r} 不存在"}
    points = (task.parameters or {}).get("sample_points") or []
    if len(points) < 8:
        return {
            "error": "unavailable",
            "detail": f"样本点不足（{len(points)} < 8），交叉验证无法诚实运行",
        }
    methods = list(parameters.get("methods") or ["IDW", "克里金", "约束IDW"])

    def _run_fold_idw(train):
        from geoviz import interpolate_idw

        xs = np.array([p["x"] for p in train], dtype=float)
        ys = np.array([p["y"] for p in train], dtype=float)
        zs = np.array([p.get("value", p.get("z")) for p in train], dtype=float)
        pad = 0.05 * max(xs.ptp(), ys.ptp(), 1.0)
        gx = np.linspace(xs.min() - pad, xs.max() + pad, 48)
        gy = np.linspace(ys.min() - pad, ys.max() + pad, 48)
        grid = interpolate_idw(xs, ys, zs, gx, gy)
        return gx, gy, grid

    report = recommend_interpolation_methods(
        points,
        methods=methods,
        run_fold=_run_fold_idw,
        requested_constraints=parameters.get("requested_constraints"),
        k=int(parameters.get("k") or 4),
    )
    # Review R2-P1: ONE proxy fold engine cannot discriminate methods — the
    # per-method metrics are identical by construction. Demote the ranking
    # honestly; the capability warnings remain authoritative.
    report["factor"] = task.name
    report["fold_engine"] = "idw-proxy"
    report["recommended_method"] = None
    for entry in report.get("methods", []):
        entry["recommended"] = None
        entry["rationale"] = (
            "proxy fold engine (IDW) cannot discriminate methods — metrics "
            "are NOT a method comparison; only capability warnings are "
            "authoritative here"
        )
    return report


def _describe_product(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.map_product import describe_map_product, find_map_product

    project = context.project
    product = str(parameters.get("product", "")).strip()
    record = find_map_product(project, product)
    if record is None:
        return {"error": "not_found", "detail": f"产品 {product!r} 不存在"}
    catalog = getattr(context, "catalog", None)
    description = describe_map_product(record, project, catalog)
    return {"product": description}


def _publish_product(context: ActionContext, parameters: dict) -> dict:
    from paleo_workbench.workflow.map_product import find_map_product, publish_map_product

    project = context.project
    product = str(parameters.get("product", "")).strip()
    record = find_map_product(project, product)
    if record is None:
        return {"error": "not_found", "detail": f"产品 {product!r} 不存在"}
    try:
        report = publish_map_product(
            record,
            project,
            export_path=parameters.get("export_path"),
            accept_warnings=bool(parameters.get("accept_warnings", True)),
        )
    except ValueError as exc:
        return {"error": "refused", "detail": str(exc)}
    report["published"] = True
    return report
