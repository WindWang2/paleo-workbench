"""Multi-well stratigraphic correlation helpers (CrossWell engine)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from paleo_workbench.pipeline.assets import WELL_KEY
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.project.paths import is_within_directory
from paleo_workbench.resources.well_tops_parser import parse_well_tops
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.workflow.well_log_prediction import merge_prediction_onto_well_log


def _resource_path(project: ProjectDocument, resource) -> Path:
    """Resolve a resource path, mirroring VizAdapter._absolute_path.

    Relative paths are resolved against ``project.meta.project_root``
    (joins are confined to the root; ``..`` escapes are not followed).
    """
    candidate = Path(resource.path).expanduser()
    if candidate.is_file() or candidate.is_absolute():
        return candidate
    root = str(getattr(project.meta, "project_root", "") or "").strip()
    if root and root not in {".", ".."}:
        root_path = Path(root).expanduser().resolve()
        joined = (root_path / candidate).resolve()
        if is_within_directory(joined, root_path):
            return joined
    return candidate


def list_well_log_resources(project: ProjectDocument) -> list[Any]:
    return sorted(
        (r for r in project.resources if r.type == "well_log"),
        key=lambda r: (r.name or "", r.id),
    )


def load_correlation_wells(
    project: ProjectDocument,
    *,
    resource_ids: list[str] | None = None,
    max_wells: int = 8,
    attach_prediction_facies: bool = True,
) -> tuple[list[Any], list[str], list[str]]:
    """Load WellLogData for correlation section.

    Returns (logs, names, warnings).
    """
    wells = list_well_log_resources(project)
    if resource_ids is not None:
        wanted = set(resource_ids)
        wells = [r for r in wells if r.id in wanted]
    wells = wells[: max(1, int(max_wells))]

    adapter = VizAdapter()
    logs: list[Any] = []
    names: list[str] = []
    warnings: list[str] = []
    task = project.prediction_tasks[-1] if project.prediction_tasks else None

    for resource in wells:
        ref = adapter.ref_from_resource(resource)
        if ref is None:
            warnings.append(f"跳过 {resource.name}: 不支持可视化")
            continue
        payload = adapter.resolve(ref, project)
        data = payload.well_log
        if data is None:
            warnings.append(
                f"跳过 {resource.name}: {payload.message or '无法加载 LAS'}"
            )
            continue
        if attach_prediction_facies and task is not None:
            data = merge_prediction_onto_well_log(data, task)
        logs.append(data)
        names.append(
            str(getattr(data, "well_name", "") or Path(resource.name).stem or resource.id)
        )
    return logs, names, warnings


def prediction_bound_well_ids(project: ProjectDocument) -> list[str]:
    if not project.prediction_tasks:
        return []
    task = project.prediction_tasks[-1]
    return list((task.input_refs or {}).get(WELL_KEY) or [])


def load_well_tops(project: ProjectDocument) -> tuple[dict[str, list[tuple[str, float]]], list[str]]:
    """Load 井分层 tops from well_stratification resources.

    Returns ({well_name: [(top_name, depth_md)] sorted by depth}, warnings).
    """
    tops_by_well: dict[str, list[tuple[str, float]]] = {}
    warnings: list[str] = []
    resources = [r for r in project.resources if r.type == "well_stratification"]
    for resource in resources:
        path = _resource_path(project, resource)
        if not path.is_file():
            warnings.append(f"分层文件不存在: {resource.name}")
            continue
        try:
            rows = parse_well_tops(path)
        except Exception as exc:
            warnings.append(f"分层解析失败 {resource.name}: {exc.__class__.__name__}")
            continue
        for row in rows:
            tops_by_well.setdefault(row.well_name, []).append((row.top_name, row.md))
    for well in tops_by_well:
        tops_by_well[well].sort(key=lambda t: t[1])
    return tops_by_well, warnings


def match_tops_to_wells(
    tops_by_well: dict[str, list[tuple[str, float]]],
    well_names: list[str],
) -> tuple[dict[str, list[tuple[str, float]]], list[str]]:
    """Match tops well names to section well names (exact, then case-insensitive).

    Returns ({section_well_name: tops}, unmatched_top_well_names).
    """
    lookup: dict[str, str] = {}
    for name in well_names:
        lookup[name] = name
        lookup.setdefault(name.upper(), name)
    matched: dict[str, list[tuple[str, float]]] = {}
    unmatched: list[str] = []
    for top_well, tops in tops_by_well.items():
        target = lookup.get(top_well) or lookup.get(top_well.upper())
        if target is None:
            unmatched.append(top_well)
        else:
            matched[target] = tops
    return matched, unmatched


def tops_to_intervals(tops: list[tuple[str, float]]) -> list[Any]:
    """Convert [(name, depth)] tops into IntervalItems for auto_link.

    Interval i spans tops[i]..tops[i+1]; the last top reuses the previous
    thickness (a single top gets a default 10.0 m thickness).
    """
    from geoviz import IntervalItem

    intervals: list[Any] = []
    for i, (name, depth) in enumerate(tops):
        if i + 1 < len(tops):
            bottom = tops[i + 1][1]
        elif i > 0:
            bottom = depth + (depth - tops[i - 1][1])
        else:
            bottom = depth + 10.0
        intervals.append(IntervalItem(top=float(depth), bottom=float(bottom), name=name))
    return intervals
