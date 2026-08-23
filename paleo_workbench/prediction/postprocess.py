"""Deterministic post-processing for persisted online facies predictions.

The inference API returns one categorical prediction at each sampled depth.
Those samples are first normalized into non-overlapping cells, then this
module reduces only *adjacent* compatible cells.  Formation tops are hard
boundaries: a reduction must never bridge a stratigraphic unit.
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from paleo_workbench.resources.well_tops_parser import parse_well_tops


_EPSILON = 1e-6
_UNSPECIFIED_STRATUM = "未标定层位"


def postprocess_prediction_regions(
    regions: list[dict[str, Any]] | None,
    *,
    formation_boundaries: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Merge compatible adjacent prediction cells without crossing a top.

    Compatibility intentionally uses the same whole-percent precision shown by
    the confidence heatmap. Remote confidences are continuous floats, so
    requiring bitwise equality would almost never reduce a sampled result
    despite appearing identical to the operator. The persisted merged
    probability is the canonical displayed probability (for example, 53%
    becomes 0.53).

    Every supplied formation boundary splits a cell before the merge pass.
    This also protects against the uncommon case where a top falls inside a
    remote sample cell rather than exactly on its midpoint boundary.
    """
    normalized_boundaries = _normalize_boundaries(formation_boundaries)
    source = [
        dict(region)
        for region in (regions or [])
        if isinstance(region, dict) and _bounds(region) is not None
    ]
    source.sort(key=lambda item: (_bounds(item) or (math.inf, math.inf)))

    split: list[tuple[dict[str, Any], int, str]] = []
    for region in source:
        top, bottom = _bounds(region) or (0.0, 0.0)
        for segment_top, segment_bottom in _split_bounds(
            top, bottom, normalized_boundaries
        ):
            item = dict(region)
            item["top"] = round(segment_top, 6)
            item["bottom"] = round(segment_bottom, 6)
            layer_index, layer_name = _stratum_at(
                (segment_top + segment_bottom) / 2.0, normalized_boundaries
            )
            if normalized_boundaries:
                item["stratigraphic_unit"] = layer_name
            split.append((item, layer_index, layer_name))

    merged: list[tuple[dict[str, Any], int, str]] = []
    for item, layer_index, layer_name in split:
        probability = _display_probability(item.get("probability"))
        facies = str(item.get("facies") or "").strip()
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and facies
            and str(previous[0].get("facies") or "").strip() == facies
            and _display_probability(previous[0].get("probability")) == probability
            and previous[1] == layer_index
            and _touches(previous[0], item)
        ):
            previous[0]["bottom"] = item["bottom"]
            previous[0]["probability"] = probability
            previous[0]["merged_sample_count"] = int(
                previous[0].get("merged_sample_count", 1) or 1
            ) + int(item.get("merged_sample_count", 1) or 1)
            continue

        copied = dict(item)
        copied["probability"] = probability
        merged.append((copied, layer_index, layer_name))

    records: list[dict[str, Any]] = []
    for index, (item, _layer_index, _layer_name) in enumerate(merged, start=1):
        item["region_id"] = f"inference_api_post_{index}"
        records.append(item)
    return records, {
        "applied": True,
        "confidence_display_precision": "1%",
        "raw_region_count": len(source),
        "split_region_count": len(split),
        "postprocessed_region_count": len(records),
        "formation_boundary_count": len(normalized_boundaries),
    }


def resolve_formation_boundaries(
    well_name: str,
    *,
    well_log: Any = None,
    inputs: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve per-well formation tops from catalogued data and LAS metadata.

    Catalogued well_stratification inputs are the primary source because they
    describe project correlation tops. Embedded LAS formation intervals are
    added as a secondary source. A malformed optional stratification file
    never invalidates a successful remote inference; its diagnostic is saved
    with the post-processing metadata instead.
    """
    target = _well_key(well_name)
    boundaries: list[dict[str, Any]] = []
    diagnostics: list[str] = []

    for info in (inputs or {}).values():
        if str(info.get("asset_type") or "") != "well_stratification":
            continue
        path = Path(str(info.get("path") or ""))
        if not path.is_file():
            diagnostics.append(f"井分层文件不可读取: {info.get('name') or path.name}")
            continue
        try:
            rows = parse_well_tops(path)
        except Exception as exc:  # optional context must not discard a prediction
            diagnostics.append(
                f"井分层解析失败 {info.get('name') or path.name}: {exc.__class__.__name__}"
            )
            continue
        for row in rows:
            if _well_key(row.well_name) == target:
                boundaries.append(
                    {
                        "name": str(row.top_name or _UNSPECIFIED_STRATUM),
                        "depth": float(row.md),
                        "source": "well_stratification",
                    }
                )

    intervals = getattr(well_log, "intervals", None)
    formations = list(getattr(intervals, "formation", None) or [])
    for interval in formations:
        depth = _finite_number(getattr(interval, "top", None))
        if depth is not None:
            boundaries.append(
                {
                    "name": str(getattr(interval, "name", "") or _UNSPECIFIED_STRATUM),
                    "depth": depth,
                    "source": "las_formation",
                }
            )

    return _normalize_boundaries(boundaries), diagnostics


def _normalize_boundaries(
    boundaries: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    deduped: dict[tuple[float, str], dict[str, Any]] = {}
    for boundary in boundaries or []:
        if not isinstance(boundary, dict):
            continue
        depth = _finite_number(boundary.get("depth"))
        if depth is None:
            continue
        name = str(boundary.get("name") or _UNSPECIFIED_STRATUM).strip()
        key = (round(depth, 6), name)
        deduped.setdefault(
            key,
            {
                "name": name or _UNSPECIFIED_STRATUM,
                "depth": round(depth, 6),
                "source": str(boundary.get("source") or ""),
            },
        )
    # Multiple labels at exactly the same depth still mean one hard boundary;
    # preserve a deterministic label rather than creating zero-thickness units.
    by_depth: dict[float, dict[str, Any]] = {}
    for boundary in sorted(deduped.values(), key=lambda item: (item["depth"], item["name"])):
        by_depth.setdefault(float(boundary["depth"]), boundary)
    return list(by_depth.values())


def _split_bounds(
    top: float, bottom: float, boundaries: list[dict[str, Any]]
) -> list[tuple[float, float]]:
    cuts = [
        float(boundary["depth"])
        for boundary in boundaries
        if top + _EPSILON < float(boundary["depth"]) < bottom - _EPSILON
    ]
    points = [top, *cuts, bottom]
    return [
        (start, end)
        for start, end in zip(points, points[1:])
        if end - start > _EPSILON
    ]


def _stratum_at(
    depth: float, boundaries: list[dict[str, Any]]
) -> tuple[int, str]:
    index = 0
    name = _UNSPECIFIED_STRATUM
    for boundary in boundaries:
        if float(boundary["depth"]) > depth + _EPSILON:
            break
        index += 1
        name = str(boundary["name"])
    return index, name


def _display_probability(value: Any) -> float:
    probability = _finite_number(value)
    if probability is None:
        return 0.0
    probability = max(0.0, min(1.0, probability))
    # Keep the stored number in exact lockstep with the percentage rendered to
    # the operator. This reproduces Python percent-format rounding exactly.
    return int(f"{probability:.0%}"[:-1]) / 100.0


def _bounds(item: dict[str, Any]) -> tuple[float, float] | None:
    top = _finite_number(item.get("top"))
    bottom = _finite_number(item.get("bottom"))
    if top is None or bottom is None or bottom - top <= _EPSILON:
        return None
    return top, bottom


def _touches(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_bounds = _bounds(left)
    right_bounds = _bounds(right)
    return bool(
        left_bounds is not None
        and right_bounds is not None
        and abs(left_bounds[1] - right_bounds[0]) <= _EPSILON
    )


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _well_key(value: Any) -> str:
    name = Path(str(value or "")).stem.casefold()
    return re.sub(r"[^\w]", "", name, flags=re.UNICODE)


__all__ = [
    "postprocess_prediction_regions",
    "resolve_formation_boundaries",
]
