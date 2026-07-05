from __future__ import annotations

from typing import Any

from geoviz_well_log import CurveData, FaciesInterval, WellLogData


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
    regions = (field_value(task, "result_summary", {}) or {}).get("predicted_regions", [])
    if not regions:
        regions = [{"facies": "未分类", "probability": 0.0}]

    interval_height = 100.0 / len(regions)
    depths: list[float] = []
    values: list[float] = []
    facies_intervals: list[FaciesInterval] = []
    for index, region in enumerate(regions):
        top = round(index * interval_height, 3)
        bottom = round((index + 1) * interval_height, 3)
        probability = float(region.get("probability", 0.0))
        depths.append(round((top + bottom) / 2.0, 3))
        values.append(round(probability * 100.0, 1))
        facies_intervals.append(
            FaciesInterval(
                top=top,
                bottom=bottom,
                facies=str(region.get("facies") or "未分类"),
            )
        )

    return WellLogData(
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
        facies=facies_intervals,
    )
