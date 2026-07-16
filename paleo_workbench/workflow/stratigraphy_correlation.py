"""Multi-well stratigraphic correlation helpers (CrossWell engine)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from paleo_workbench.pipeline.assets import WELL_KEY
from paleo_workbench.project.models import ProjectDocument
from paleo_workbench.viz.adapter import VizAdapter
from paleo_workbench.workflow.well_log_prediction import merge_prediction_onto_well_log


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
