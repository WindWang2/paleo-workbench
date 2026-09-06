"""Multi-factor fusion framework (M5, decision D7).

Combines several single-factor grid results into ONE interpretable
palaeogeographic interpretation. Two method families, both fully auditable:

* **weighted evidence** — every factor grid is normalised to a [0, 1]
  membership, and the fused likelihood is the weight-renormalised mean over
  the factors available at each cell. Where some factors carry no data the
  weights renormalise over the remaining evidence (recorded as
  ``nan_policy="renormalize"``); a cell with no evidence at all stays NaN —
  absence of data is never read as zero evidence.
* **rule_based** — an ordered table of threshold conditions on the *raw*
  factor values (real units, so geological tables stay meaningful), first
  match wins, explicit default class for non-matching cells.

Uncertainty handling stays within honest linear approximations:

* confidence grid — evidence coverage (available weight share) times
  agreement (1 − normalised spread of memberships);
* variance propagation — where input grids carry kriging variance, the
  fused variance is the squared-weight sum on the common support.

Every weight, normalisation and rule is serialisable and lands in the output
provenance, so a fusion product answers "which factor, which weight, which
rule produced this class". A deterministic leave-one-factor-out sensitivity
report quantifies each factor's influence as the fraction of classified
cells that change when its weight is removed.

No machine learning, no black-box scoring: this is D7's explicit-design
fusion. Registration into the catalog happens through :func:`register_output`
(DataRun + DERIVED version on the single catalog write path).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from paleo_workbench.workflow.factor_grid_result import FactorGridResult

__all__ = [
    "Normalization",
    "FactorEvidence",
    "FusionRule",
    "FusionModel",
    "FusionResult",
    "fuse",
    "sensitivity_report",
    "register_output",
]

FUSION_GENERATOR_VERSION = "factor-fusion-v1"

_RULE_OPS = {
    ">=": lambda v, t: v >= t,
    "<=": lambda v, t: v <= t,
    ">": lambda v, t: v > t,
    "<": lambda v, t: v < t,
    "==": lambda v, t: np.isclose(v, t, rtol=1e-9, atol=1e-12),
}


@dataclass(frozen=True, slots=True)
class Normalization:
    """Membership transform mapping a factor's raw values into [0, 1].

    * ``minmax`` — linear from *low* (0) to *high* (1), clamped.
    * ``ramp`` — 0 below *low*, linear to 1 at *high*, clamped (same as
      minmax but named for readability in rule tables).
    """

    kind: str  # "minmax" | "ramp"
    low: float
    high: float

    def __post_init__(self) -> None:
        if self.kind not in ("minmax", "ramp"):
            raise ValueError(f"unknown normalization kind {self.kind!r}")
        if not (math.isfinite(self.low) and math.isfinite(self.high)):
            raise ValueError("normalization bounds must be finite")
        if self.high <= self.low:
            raise ValueError("normalization requires high > low")

    def apply(self, values: np.ndarray) -> np.ndarray:
        span = self.high - self.low
        out = (values - self.low) / span
        return np.clip(out, 0.0, 1.0)

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "low": self.low, "high": self.high}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Normalization":
        return cls(
            kind=str(data["kind"]),
            low=float(data["low"]),
            high=float(data["high"]),
        )


@dataclass(frozen=True, slots=True)
class FactorEvidence:
    """One factor grid contributing to a fusion, with its declared weight."""

    factor_name: str
    grid: FactorGridResult
    weight: float
    normalization: Normalization

    def __post_init__(self) -> None:
        if not math.isfinite(self.weight) or self.weight <= 0.0:
            raise ValueError(
                f"evidence weight must be finite and positive, got {self.weight}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_name": self.factor_name,
            "weight": self.weight,
            "normalization": self.normalization.to_dict(),
            "source_version_ids": list(self.grid.source_refs),
            "algorithm_id": self.grid.algorithm_id,
        }


@dataclass(frozen=True, slots=True)
class FusionRule:
    """One ordered rule: all conditions hold on RAW values → *class_name*."""

    conditions: tuple[tuple[str, str, float], ...]
    class_name: str

    def __post_init__(self) -> None:
        if not self.conditions:
            raise ValueError("rule needs at least one condition")
        for index, condition in enumerate(self.conditions):
            if not isinstance(condition, (tuple, list)) or len(condition) != 3:
                raise ValueError(
                    f"rule condition {index} must be (factor, op, threshold), "
                    f"got {condition!r}"
                )
            _factor, op, threshold = condition
            if op not in _RULE_OPS:
                raise ValueError(f"unknown rule operator {op!r}")
            if not isinstance(threshold, (int, float)) or not math.isfinite(
                float(threshold)
            ):
                raise ValueError(
                    f"rule condition {index} threshold must be finite, got "
                    f"{threshold!r}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "conditions": [[f, op, float(t)] for f, op, t in self.conditions],
            "class_name": self.class_name,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FusionRule":
        conditions = []
        for index, c in enumerate(data.get("conditions") or []):
            if not isinstance(c, (tuple, list)) or len(c) != 3:
                raise ValueError(
                    f"rule condition {index} must be [factor, op, threshold], "
                    f"got {c!r}"
                )
            conditions.append((str(c[0]), str(c[1]), float(c[2])))
        return cls(
            conditions=tuple(conditions),
            class_name=str(data["class_name"]),
        )


@dataclass(slots=True)
class FusionModel:
    """Auditable fusion specification (weights + normalisations + rules)."""

    name: str
    kind: str  # "weighted_evidence" | "rule_based"
    evidences: list[FactorEvidence] = field(default_factory=list)
    rules: list[FusionRule] = field(default_factory=list)
    default_class: str = "未定"
    class_thresholds: list[float] = field(default_factory=list)
    class_names: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in ("weighted_evidence", "rule_based"):
            raise ValueError(f"unknown fusion kind {self.kind!r}")
        if self.kind == "weighted_evidence" and not self.evidences:
            raise ValueError("weighted_evidence fusion needs at least one evidence")
        if self.kind == "rule_based" and not self.rules:
            raise ValueError("rule_based fusion needs at least one rule")
        if self.kind == "weighted_evidence":
            if not self.class_names:
                raise ValueError("weighted_evidence fusion needs class_names")
            if len(self.class_thresholds) != len(self.class_names) - 1:
                raise ValueError(
                    "class_thresholds must have exactly len(class_names) - 1 entries"
                )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "default_class": self.default_class,
            "generator_version": FUSION_GENERATOR_VERSION,
            "evidences": [e.to_dict() for e in self.evidences],
            "rules": [r.to_dict() for r in self.rules],
        }
        if self.kind == "weighted_evidence":
            payload["class_thresholds"] = list(self.class_thresholds)
            payload["class_names"] = list(self.class_names)
        return payload

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], *, grids: Mapping[str, "FactorGridResult"] | None = None
    ) -> "FusionModel":
        """Rebuild a model from its provenance dict.

        Grid payloads are runtime objects and never serialised; supply them
        via *grids* (keyed by factor name) to get a runnable model.
        """
        grids = grids or {}
        evidences: list[FactorEvidence] = []
        for e in data.get("evidences", []):
            name = str(e["factor_name"])
            if name not in grids:
                raise ValueError(
                    f"runtime grid for factor {name!r} not supplied — "
                    "pass grids={factor_name: FactorGridResult}"
                )
            evidences.append(
                FactorEvidence(
                    factor_name=name,
                    grid=grids[name],
                    weight=float(e["weight"]),
                    normalization=Normalization.from_dict(e["normalization"]),
                )
            )
        return cls(
            name=str(data["name"]),
            kind=str(data["kind"]),
            evidences=evidences,
            rules=[FusionRule.from_dict(r) for r in data.get("rules", [])],
            default_class=str(data.get("default_class") or "未定"),
            class_thresholds=[
                float(t) for t in data.get("class_thresholds", [])
            ],
            class_names=list(data.get("class_names", [])),
        )

    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.to_dict(), sort_keys=True, ensure_ascii=False, default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class FusionResult:
    """Fused interpretation: likelihood + confidence + classification."""

    model: FusionModel
    model_dict: dict[str, Any]  # provenance snapshot (grids excluded)
    likelihood: FactorGridResult
    confidence: FactorGridResult
    variance: FactorGridResult | None  # only when inputs carry variance grids
    class_names: list[str]
    qc: dict[str, Any] = field(default_factory=dict)

    def provenance(self) -> dict[str, Any]:
        return {
            "model": self.model_dict,
            "model_fingerprint": self.model.fingerprint(),
            "generator_version": FUSION_GENERATOR_VERSION,
            "qc": self.qc,
        }


def _aligned_or_raise(grids: Sequence[FactorGridResult]) -> None:
    first = grids[0]
    for other in grids[1:]:
        if other.shape != first.shape:
            raise ValueError(
                f"evidence grids must share one geometry: {first.shape} vs {other.shape}"
            )
        if not (
            np.allclose(other.grid_x, first.grid_x)
            and np.allclose(other.grid_y, first.grid_y)
        ):
            raise ValueError("evidence grid axes differ — resample to a common grid first")
        # V6 §16 (P1-11): same-shape grids in DIFFERENT CRSs fuse silently —
        # refuse: the coordinates are not comparable until reprojected.
        crs_a = str(first.crs or "").strip()
        crs_b = str(other.crs or "").strip()
        if crs_a and crs_b and crs_a != crs_b:
            raise ValueError(
                f"evidence grids declare different CRSs ({crs_a!r} vs {crs_b!r}); "
                "reproject to a common CRS before fusing"
            )


def _build_grid(
    model: FusionModel,
    data: np.ndarray,
    reference: FactorGridResult,
    *,
    name: str,
    unit: str,
) -> FactorGridResult:
    return FactorGridResult(
        grid_z=data,
        grid_x=np.array(reference.grid_x, copy=True),
        grid_y=np.array(reference.grid_y, copy=True),
        factor_name=name,
        algorithm_id="factor_fusion",
        algorithm_parameters={
            "fusion_kind": model.kind,
            "fusion_name": model.name,
        },
        crs=reference.crs,
        unit=unit,
        generator_version=FUSION_GENERATOR_VERSION,
        source_refs=sorted(
            {ref for ev in model.evidences for ref in ev.grid.source_refs}
        ),
    )


def fuse(model: FusionModel) -> FusionResult:
    """Run the fusion described by *model* and return the fused products."""
    if model.kind == "weighted_evidence":
        return _fuse_weighted(model)
    return _fuse_rule_based(model)


def _fuse_weighted(model: FusionModel) -> FusionResult:
    grids = [ev.grid for ev in model.evidences]
    _aligned_or_raise(grids)
    reference = grids[0]
    # V6 §16 (P1-11): normalization bounds live in each factor's OWN unit;
    # a bounds-vs-grid unit mismatch (percent grid with 0..1 bounds) or a
    # values-vs-declared-unit mismatch misclassifies silently. Diagnose both.
    from paleo_workbench.workflow.factor_units import (
        validate_factor_unit_against_values,
    )

    unit_warnings: list[str] = []
    for ev in model.evidences:
        grid_unit = str(ev.grid.unit or "").strip()
        if (
            getattr(ev.normalization, "kind", "") in ("minmax", "ramp")
            and grid_unit in {"%", "percent"}
            and max(abs(ev.normalization.low), abs(ev.normalization.high)) <= 1.5
        ):
            unit_warnings.append(
                f"evidence {ev.factor_name!r}: percent-declared grid with 0..1 "
                f"normalization bounds (low={ev.normalization.low}, "
                f"high={ev.normalization.high}) — bounds unit mismatch"
            )
        unit_warnings.extend(
            validate_factor_unit_against_values(
                ev.factor_name, ev.grid.unit, ev.grid.grid_z
            )
        )
    weights = np.array([ev.weight for ev in model.evidences], dtype=float)
    total_weight = float(weights.sum())
    memberships = [ev.normalization.apply(ev.grid.grid_z.astype(float)) for ev in model.evidences]
    finite_masks = [np.isfinite(m) for m in memberships]

    stack = np.stack(memberships)  # (n, h, w)
    avail = np.stack(finite_masks)  # (n, h, w)
    weighted = stack * weights[:, None, None]
    w_avail = weights[:, None, None] * avail
    w_sum = w_avail.sum(axis=0)
    m_sum = np.where(avail, weighted, 0.0).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        likelihood = m_sum / w_sum
    likelihood[w_sum <= 0.0] = np.nan  # no evidence at all stays nodata

    # Confidence: coverage (available weight share) × agreement.
    with np.errstate(invalid="ignore", divide="ignore"):
        coverage = w_sum / total_weight
        w_sq = np.where(avail, weighted * stack, 0.0).sum(axis=0)
        mean_sq = w_sq / w_sum
        spread_sq = np.maximum(mean_sq - likelihood**2, 0.0)
        agreement = 1.0 - np.sqrt(spread_sq)
    confidence = coverage * agreement
    confidence[w_sum <= 0.0] = np.nan

    # Variance propagation on the common support of available evidence.
    variance: FactorGridResult | None = None
    var_grids = [ev.grid.variance_grid for ev in model.evidences]
    if any(v is not None for v in var_grids):
        var_acc = np.zeros_like(likelihood)
        have_var = np.zeros_like(likelihood, dtype=bool)
        for ev, var, mask in zip(model.evidences, var_grids, finite_masks):
            if var is None:
                continue
            share = (ev.weight / w_sum) ** 2
            var_acc += np.where(mask, share * var.astype(float), 0.0)
            have_var |= mask
        var_acc[~have_var] = np.nan
        variance = _build_grid(model, var_acc, reference, name="融合方差", unit="1")

    # Classification on the fused likelihood: thresholds ascend and higher
    # classes overwrite lower ones, so the highest matching class wins.
    thresholds = [float(t) for t in model.class_thresholds]
    finite = np.isfinite(likelihood)
    class_grid = np.zeros(likelihood.shape)  # 0 = lowest class
    for idx in range(1, len(thresholds) + 1):
        class_grid[finite & (likelihood >= thresholds[idx - 1])] = float(idx)
    class_grid[~finite] = np.nan

    qc = {
        "fusion_kind": model.kind,
        "n_factors": len(model.evidences),
        "unit_warnings": unit_warnings,
        "classified_cells": int(finite.sum()),
        "unclassified_cells": int((~finite).sum()),
        "class_counts": {
            model.class_names[i]: int((class_grid == i).sum())
            for i in range(len(model.class_names))
        },
        "nan_policy": "renormalize",
    }
    result = FusionResult(
        model=model,
        model_dict=model.to_dict(),
        likelihood=_build_grid(model, likelihood, reference, name=f"{model.name} 融合似然", unit="1"),
        confidence=_build_grid(model, confidence, reference, name=f"{model.name} 融合置信度", unit="1"),
        variance=variance,
        class_names=list(model.class_names),
        qc=qc,
    )
    result.likelihood.algorithm_parameters["class_thresholds"] = list(thresholds)
    return result


def _fuse_rule_based(model: FusionModel) -> FusionResult:
    grids = {ev.factor_name: ev.grid for ev in model.evidences}
    _aligned_or_raise([ev.grid for ev in model.evidences])
    reference = next(iter(grids.values()))
    shape = reference.shape
    fields = {name: g.grid_z.astype(float) for name, g in grids.items()}

    # class grid: NaN = no evidence, 0 = default, 1..n = matching rule index
    class_grid = np.full(shape, np.nan)
    matched_by_rule = np.zeros(shape, dtype=bool)
    rule_hits = {i: 0 for i in range(len(model.rules))}
    for r_idx, rule in enumerate(model.rules):
        applicable = ~matched_by_rule
        for factor_name, op, threshold in rule.conditions:
            if factor_name not in fields:
                raise ValueError(
                    f"rule references unknown factor {factor_name!r}; "
                    f"known: {sorted(fields)}"
                )
            applicable &= np.isfinite(fields[factor_name])
            applicable &= _RULE_OPS[op](fields[factor_name], threshold)
        class_grid[applicable] = float(r_idx + 1)
        matched_by_rule |= applicable
        rule_hits[r_idx] = int(applicable.sum())

    no_evidence = np.ones(shape, dtype=bool)
    for values in fields.values():
        no_evidence &= ~np.isfinite(values)
    # cells with evidence but no matching rule → explicit default class;
    # cells with no evidence at all → nodata (never the default)
    class_grid[~matched_by_rule & ~no_evidence] = 0.0

    # Confidence: 1.0 for explicitly matched cells, 0.0 for the default
    # class, nodata where there is no evidence at all.
    confidence = np.full(shape, np.nan)
    confidence[matched_by_rule] = 1.0
    confidence[(class_grid == 0) & ~no_evidence] = 0.0

    names = [model.default_class] + [r.class_name for r in model.rules]
    qc = {
        "fusion_kind": model.kind,
        "n_factors": len(grids),
        "n_rules": len(model.rules),
        "classified_cells": int(matched_by_rule.sum()),
        "default_cells": int(((class_grid == 0) & ~no_evidence).sum()),
        "unclassified_cells": int(no_evidence.sum()),
        "rule_hits": {model.rules[i].class_name: hits for i, hits in rule_hits.items()},
    }
    result = FusionResult(
        model=model,
        model_dict=model.to_dict(),
        likelihood=_build_grid(model, class_grid.astype(float), reference, name=f"{model.name} 融合分类", unit="1"),
        confidence=_build_grid(model, confidence, reference, name=f"{model.name} 融合置信度", unit="1"),
        variance=None,
        class_names=names,
        qc=qc,
    )
    result.likelihood.algorithm_parameters["class_encoding"] = "nan=nodata; 0=default; 1..n=rule_index"
    return result


def sensitivity_report(
    model: FusionModel,
    baseline: FusionResult,
    *,
    delta: float | None = None,
) -> dict[str, Any]:
    """Leave-one-factor-out sensitivity of the fused classification.

    For every factor, re-fuse with that factor's weight removed and report
    the fraction of *classified* cells whose class changed (weighted
    perturbations are only defined for the weighted family). Deterministic,
    interpretable, and recorded alongside the model provenance.
    """
    if model.kind != "weighted_evidence":
        return {"kind": "leave_one_out", "supported": False}
    base_classes = _classify_grid(baseline)
    report: dict[str, Any] = {"kind": "leave_one_out", "supported": True, "factors": {}}
    if len(model.evidences) < 2:
        # Leave-one-out needs someone left in the model; a single-factor
        # fusion has no perturbation to measure.
        report["reason"] = "single factor — no perturbation possible"
        report["factors"] = {
            model.evidences[0].factor_name: {
                "weight": model.evidences[0].weight,
                "class_change_fraction": None,
                "changed_cells": 0,
                "comparable_cells": 0,
            }
        }
        return report
    for ev in model.evidences:
        reduced = FusionModel(
            name=model.name,
            kind=model.kind,
            evidences=[e for e in model.evidences if e is not ev],
            rules=list(model.rules),
            default_class=model.default_class,
            class_thresholds=list(model.class_thresholds),
            class_names=list(model.class_names),
        )
        variant = _fuse_weighted(reduced)
        variant_classes = _classify_grid(variant)
        comparable = np.isfinite(base_classes) & np.isfinite(variant_classes)
        total = int(comparable.sum())
        changed = int((comparable & (base_classes != variant_classes)).sum())
        report["factors"][ev.factor_name] = {
            "weight": ev.weight,
            "class_change_fraction": (changed / total) if total else None,
            "changed_cells": changed,
            "comparable_cells": total,
        }
    return report


def _classify_grid(result: FusionResult) -> np.ndarray:
    likelihood = result.likelihood.grid_z.astype(float)
    finite = np.isfinite(likelihood)
    if result.model.kind == "weighted_evidence":
        out = np.zeros(likelihood.shape)
        for idx in range(1, len(result.model.class_thresholds) + 1):
            out[finite & (likelihood >= result.model.class_thresholds[idx - 1])] = float(idx)
        out[~finite] = np.nan
        return out
    return likelihood  # rule-based class encoding already numeric


def register_output(
    catalog_service,
    result: FusionResult,
    *,
    project_path=None,
) -> str:
    """Register the fused likelihood as a catalog DERIVED version + DataRun.

    Parents are the *input factor versions* every evidence declared; the run
    parameters carry the full model provenance. Returns the new version id.
    """
    import tempfile
    from pathlib import Path

    from paleo_workbench.catalog.grid_artifact import write_grid_artifact

    parents = sorted({ref for ev in result.model.evidences for ref in ev.grid.source_refs})
    provenance = result.provenance()
    # V6 §16 (P1-11): sensitivity was computed but never persisted — leave-
    # one-factor-out is part of the product's honesty record.
    try:
        sensitivity = sensitivity_report(result.model, result)
    except Exception:
        sensitivity = None
    if sensitivity is not None:
        provenance["sensitivity_leave_one_factor_out"] = sensitivity
    with tempfile.TemporaryDirectory() as td:
        artifact_path = write_grid_artifact(result.likelihood, td, "fusion_result")
        derived = catalog_service.create_derived(
            artifact_path,
            parent_version_ids=parents or [],
            name=f"{result.model.name} 融合成果",
            operation="factor_fusion",
            parameters=provenance,
            generator=FUSION_GENERATOR_VERSION,
            type="factor_map",
            format="npz",
        )
        # The uncertainty surface ships WITH the product (best-effort
        # sibling version): a fused map without its confidence grid used to
        # look more certain than its provenance allows.
        confidence_path = write_grid_artifact(
            result.confidence, td, "fusion_confidence"
        )
        try:
            derived_conf = catalog_service.create_derived(
                confidence_path,
                parent_version_ids=[str(derived.id)],
                name=f"{result.model.name} 融合置信度",
                operation="factor_fusion:confidence",
                parameters={"fusion_version_id": str(derived.id)},
                generator=FUSION_GENERATOR_VERSION,
                type="factor_map",
                format="npz",
            )
        except Exception:
            derived_conf = None
    result.likelihood.run_ref = getattr(derived, "run_id", None) or str(
        getattr(derived, "id", "")
    )
    result.qc["catalog_version_id"] = str(derived.id)
    if derived_conf is not None:
        result.qc["confidence_version_id"] = str(derived_conf.id)
    return str(derived.id)
