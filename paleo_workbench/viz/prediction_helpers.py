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
    # Early online runs stored every per-depth API label as ``depth ± 0.5m``.
    # At normal 0.125m sampling those bands overlap eight-fold and whichever
    # interval paints last visually wins.  Reconstruct adjacent sample cells
    # for display without mutating the persisted prediction result.
    items = normalize_sampled_prediction_regions(
        items, minimum_depth=float(top), maximum_depth=float(bottom)
    )
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


def normalize_sampled_prediction_regions(
    regions: list[dict[str, Any]] | None,
    *,
    minimum_depth: float | None = None,
    maximum_depth: float | None = None,
    force: bool = False,
    depth_key: str = "depth",
) -> list[dict[str, Any]]:
    """Convert overlapping point predictions into contiguous depth cells.

    Remote inference returns one label per sampled depth.  Interval renderers
    need cell bounds instead, so adjacent boundaries are the midpoints between
    sample depths.  ``force`` handles fresh API records carrying a depth field;
    otherwise only legacy ``inference_api_*`` regions that actually overlap
    are normalized.  Explicit user-defined regions are never rewritten.
    """
    source = [dict(item) for item in (regions or []) if isinstance(item, dict)]
    if len(source) < 2:
        if force and len(source) == 1:
            center = _prediction_sample_center(source[0], depth_key=depth_key)
            if center is not None:
                source[0]["top"] = center - 0.5
                source[0]["bottom"] = center + 0.5
        return source
    if not force and not all(
        str(item.get("region_id") or "").startswith("inference_api_")
        for item in source
    ):
        return source

    samples: list[tuple[float, int, dict[str, Any]]] = []
    for index, item in enumerate(source):
        center = _prediction_sample_center(item, depth_key=depth_key)
        if center is None:
            return source
        samples.append((center, index, item))
    samples.sort(key=lambda entry: (entry[0], entry[1]))
    if any(next_center <= center for (center, _, _), (next_center, _, _) in zip(samples, samples[1:])):
        return source

    if not force and not any(
        _interval_bounds(item) is not None
        and _interval_bounds(next_item) is not None
        and _interval_bounds(item)[1] > _interval_bounds(next_item)[0]
        for (_center, _index, item), (_next_center, _next_index, next_item) in zip(
            samples, samples[1:]
        )
    ):
        return source

    normalized: list[dict[str, Any]] = []
    for position, (center, _index, item) in enumerate(samples):
        previous_center = samples[position - 1][0] if position else None
        next_center = samples[position + 1][0] if position + 1 < len(samples) else None
        if previous_center is None:
            assert next_center is not None
            interval_top = center - (next_center - center) / 2.0
        else:
            interval_top = (previous_center + center) / 2.0
        if next_center is None:
            assert previous_center is not None
            interval_bottom = center + (center - previous_center) / 2.0
        else:
            interval_bottom = (center + next_center) / 2.0
        if minimum_depth is not None:
            interval_top = max(float(minimum_depth), interval_top)
        if maximum_depth is not None:
            interval_bottom = min(float(maximum_depth), interval_bottom)
        if interval_bottom <= interval_top:
            return source
        normalized_item = dict(item)
        normalized_item["top"] = round(interval_top, 6)
        normalized_item["bottom"] = round(interval_bottom, 6)
        normalized.append(normalized_item)
    return normalized


def _prediction_sample_center(item: dict[str, Any], *, depth_key: str) -> float | None:
    try:
        if item.get(depth_key) is not None:
            return float(item[depth_key])
        bounds = _interval_bounds(item)
        if bounds is None:
            return None
        return (bounds[0] + bounds[1]) / 2.0
    except (TypeError, ValueError):
        return None


def _interval_bounds(item: dict[str, Any]) -> tuple[float, float] | None:
    try:
        return float(item["top"]), float(item["bottom"])
    except (KeyError, TypeError, ValueError):
        return None


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


def build_ai_prediction_tracks(well_log: Any, task: Any) -> list[Any]:
    """Build GeoViz's dedicated facies and confidence tracks for a prediction.

    GeoViz's historical well-log prediction screen presents the prediction in
    two explicit interval columns: facies labels and percentage confidence.
    The workbench keeps the result in ``PredictionTask`` rather than a
    spreadsheet, so this adapter converts the same normalized depth intervals
    into the native QPainter tracks at render time.
    """
    if well_log is None or task is None:
        return []
    regions = (getattr(task, "result_summary", None) or {}).get(
        "predicted_regions"
    ) or []
    if not regions:
        return []

    top = float(getattr(well_log, "top_depth", 0.0) or 0.0)
    bottom = float(getattr(well_log, "bottom_depth", 0.0) or 0.0)
    intervals = regions_to_depth_intervals(regions, top=top, bottom=bottom)
    if not intervals:
        return []

    # Facies is categorical (stable style + project-owned texture), while
    # confidence is continuous (a sequential 0–1 heatmap).  Do not send both
    # through generic IntervalTrack: it cycles colours for arbitrary text.
    from geoviz import IntervalItem
    from paleo_workbench.viz.prediction_tracks import (
        ConfidenceHeatmapTrack,
        FaciesTextureTrack,
    )

    facies_items = [
        IntervalItem(top=item["top"], bottom=item["bottom"], name=item["facies"])
        for item in intervals
    ]
    confidence_items = []
    for item in intervals:
        probability = float(item.get("probability", 0.0) or 0.0)
        label = f"{probability:.0%}" if 0.0 <= probability <= 1.0 else str(probability)
        confidence_items.append(
            IntervalItem(top=item["top"], bottom=item["bottom"], name=label)
        )

    tracks = [
        FaciesTextureTrack(facies_items),
        ConfidenceHeatmapTrack(
            confidence_items,
            [float(item.get("probability", 0.0) or 0.0) for item in intervals],
        ),
    ]
    for track in tracks:
        track.set_depth_range(top, bottom)
    return tracks


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
