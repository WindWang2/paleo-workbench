"""Well-table mathematical QC: MAD outlier score and sand-ratio constraints.

Formulas (product spec):
  - Modified z-score: z* = 0.6745 * (x - median) / MAD
  - Sand ratio:      R_s = H_s / H_t  with  0 ≤ H_s ≤ H_t  and H_t > 0
"""

from __future__ import annotations

import math

from geoviz import compute_sand_ratio, median_absolute_deviation, modified_z_scores

from paleo_workbench.project.models import WellTable, WellTableRow

# Consistency constant for normal distribution (≈ Φ^{-1}(0.75)).
_DEFAULT_OUTLIER_THRESHOLD = 3.5


def apply_sand_ratio_qc(table: WellTable) -> WellTable:
    """Mutate rows: fill R_s from H_s/H_t; mark invalid ratios."""
    for row in table.rows:
        ratio, flag = compute_sand_ratio(row.H_s, row.H_t)
        if flag == "invalid_ratio":
            row.qc_flag = "invalid_ratio"
            row.R_s = None
            row.b_i = 0.0
            continue
        if ratio is not None:
            row.R_s = ratio
            # Prefer ratio as primary z when factor is sand-ratio like.
            if row.z is None:
                row.z = ratio
    return table


def apply_mad_outlier_qc(
    table: WellTable,
    *,
    threshold: float = _DEFAULT_OUTLIER_THRESHOLD,
    value_attr: str = "z",
) -> WellTable:
    """Flag rows whose modified z-score exceeds *threshold*.

    *value_attr* (audit #1151) names the single WellTableRow column scored —
    ``"z"`` (raw measured value, the default for callers that cannot know the
    factor semantics), ``"R_s"``, ``"H_t"`` or ``"H_s"``. There is NO fallback
    to another column: mixing a dimensionless ratio with metre thicknesses in
    one MAD score field produced meaningless z-scores. Rows lacking the
    selected column are flagged ``missing``.

    Does not overwrite an existing ``invalid_ratio`` flag. Outliers keep their
    value but get ``qc_flag=outlier`` and reduced ``b_i`` so trend surfaces can
    down-weight them.
    """
    values: list[float] = []
    index_map: list[int] = []
    for i, row in enumerate(table.rows):
        if row.qc_flag == "invalid_ratio":
            continue
        raw = getattr(row, value_attr, None)
        if raw is None:
            row.qc_flag = "missing"
            row.b_i = 0.0
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            row.qc_flag = "missing"
            row.b_i = 0.0
            continue
        if not math.isfinite(v):
            row.qc_flag = "missing"
            row.b_i = 0.0
            continue
        values.append(v)
        index_map.append(i)

    if not values:
        return table

    z_stars = modified_z_scores(values)
    for local_i, row_i in enumerate(index_map):
        row = table.rows[row_i]
        z_star = float(z_stars[local_i])
        row.qc_z_star = z_star
        if abs(z_star) > float(threshold):
            row.qc_flag = "outlier"
            row.b_i = min(row.b_i, 0.1)
        elif row.qc_flag not in {"invalid_ratio", "missing"}:
            row.qc_flag = "ok"
    return table


def run_well_table_qc(
    table: WellTable,
    *,
    mad_threshold: float = _DEFAULT_OUTLIER_THRESHOLD,
) -> WellTable:
    """Full well-table QC pipeline: sand ratio then MAD on primary z."""
    apply_sand_ratio_qc(table)
    apply_mad_outlier_qc(table, threshold=mad_threshold, value_attr="z")
    return table


def qc_summary(table: WellTable) -> dict[str, int]:
    counts = {"ok": 0, "outlier": 0, "invalid_ratio": 0, "missing": 0, "total": len(table.rows)}
    for row in table.rows:
        key = row.qc_flag if row.qc_flag in counts else "ok"
        counts[key] = counts.get(key, 0) + 1
    return counts
