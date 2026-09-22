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
    """Mutate rows: fill R_s from H_s/H_t; mark invalid ratios.

    R_s is dimensionless. QC conclusions land in ``qc_flag`` / ``b_i`` and the
    dedicated ``R_s`` column — a missing ``z`` (the metre-valued primary
    measurement column) is never backfilled from the ratio: writing R_s into
    z mixed dimensions in one column and poisoned downstream MAD scoring
    (audit #1151 residual).
    """
    for row in table.rows:
        ratio, flag = compute_sand_ratio(row.H_s, row.H_t)
        if flag == "invalid_ratio":
            row.qc_flag = "invalid_ratio"
            row.R_s = None
            row.b_i = 0.0
            continue
        if ratio is not None:
            row.R_s = ratio
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
    value_key: str = "z",
) -> WellTable:
    """Full well-table QC pipeline: sand ratio then MAD on ONE column.

    *value_key* selects the column the MAD score runs on (audit #1151):
    pass ``value_key_for_factor_type(table.factor_type)`` when the factor
    semantics are known, so a sand-ratio table scores ``R_s`` instead of the
    metre-valued ``z`` (rows lacking the selected column are flagged
    ``missing`` — never filled from a column of another dimension). Defaults
    to ``"z"`` for backwards compatibility with unknown-semantics callers.
    """
    apply_sand_ratio_qc(table)
    apply_mad_outlier_qc(table, threshold=mad_threshold, value_attr=value_key)
    return table


def qc_summary(table: WellTable) -> dict[str, int]:
    counts = {"ok": 0, "outlier": 0, "invalid_ratio": 0, "missing": 0, "total": len(table.rows)}
    for row in table.rows:
        key = row.qc_flag if row.qc_flag in counts else "ok"
        counts[key] = counts.get(key, 0) + 1
    return counts
