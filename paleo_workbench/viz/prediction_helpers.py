"""Visualization helpers shared by prediction pages and well-log views.

Moved here from the legacy workflow wrapper modules (audit #848) so the
paleo_workbench.workflow prediction wrappers can be removed while the still-used
viz utilities remain in the viz layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from geoviz import CurveData, WellLogData


# Simple facies → lithology heuristic for SVG pattern track
_FACIES_LITHOLOGY = {
    "砂": "砂岩",
    "泥": "泥岩",
    "三角洲": "砂岩",
    "河道": "砂岩",
    "分流间湾": "泥岩",
    "滨岸": "砂岩",
    "水下": "砂岩",
}


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


def lithology_name_for_facies(facies: str) -> str:
    text = str(facies or "")
    for key, litho in _FACIES_LITHOLOGY.items():
        if key in text:
            return litho
    return "未分类岩性"


def regions_to_depth_intervals(
    regions: list[dict[str, Any]] | None,
    *,
    top: float,
    bottom: float,
) -> list[dict[str, Any]]:
    """Map predicted_regions onto depth range.

    Prefer explicit ``top``/``bottom`` on each region (local LAS zones);
    otherwise split ``[top, bottom]`` evenly.
    """
    items = list(regions or [])
    if not items:
        items = [{"facies": "未分类", "probability": 0.0}]
    # If any region carries depth, use those; clamp into [top, bottom].
    if any("top" in r and "bottom" in r for r in items if isinstance(r, dict)):
        out: list[dict[str, Any]] = []
        for region in items:
            if not isinstance(region, dict):
                continue
            try:
                t = float(region.get("top", top))
                b = float(region.get("bottom", bottom))
            except (TypeError, ValueError):
                continue
            t = max(float(top), min(t, float(bottom)))
            b = max(float(top), min(b, float(bottom)))
            if b <= t:
                continue
            facies = str(region.get("facies") or "未分类")
            out.append(
                {
                    "top": round(t, 3),
                    "bottom": round(b, 3),
                    "facies": facies,
                    "lithology": lithology_name_for_facies(facies),
                    "probability": float(region.get("probability", 0.0) or 0.0),
                }
            )
        if out:
            return out
    span = max(float(bottom) - float(top), 1e-6)
    step = span / len(items)
    out = []
    for index, region in enumerate(items):
        t = round(float(top) + index * step, 3)
        b = round(float(top) + (index + 1) * step, 3)
        facies = str(region.get("facies") or "未分类")
        out.append(
            {
                "top": t,
                "bottom": b,
                "facies": facies,
                "lithology": lithology_name_for_facies(facies),
                "probability": float(region.get("probability", 0.0) or 0.0),
            }
        )
    return out


def merge_prediction_onto_well_log(well_log: Any, task: Any) -> Any:
    """Attach lithology + facies tracks from prediction regions onto real LAS data.

    Mutates a copy via model_copy when available; falls back to attribute set.
    """
    if well_log is None:
        return None
    regions = (getattr(task, "result_summary", None) or {}).get("predicted_regions") or []
    top = float(getattr(well_log, "top_depth", 0.0) or 0.0)
    bottom = float(getattr(well_log, "bottom_depth", 100.0) or 100.0)
    intervals = regions_to_depth_intervals(regions, top=top, bottom=bottom)

    try:
        from geoviz import (
            FaciesData,
            FaciesInterval,
            IntervalItem,
            LithologyInterval,
            WellIntervals,
        )
    except Exception:
        # Minimal duck-type when engine models are unavailable.
        litho = [
            {
                "top": i["top"],
                "bottom": i["bottom"],
                "lithology": i["lithology"],
            }
            for i in intervals
        ]
        if hasattr(well_log, "model_copy"):
            return well_log.model_copy(update={"lithology": litho})
        well_log.lithology = litho
        return well_log

    lithology = [
        LithologyInterval(
            top=i["top"],
            bottom=i["bottom"],
            lithology=i["lithology"],
            description=i["facies"],
        )
        for i in intervals
    ]
    phase = [
        IntervalItem(top=i["top"], bottom=i["bottom"], name=i["facies"]) for i in intervals
    ]
    existing = getattr(well_log, "intervals", None)
    if existing is None:
        well_intervals = WellIntervals(facies=FaciesData(phase=phase))
    else:
        facies = getattr(existing, "facies", None) or FaciesData()
        well_intervals = existing.model_copy(
            update={
                "facies": FaciesData(
                    phase=phase,
                    sub_phase=list(facies.sub_phase or []),
                    micro_phase=list(facies.micro_phase or []),
                )
            }
        )

    updates = {
        "lithology": lithology,
        "intervals": well_intervals,
        "facies": [
            FaciesInterval(top=i["top"], bottom=i["bottom"], facies=i["facies"])
            for i in intervals
        ],
    }
    if hasattr(well_log, "model_copy"):
        return well_log.model_copy(update=updates)
    for key, value in updates.items():
        setattr(well_log, key, value)
    return well_log


def well_log_data_from_prediction(task) -> WellLogData:
    """Build synthetic well + lithology/facies tracks from predicted_regions.

    Used when no LAS is bound. Real LAS path merges prediction onto loaded
    curves via ``merge_prediction_onto_well_log``.
    """
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
    return merge_prediction_onto_well_log(data, task)


def export_well_canvas(
    canvas: Any,
    output_path: Path | str,
    format_label: str = "PNG",
    *,
    project=None,
    source_task_ids: list[str] | None = None,
    linked_id: str = "well_log_canvas",
) -> Path:
    """Export WellLogCanvas via engine helpers (PNG/SVG/PDF).

    When ``project`` is given, the export is registered as an ExportArtifact +
    catalog OUTPUT DataVersion (closing the previous tracking gap where this
    path wrote a file with zero registration). ``source_task_ids`` should carry
    the active PredictionTask id for lineage.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    label = (format_label or "PNG").upper()
    if label == "PNG":
        from geoviz import export_png

        export_png(canvas, str(path))
    elif label == "SVG":
        from geoviz import export_svg

        export_svg(canvas, str(path))
    elif label == "PDF":
        from geoviz import export_pdf

        export_pdf(canvas, str(path))
    else:
        raise ValueError(f"不支持的测井导出格式: {label}")

    if project is not None:
        from paleo_workbench.project.artifacts import record_export

        record_export(
            project,
            linked_id=linked_id,
            output_path=str(path),
            fmt=label.lower(),
            source_task_ids=list(source_task_ids or []),
        )
    return path
