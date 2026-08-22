"""WellTable adapters: bridge sample_points dicts ↔ typed well tables."""

from __future__ import annotations

from typing import Any

from paleo_workbench.project.models import (
    FactorMapTask,
    ProjectDocument,
    WellTable,
    WellTableRow,
    _id,
)


def well_table_from_sample_points(
    sample_points: list[dict[str, Any]] | None,
    *,
    name: str = "WellTable",
    target_horizon: str = "",
    factor_type: str = "",
    source_resource_ids: list[str] | None = None,
) -> WellTable:
    """Build a WellTable from legacy factor sample_points records."""
    rows: list[WellTableRow] = []
    for i, pt in enumerate(sample_points or []):
        if not isinstance(pt, dict):
            continue
        try:
            if "x" in pt and "y" in pt:
                x = float(pt["x"])
                y = float(pt["y"])
            elif "lng" in pt and "lat" in pt:
                x = float(pt["lng"])
                y = float(pt["lat"])
            else:
                continue
        except (TypeError, ValueError):
            continue
        z = _optional_float(pt.get("value", pt.get("z", pt.get("v"))))
        H_s = _optional_float(pt.get("H_s", pt.get("hs", pt.get("sand_thickness"))))
        H_t = _optional_float(pt.get("H_t", pt.get("ht", pt.get("total_thickness"))))
        R_s = _optional_float(pt.get("R_s", pt.get("rs", pt.get("sand_ratio"))))
        name_w = str(pt.get("well") or pt.get("name") or pt.get("well_name") or f"W{i + 1}")
        q = _optional_float(pt.get("q", pt.get("quality")))
        b_i = _optional_float(pt.get("b_i", pt.get("barrier_weight")))
        rows.append(
            WellTableRow(
                well_id=str(pt.get("well_id") or pt.get("id") or _id("well")),
                name=name_w,
                x=x,
                y=y,
                z=z,
                H_s=H_s,
                H_t=H_t,
                R_s=R_s,
                q=1.0 if q is None else float(q),
                b_i=1.0 if b_i is None else float(b_i),
                attributes={
                    k: v
                    for k, v in pt.items()
                    if k
                    not in {
                        "x",
                        "y",
                        "lng",
                        "lat",
                        "value",
                        "z",
                        "v",
                        "H_s",
                        "H_t",
                        "R_s",
                        "hs",
                        "ht",
                        "rs",
                        "sand_thickness",
                        "total_thickness",
                        "sand_ratio",
                        "well",
                        "name",
                        "well_name",
                        "well_id",
                        "id",
                        "q",
                        "quality",
                        "b_i",
                        "barrier_weight",
                    }
                },
            )
        )
    return WellTable(
        name=name,
        target_horizon=target_horizon,
        factor_type=factor_type,
        rows=rows,
        source_resource_ids=list(source_resource_ids or []),
    )


def sample_points_from_well_table(
    table: WellTable,
    *,
    include_flagged: bool = False,
) -> list[dict[str, Any]]:
    """Export WellTable rows to factor sample_points dicts for IDW/grid APIs.

    By default skips ``outlier`` / ``invalid_ratio`` / ``missing`` rows so
    interpolation only sees QC-clean samples.
    """
    points: list[dict[str, Any]] = []
    for row in table.rows:
        if not include_flagged and row.qc_flag != "ok":
            continue
        z = row.z
        if z is None and row.R_s is not None:
            z = row.R_s
        if z is None and row.H_t is not None:
            z = row.H_t
        if z is None:
            continue
        rec: dict[str, Any] = {
            "well_id": row.well_id,
            "well": row.name,
            "name": row.name,
            "x": row.x,
            "y": row.y,
            "value": float(z),
            "q": row.q,
            "b_i": row.b_i,
            "qc_flag": row.qc_flag,
        }
        if row.H_s is not None:
            rec["H_s"] = row.H_s
        if row.H_t is not None:
            rec["H_t"] = row.H_t
        if row.R_s is not None:
            rec["R_s"] = row.R_s
        if row.qc_z_star is not None:
            rec["qc_z_star"] = row.qc_z_star
        points.append(rec)
    return points


def attach_well_table_to_factor_task(
    project: ProjectDocument,
    table: WellTable,
    task: FactorMapTask,
) -> WellTable:
    """Register *table* on the project and link it to *task* (+ sample_points sync)."""
    table.linked_factor_task_id = task.id
    table.target_horizon = table.target_horizon or task.target_horizon
    table.factor_type = table.factor_type or task.factor_type

    # Upsert by id
    replaced = False
    for i, existing in enumerate(project.well_tables):
        if existing.id == table.id:
            project.well_tables[i] = table
            replaced = True
            break
    if not replaced:
        project.well_tables.append(table)

    task.well_table_id = table.id
    params = dict(task.parameters or {})
    params["sample_points"] = sample_points_from_well_table(table)
    params["well_table_id"] = table.id
    task.parameters = params
    return table


def well_table_from_factor_task(task: FactorMapTask) -> WellTable:
    """Recover a WellTable from a FactorMapTask's sample_points (no project write)."""
    params = task.parameters or {}
    points = params.get("sample_points") if isinstance(params, dict) else None
    table = well_table_from_sample_points(
        points if isinstance(points, list) else [],
        name=f"{task.name} wells",
        target_horizon=task.target_horizon,
        factor_type=task.factor_type,
        source_resource_ids=list(task.input_resource_ids or []),
    )
    table.linked_factor_task_id = task.id
    if task.well_table_id:
        table.id = task.well_table_id
    return table


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sync_well_table_to_linked_tasks(
    project: ProjectDocument, table: WellTable
) -> list[FactorMapTask]:
    """Write cleaned sample_points back to tasks explicitly bound to *table*.

    Audit #936: the previous fallback injected the table's samples into
    ``factor_map_tasks[0]`` even when that task belonged to a different
    horizon/factor.  Only explicit bindings are honoured now; a legacy
    single-task project with no binding yet keeps the convenience of adopting
    the table.  Returns the tasks that were updated.
    """
    linked = [
        task for task in project.factor_map_tasks if task.well_table_id == table.id
    ]
    if not linked and len(project.factor_map_tasks) == 1:
        linked = list(project.factor_map_tasks)
    for task in linked:
        params = dict(task.parameters or {})
        params["sample_points"] = sample_points_from_well_table(table)
        task.parameters = params
        task.well_table_id = table.id
    return linked
