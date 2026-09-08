"""Factor sample normalization — one policy authority for every method (V8 M3).

Twin wells / re-sampled logs deliver samples at IDENTICAL (x, y). Every
interpolation backend treated them differently before V8:

* plain IDW — every duplicate cast a full-weight vote (double-vote);
* constrained IDW — first-wins (its own internal dedupe);
* engine kriging — collapsed to the mean (its own internal dedupe);
* cross-validation — collapsed duplicates for fold scoring while production
  kept them, so CV scored a *different* model than the one delivered.

This module makes the policy EXPLICIT and host-side, applied once before the
engine sees the samples, so production, CV, fingerprints and surface checks
all consume the same normalized sample set:

* ``"mean"`` (default) — duplicates merge to their mean value, matching the
  kriging authority's convention and the CV scorer's existing behaviour;
* ``"first"`` — keep the first occurrence (legacy constrained-IDW semantics);
* ``"error"`` — refuse (strict callers that want duplicates surfaced, never
  silently merged);
* ``"keep"`` — legacy no-op (documented double-vote for plain IDW; escape
  hatch for exact bit-compatibility with pre-V8 results).

The report travels with the task (``parameters["sample_normalization"]``),
the grid result provenance and quality metrics — a merged twin well can never
disappear silently.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

__all__ = [
    "DUPLICATE_POLICIES",
    "DEFAULT_DUPLICATE_POLICY",
    "SampleNormalizationReport",
    "normalize_factor_samples",
]


DUPLICATE_POLICIES = ("mean", "first", "error", "keep")
DEFAULT_DUPLICATE_POLICY = "mean"

_NUMERIC_EXTRAS = ("q", "b_i")


@dataclass(frozen=True, slots=True)
class SampleNormalizationReport:
    """Honest accounting of what normalization did to a sample set."""

    policy: str
    n_input: int
    n_valid: int
    n_nonfinite_dropped: int
    n_duplicate_groups: int  # distinct (x, y) locations with 2+ samples
    n_duplicates_merged: int  # total samples removed by merging
    n_qc_flagged: int  # samples carrying a non-ok qc_flag (visibility only)

    @property
    def duplicates_present(self) -> bool:
        return self.n_duplicate_groups > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "n_input": self.n_input,
            "n_valid": self.n_valid,
            "n_nonfinite_dropped": self.n_nonfinite_dropped,
            "n_duplicate_groups": self.n_duplicate_groups,
            "n_duplicates_merged": self.n_duplicates_merged,
            "n_qc_flagged": self.n_qc_flagged,
        }


def _valid_record(pt: Any) -> dict[str, Any] | None:
    """Valid (finite x, y, z) sample record, or None (mirrors the
    fingerprint extractor's validity rules so both authorities agree)."""
    if not isinstance(pt, Mapping):
        return None
    try:
        if "x" in pt and "y" in pt:
            x = float(pt["x"])
            y = float(pt["y"])
        elif "lng" in pt and "lat" in pt:
            x = float(pt["lng"])
            y = float(pt["lat"])
        else:
            return None
        z = float(pt.get("value", pt.get("z", pt.get("v"))))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
        return None
    record: dict[str, Any] = {"x": x, "y": y, "z": z}
    for key in _NUMERIC_EXTRAS:
        value = pt.get(key)
        if value is not None:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                record[key] = number
    qc = pt.get("qc_flag")
    if qc is not None:
        record["qc_flag"] = str(qc)
    for key in ("well_id", "name"):
        value = pt.get(key)
        if value:
            record[key] = str(value)
    return record


def normalize_factor_samples(
    points: Sequence[Any],
    *,
    policy: str = DEFAULT_DUPLICATE_POLICY,
) -> tuple[list[dict[str, Any]], SampleNormalizationReport]:
    """Apply the duplicate policy to a raw sample set.

    Returns ``(normalized_points, report)``. Non-finite samples are dropped
    (the engine would drop them anyway — here the count is reported instead
    of being invisible). Order is preserved: the first occurrence of each
    distinct location defines the output position of its merged record.
    """
    if policy not in DUPLICATE_POLICIES:
        raise ValueError(
            f"unknown duplicate policy {policy!r}; choose from {DUPLICATE_POLICIES}"
        )
    records: list[dict[str, Any]] = []
    n_nonfinite = 0
    for pt in points or []:
        record = _valid_record(pt)
        if record is None:
            n_nonfinite += 1
            continue
        records.append(record)
    n_qc_flagged = sum(
        1 for r in records if str(r.get("qc_flag") or "") not in ("", "ok")
    )

    if policy == "keep":
        report = SampleNormalizationReport(
            policy=policy,
            n_input=len(points or []),
            n_valid=len(records),
            n_nonfinite_dropped=n_nonfinite,
            n_duplicate_groups=0,
            n_duplicates_merged=0,
            n_qc_flagged=n_qc_flagged,
        )
        return records, report

    # Group by exact coordinate identity (engine dedupe semantics: exact
    # equality, no epsilon — near-but-not-equal wells stay distinct samples).
    groups: dict[tuple[float, float], list[int]] = {}
    order: list[tuple[float, float]] = []
    for index, record in enumerate(records):
        key = (record["x"], record["y"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(index)

    duplicate_keys = [key for key in order if len(groups[key]) > 1]
    if policy == "error" and duplicate_keys:
        raise ValueError(
            "duplicate sample locations present and duplicate_policy='error': "
            f"{len(duplicate_keys)} location(s) with 2+ samples "
            f"(first at x={duplicate_keys[0][0]!r}, y={duplicate_keys[0][1]!r})"
        )

    normalized: list[dict[str, Any]] = []
    merged = 0
    for key in order:
        indices = groups[key]
        if len(indices) == 1:
            normalized.append(records[indices[0]])
            continue
        merged += len(indices) - 1
        members = [records[i] for i in indices]
        base = dict(members[0])
        if policy == "mean":
            # incremental mean: a plain sum() overflows to inf for huge
            # values (1e308 duplicates); mean-of-two must stay finite
            def _imean(values):
                acc = 0.0
                for i, v in enumerate(values, 1):
                    acc += (v - acc) / i
                return acc

            base["z"] = _imean(m["z"] for m in members)
            for extra in _NUMERIC_EXTRAS:
                values = [m[extra] for m in members if extra in m]
                if values:
                    base[extra] = _imean(values)
        # Worst-flag-wins: one flagged twin flags the merged location — a
        # conservative sample is dropped by QC-aware backends, never laundered.
        flags = {str(m.get("qc_flag") or "") for m in members}
        flags.discard("")
        flags.discard("ok")
        if flags:
            base["qc_flag"] = sorted(flags)[0]
        names = [str(m.get("well_id") or m.get("name") or "") for m in members]
        names = [n for n in names if n]
        if names:
            base["well_id"] = "+".join(dict.fromkeys(names))
        normalized.append(base)

    report = SampleNormalizationReport(
        policy=policy,
        n_input=len(points or []),
        n_valid=len(records),
        n_nonfinite_dropped=n_nonfinite,
        n_duplicate_groups=len(duplicate_keys),
        n_duplicates_merged=merged,
        n_qc_flagged=n_qc_flagged,
    )
    return normalized, report


def duplicate_policy_from_params(params: Mapping[str, Any] | None) -> str:
    """Resolve the task's duplicate policy with honest fallback to default."""
    raw = (params or {}).get("duplicate_policy")
    if raw is None:
        return DEFAULT_DUPLICATE_POLICY
    policy = str(raw).strip().lower()
    if policy not in DUPLICATE_POLICIES:
        return DEFAULT_DUPLICATE_POLICY
    return policy
