from __future__ import annotations

from typing import Any

from geoviz import CurveData, WellLogData


def field_value(source: Any, name: str, default: Any = None) -> Any:
    if source is None:
        return default
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def active_prediction_task(prediction_tasks: list | tuple | None):
    if not prediction_tasks:
        return None
    return prediction_tasks[-1]


def well_log_data_from_prediction(task) -> WellLogData:
    """Build synthetic well + lithology/facies tracks from predicted_regions.

    Used when no LAS is bound. Real LAS path merges prediction onto loaded
    curves via ``merge_prediction_onto_well_log``.
    """
    # Deferred: viz → workflow cross-layer edge; keep lazy until P3+ re-layering.
    from paleo_workbench.workflow.well_log_prediction import regions_to_depth_intervals

    regions = (field_value(task, "result_summary", {}) or {}).get("predicted_regions", [])
    intervals = regions_to_depth_intervals(regions, top=0.0, bottom=100.0)

    depths = [round((i["top"] + i["bottom"]) / 2.0, 3) for i in intervals]
    values = [round(float(i["probability"]) * 100.0, 1) for i in intervals]

    data = WellLogData(
        well_name=field_value(task, "name", "") or "未命名预测任务",
        top_depth=0.0,
        bottom_depth=100.0,
        curves=[
            CurveData(
                name="预测概率",
                unit="%",
                depth=depths,
                values=values,
                display_range=(0.0, 100.0),
                color="#6f47cf",
            )
        ],
    )
    # Deferred: viz → workflow cross-layer edge; keep lazy until P3+ re-layering.
    from paleo_workbench.workflow.well_log_prediction import merge_prediction_onto_well_log

    return merge_prediction_onto_well_log(data, task)
