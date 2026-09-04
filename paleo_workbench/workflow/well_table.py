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

# Value-key selection (audit #1151): a WellTableRow carries physically distinct
# columns — ``z`` (raw measured value), ``H_s``/``H_t`` (metres of thickness),
# ``R_s`` (dimensionless sand ratio). The old per-row z→R_s→H_t export
# fallback silently mixed a ratio with metre thicknesses in one interpolation
# field. The factor TYPE now decides which single column feeds an export;
# aliases mirror the factor families registered in
# ``mapping.geological_pipeline.pipeline._FACTOR_ALIAS_GROUPS``.
_VALUE_KEY_ALIAS_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("R_s", ("sand_ratio", "r_s", "rs", "砂地比")),
    ("H_t", ("formation_thickness", "thickness", "h_t", "ht", "total_thickness", "地层厚度")),
    ("H_s", ("sand_thickness", "h_s", "hs", "sand", "砂岩厚度")),
)
VALID_VALUE_KEYS: tuple[str, ...] = ("z", "H_s", "H_t", "R_s")


def value_key_for_factor_type(factor_type: str) -> str:
    """WellTableRow column holding *factor_type*'s measured physical quantity.

    The sand-ratio / formation-thickness / sand-thickness factor families map
    to their dedicated column; every other (or unknown/empty) factor type maps
    to ``"z"`` — the raw measured value.
    """
    norm = str(factor_type or "").strip().lower()
    if not norm:
        return "z"
    for key, aliases in _VALUE_KEY_ALIAS_GROUPS:
        if norm == key.lower() or norm in aliases:
            return key
    return "z"


def _check_value_key(value_key: str) -> None:
    if value_key not in VALID_VALUE_KEYS:
        raise ValueError(
            f"value_key must be one of {VALID_VALUE_KEYS}, got {value_key!r}"
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
    value_key: str,
    stats: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Export WellTable rows to factor sample_points dicts for IDW/grid APIs.

    By default skips ``outlier`` / ``invalid_ratio`` / ``missing`` rows so
    interpolation only sees QC-clean samples.

    *value_key* (audit #1151, required) names the single WellTableRow column
    exported as ``value``: ``"z"`` (raw measured value — pass this when the
    factor semantics are genuinely unknown), ``"R_s"`` (dimensionless sand
    ratio), or ``"H_t"``/``"H_s"`` (metres of thickness). Rows that lack the
    selected column are skipped and counted — never silently filled from a
    column of a different physical dimension. Pass *stats* (dict) to receive
    ``{"exported": int, "skipped_missing_value": int}``.
    """
    _check_value_key(value_key)
    points: list[dict[str, Any]] = []
    skipped_missing = 0
    for row in table.rows:
        if not include_flagged and row.qc_flag != "ok":
            continue
        z = getattr(row, value_key)
        if z is None:
            skipped_missing += 1
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
    if stats is not None:
        stats["exported"] = len(points)
        stats["skipped_missing_value"] = skipped_missing
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
    params["sample_points"] = sample_points_from_well_table(
        table, value_key=value_key_for_factor_type(table.factor_type)
    )
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
        params["sample_points"] = sample_points_from_well_table(
            table, value_key=value_key_for_factor_type(task.factor_type)
        )
        task.parameters = params
        task.well_table_id = table.id
    return linked


def well_table_to_arrays(
    table: WellTable,
    *,
    include_flagged: bool = False,
    value_key: str,
) -> dict[str, Any]:
    """Export WellTable columns directly to contiguous NumPy arrays.

    *value_key* (audit #1151, required) names the single WellTableRow column
    exported as ``z``: ``"z"`` (raw measured value — pass this when the factor
    semantics are genuinely unknown), ``"R_s"`` (dimensionless), or
    ``"H_t"``/``"H_s"`` (metres). Rows lacking the selected column are skipped
    from every array and counted under ``"skipped_missing"`` in the result —
    never silently filled from a column of a different physical dimension.
    """
    import numpy as np

    _check_value_key(value_key)
    qc_rows = [r for r in table.rows if include_flagged or r.qc_flag == "ok"]
    valid_rows = [r for r in qc_rows if getattr(r, value_key) is not None]
    skipped_missing = len(qc_rows) - len(valid_rows)
    n = len(valid_rows)
    if n == 0:
        return {
            "names": np.array([], dtype=object),
            "x": np.array([], dtype=np.float64),
            "y": np.array([], dtype=np.float64),
            "z": np.array([], dtype=np.float64),
            "q": np.array([], dtype=np.float64),
            "b_i": np.array([], dtype=np.float64),
            "qc_flags": np.array([], dtype=object),
            "skipped_missing": skipped_missing,
        }

    names = [r.name for r in valid_rows]
    x = np.fromiter((r.x for r in valid_rows), dtype=np.float64, count=n)
    y = np.fromiter((r.y for r in valid_rows), dtype=np.float64, count=n)
    z = np.fromiter((getattr(r, value_key) for r in valid_rows), dtype=np.float64, count=n)
    q = np.fromiter((r.q for r in valid_rows), dtype=np.float64, count=n)
    b_i = np.fromiter((r.b_i for r in valid_rows), dtype=np.float64, count=n)
    qc_flags = [r.qc_flag for r in valid_rows]

    return {
        "names": np.array(names, dtype=object),
        "x": x,
        "y": y,
        "z": z,
        "q": q,
        "b_i": b_i,
        "qc_flags": np.array(qc_flags, dtype=object),
        "skipped_missing": skipped_missing,
    }


def well_table_to_dataframe(
    table: WellTable,
    *,
    include_flagged: bool = True,
    value_key: str,
):
    """Convert WellTable to a pandas DataFrame (see ``well_table_to_arrays``)."""
    import pandas as pd

    data = well_table_to_arrays(
        table, include_flagged=include_flagged, value_key=value_key
    )
    df = pd.DataFrame(
        {
            "name": data["names"],
            "x": data["x"],
            "y": data["y"],
            "value": data["z"],
            "q": data["q"],
            "b_i": data["b_i"],
            "qc_flag": data["qc_flags"],
        }
    )
    return df

