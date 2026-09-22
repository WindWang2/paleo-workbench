#!/usr/bin/env python3
"""Generate the frozen factor_fusion + factor_units oracle for CONV-24.

Drives the REAL Python implementation and freezes: normalization ctor/apply,
rule ctor/from_dict, model ctor/to_dict/from_dict/fingerprint, weighted and
rule-based fusion (all qc + diagnostics + provenance), alignment/CRS errors,
sensitivity reports, and the factor_units lookup/validation surface. Also
emits ``libs/factor_fusion/src/factor_units_data.inc`` (declaration table)
and ``libs/factor_fusion/src/units_lower_map.inc`` (Unicode lower() map).

Deterministic: re-run must be byte-identical (CI checks the diff).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.workflow import factor_units as fu  # noqa: E402
from paleo_workbench.workflow.factor_fusion import (  # noqa: E402
    FactorEvidence,
    FusionModel,
    FusionRule,
    Normalization,
    _aligned_or_raise,
    fuse,
    sensitivity_report,
)
from paleo_workbench.workflow.factor_grid_result import FactorGridResult  # noqa: E402

FIXTURE = (
    ROOT
    / "libs/factor_fusion/factor_fusion_tests/fixtures/factor_fusion_oracle.json"
)
INC = ROOT / "libs/factor_fusion/src/factor_units_data.inc"
LOWER_INC = ROOT / "libs/factor_fusion/src/units_lower_map.inc"

cases: list[dict] = []


def add(cid: str, fn: str, inp: dict, expect: dict) -> None:
    cases.append({"id": cid, "fn": fn, "input": inp, "expect": expect})


def freeze_grid(g: FactorGridResult) -> dict:
    return {
        "grid_z": _rows(g.grid_z),
        "variance_grid": _rows(g.variance_grid) if g.variance_grid is not None else None,
        "factor_name": g.factor_name,
        "algorithm_id": g.algorithm_id,
        "algorithm_parameters": dict(g.algorithm_parameters),
        "crs": g.crs,
        "unit": g.unit,
        "generator_version": g.generator_version,
        "source_refs": list(g.source_refs),
    }


def _rows(arr) -> list:
    if arr is None:
        return None
    return [[None if not math.isfinite(v) else float(v) for v in row] for row in arr]


def make_grid(spec: dict) -> FactorGridResult:
    z = np.array(
        [[np.nan if v is None else float(v) for v in row] for row in spec["grid_z"]],
        dtype=float,
    )
    var = spec.get("variance_grid")
    return FactorGridResult(
        grid_z=z,
        grid_x=np.array(spec["grid_x"], dtype=float),
        grid_y=np.array(spec["grid_y"], dtype=float),
        factor_name=spec["factor_name"],
        algorithm_id=spec.get("algorithm_id", "idw"),
        algorithm_parameters=dict(spec.get("algorithm_parameters") or {}),
        crs=spec.get("crs"),
        unit=spec.get("unit"),
        source_refs=list(spec.get("source_refs") or []),
        variance_grid=(
            np.array(
                [[np.nan if v is None else float(v) for v in row] for row in var],
                dtype=float,
            )
            if var is not None
            else None
        ),
    )


def make_evidence(spec: dict) -> FactorEvidence:
    return FactorEvidence(
        factor_name=spec["factor_name"],
        grid=make_grid(spec["grid"]),
        weight=float(spec["weight"]),
        normalization=Normalization(**spec["normalization"]),
    )


def make_model(spec: dict, evidences: list | None = None) -> FusionModel:
    return FusionModel(
        name=spec["name"],
        kind=spec["kind"],
        evidences=evidences if evidences is not None else [],
        rules=[FusionRule(conditions=tuple(tuple(c) for c in r["conditions"]),
                          class_name=r["class_name"]) for r in spec.get("rules", [])],
        default_class=spec.get("default_class", "未定"),
        class_thresholds=[float(t) for t in spec.get("class_thresholds", [])],
        class_names=list(spec.get("class_names", [])),
        weight_provenance=spec.get("weight_provenance"),
    )


def freeze_result(r) -> dict:
    return {
        "likelihood": freeze_grid(r.likelihood),
        "confidence": freeze_grid(r.confidence),
        "variance": freeze_grid(r.variance) if r.variance is not None else None,
        "class_names": list(r.class_names),
        "qc": r.qc,
        "model_dict": r.model_dict,
        "provenance": r.provenance(),
    }


def capture(fn, *args, **kwargs):
    try:
        return {"result": fn(*args, **kwargs)}
    except Exception as exc:  # noqa: BLE001 — freeze class + message verbatim
        return {"raise": {"python_class": type(exc).__name__, "message": str(exc)}}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

for cid, kw in [
    ("norm_minmax", {"kind": "minmax", "low": 0.0, "high": 10.0}),
    ("norm_ramp", {"kind": "ramp", "low": -2.5, "high": 7.5}),
    ("norm_bad_kind", {"kind": "sigmoid", "low": 0.0, "high": 1.0}),
    ("norm_empty_kind", {"kind": "", "low": 0.0, "high": 1.0}),
    ("norm_nan_low", {"kind": "minmax", "low": float("nan"), "high": 1.0}),
    ("norm_inf_high", {"kind": "ramp", "low": 0.0, "high": float("inf")}),
    ("norm_neg_inf", {"kind": "ramp", "low": float("-inf"), "high": 1.0}),
    ("norm_equal", {"kind": "minmax", "low": 3.0, "high": 3.0}),
    ("norm_inverted", {"kind": "minmax", "low": 5.0, "high": 1.0}),
]:
    add(cid, "normalization_ctor", kw,
        capture(lambda k=kw: Normalization(**k).to_dict()))

for cid, kw, values in [
    ("apply_mid", {"kind": "minmax", "low": 0.0, "high": 10.0},
     [[0.0, 5.0, 10.0], [None, -3.0, 12.0]]),
    ("apply_ramp", {"kind": "ramp", "low": -2.0, "high": 2.0},
     [[-5.0, -2.0, 0.0], [2.0, 5.0, None]]),
    ("apply_all_nan", {"kind": "minmax", "low": 0.0, "high": 1.0},
     [[None, None], [None, None]]),
    ("apply_frac", {"kind": "minmax", "low": 0.25, "high": 0.75},
     [[0.0, 0.5, 1.0], [0.25, 0.75, None]]),
]:
    n = Normalization(**kw)
    arr = np.array(
        [[np.nan if v is None else float(v) for v in row] for row in values]
    )
    add(cid, "normalization_apply", {"normalization": kw, "values": values},
        {"result": _rows(n.apply(arr))})


# ---------------------------------------------------------------------------
# FactorEvidence
# ---------------------------------------------------------------------------

G_A = {
    "grid_z": [[0.2, 0.5, 0.8], [0.1, None, 0.9]],
    "grid_x": [100.0, 200.0, 300.0],
    "grid_y": [10.0, 20.0],
    "factor_name": "砂地比",
    "algorithm_id": "idw",
    "crs": "EPSG:4490",
    "unit": "%",
    "source_refs": ["ver-a1", "ver-a0"],
}

for cid, w in [
    ("ev_ok", 2.5),
    ("ev_zero", 0.0),
    ("ev_negative", -1.5),
    ("ev_nan", float("nan")),
    ("ev_inf", float("inf")),
]:
    inp = {"factor_name": "砂地比", "weight": w,
           "normalization": {"kind": "minmax", "low": 0.0, "high": 100.0},
           "grid": G_A}
    add(cid, "evidence_ctor", inp,
        capture(lambda i=inp: make_evidence(i).to_dict()))


# ---------------------------------------------------------------------------
# FusionRule
# ---------------------------------------------------------------------------

for cid, conds, cname in [
    ("rule_ok", [["砂地比", ">=", 0.6], ["孔隙度", "<", 0.15]], "河道"),
    ("rule_single", [["TOC", ">", 2.0]], "烃源岩"),
    ("rule_empty", [], "空"),
    ("rule_bad_len", [["砂地比", ">=", 0.6, "extra"]], "X"),
    ("rule_bad_op", [["砂地比", "!=", 0.5]], "X"),
    ("rule_nan_thr", [["砂地比", ">=", float("nan")]], "X"),
    ("rule_inf_thr", [["砂地比", ">=", float("inf")]], "X"),
    ("rule_str_thr", [["砂地比", ">=", "0.5"]], "X"),
    ("rule_bool_thr", [["砂地比", "==", True]], "X"),
    ("rule_int_thr", [["孔隙度", "<=", 20]], "泥岩"),
]:
    inp = {"conditions": conds, "class_name": cname}
    add(cid, "rule_ctor", inp,
        capture(lambda i=inp: FusionRule(
            conditions=tuple(tuple(c) for c in i["conditions"]),
            class_name=i["class_name"]).to_dict()))

for cid, data in [
    ("rfd_ok", {"conditions": [["砂地比", ">=", 0.6]], "class_name": "河道"}),
    ("rfd_coerce", {"conditions": [[123, 456, "0.5"]], "class_name": 789}),
    ("rfd_missing_conds", {"class_name": "X"}),
    ("rfd_bad_item", {"conditions": [["a", ">=", 1, 2]], "class_name": "X"}),
    ("rfd_unconvertible", {"conditions": [["a", ">=", "xyz"]], "class_name": "X"}),
    ("rfd_nulls", {"conditions": None, "class_name": "X"}),
]:
    add(cid, "rule_from_dict", {"data": data},
        capture(lambda d=data: FusionRule.from_dict(d).to_dict()))


# ---------------------------------------------------------------------------
# FusionModel ctor / to_dict / from_dict / fingerprint
# ---------------------------------------------------------------------------

EV_A = {"factor_name": "砂地比", "weight": 2.0,
        "normalization": {"kind": "minmax", "low": 0.0, "high": 1.0},
        "grid": G_A}
EV_B = {"factor_name": "孔隙度", "weight": 1.0,
        "normalization": {"kind": "minmax", "low": 0.0, "high": 0.3},
        "grid": {
            "grid_z": [[0.12, 0.2, 0.28], [None, 0.05, 0.15]],
            "grid_x": [100.0, 200.0, 300.0],
            "grid_y": [10.0, 20.0],
            "factor_name": "孔隙度",
            "algorithm_id": "kriging",
            "crs": "EPSG:4490",
            "unit": "%",
            "source_refs": ["ver-b1"],
            "variance_grid": [[0.01, 0.02, 0.01], [None, 0.03, 0.02]],
        }}

for cid, spec, evs in [
    ("model_weighted", {"name": "复合判据", "kind": "weighted_evidence",
                        "class_thresholds": [0.35, 0.7],
                        "class_names": ["低", "中", "高"]}, [EV_A, EV_B]),
    ("model_rule", {"name": "规则判据", "kind": "rule_based",
                    "rules": [{"conditions": [["砂地比", ">=", 0.6]],
                               "class_name": "河道"}],
                    "default_class": "泥岩"}, [EV_A]),
    ("model_bad_kind", {"name": "x", "kind": "magic"}, []),
    ("model_w_no_ev", {"name": "x", "kind": "weighted_evidence",
                       "class_names": ["a"], "class_thresholds": []}, []),
    ("model_r_no_rules", {"name": "x", "kind": "rule_based"}, [EV_A]),
    ("model_w_no_names", {"name": "x", "kind": "weighted_evidence",
                          "class_thresholds": [0.5]}, [EV_A]),
    ("model_w_thr_len", {"name": "x", "kind": "weighted_evidence",
                         "class_thresholds": [0.3, 0.6, 0.9],
                         "class_names": ["a", "b"]}, [EV_A]),
    ("model_provenance", {"name": "复合判据", "kind": "weighted_evidence",
                          "class_thresholds": [0.5],
                          "class_names": ["低", "高"],
                          "weight_provenance": {"actor": "expert",
                                                "policy": "manual-v2"}},
     [EV_A]),
    ("model_single_class", {"name": "x", "kind": "weighted_evidence",
                            "class_names": ["全部"]}, [EV_A]),
]:
    inp = {"model": spec, "evidences": evs}
    add(cid, "model_ctor", inp,
        capture(lambda s=spec, e=evs: make_model(s, [make_evidence(x) for x in e]).to_dict()))

for cid, spec, evs in [
    ("fp_weighted", {"name": "复合判据", "kind": "weighted_evidence",
                     "class_thresholds": [0.35, 0.7],
                     "class_names": ["低", "中", "高"]}, [EV_A, EV_B]),
    ("fp_rule", {"name": "规则判据", "kind": "rule_based",
                 "rules": [{"conditions": [["砂地比", ">=", 0.6]],
                            "class_name": "河道"}]}, [EV_A]),
    ("fp_provenance", {"name": "复合判据", "kind": "weighted_evidence",
                       "class_thresholds": [0.5], "class_names": ["低", "高"],
                       "weight_provenance": {"actor": "expert", "notes": "péng"}},
     [EV_A]),
]:
    inp = {"model": spec, "evidences": evs}
    add(cid, "model_fingerprint", inp,
        capture(lambda s=spec, e=evs: make_model(s, [make_evidence(x) for x in e]).fingerprint()))

MODEL_DICT = make_model(
    {"name": "复合判据", "kind": "weighted_evidence",
     "class_thresholds": [0.5], "class_names": ["低", "高"]},
    [make_evidence(EV_A)],
).to_dict()
for cid, grids in [
    ("mfd_ok", {"砂地比": G_A}),
    ("mfd_missing", {}),
    ("mfd_other_key", {"孔隙度": G_A}),
]:
    add(cid, "model_from_dict", {"data": MODEL_DICT, "grids": grids},
        capture(lambda d=MODEL_DICT, g=grids: FusionModel.from_dict(
            d, grids={k: make_grid(v) for k, v in g.items()}).to_dict()))


# ---------------------------------------------------------------------------
# fuse — weighted
# ---------------------------------------------------------------------------

G_A2 = dict(G_A)  # declared-crs twin for axis/shape tests
G_DIFF_SHAPE = dict(G_A, grid_z=[[0.5, 0.5]], grid_x=[1.0, 2.0], grid_y=[1.0])
G_DIFF_AXES = dict(G_A, grid_x=[101.0, 200.0, 300.0])
G_NO_CRS = dict(G_A, crs=None)
G_OTHER_CRS = dict(G_A, crs="EPSG:4326")
G_FRAC_UNIT = dict(G_A, unit="1", grid_z=[[0.2, 0.5, 0.8], [0.1, None, 0.9]])
G_PCT_VALUES = dict(G_A, unit="%", grid_z=[[20.0, 50.0, 80.0], [10.0, None, 90.0]],
                    factor_name="porosity")
G_MIXED_SPAN = dict(G_A, unit="%", grid_z=[[0.2, 50.0, 80.0], [0.1, None, 90.0]])
G_PCT_NORM_BOUNDS = dict(G_A, unit="percent")
G_INT_PCT = dict(G_A, grid_z=[[0.0, 1.0, 0.0], [1.0, None, 0.0]])
G_ALL_NAN = dict(G_A, grid_z=[[None, None, None], [None, None, None]])
G_VAR2 = dict(EV_B["grid"], variance_grid=[[0.02, 0.01, 0.03], [0.01, None, 0.02]])
G_CONFLICT = dict(G_A, grid_z=[[0.9, 0.9, 0.9], [0.9, 0.9, 0.9]])
G_CONFLICT2 = dict(EV_B["grid"], grid_z=[[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])


def wspec(**kw):
    return {"name": kw.pop("name", "复合判据"), "kind": "weighted_evidence",
            "class_thresholds": kw.pop("class_thresholds", [0.35, 0.7]),
            "class_names": kw.pop("class_names", ["低", "中", "高"]), **kw}


def ev(name, weight, low, high, grid, kind="minmax"):
    return {"factor_name": name, "weight": weight,
            "normalization": {"kind": kind, "low": low, "high": high},
            "grid": grid}


fuse_cases = [
    ("fw_two_factor", wspec(), [ev("砂地比", 2.0, 0.0, 1.0, G_A),
                              ev("孔隙度", 1.0, 0.0, 0.3, EV_B["grid"])]),
    ("fw_single", wspec(class_thresholds=[0.5], class_names=["低", "高"]),
     [ev("砂地比", 1.0, 0.0, 1.0, G_A)]),
    ("fw_all_nan", wspec(), [ev("砂地比", 1.0, 0.0, 1.0, G_ALL_NAN),
                             ev("孔隙度", 1.0, 0.0, 0.3, G_ALL_NAN)]),
    ("fw_var_none", wspec(), [ev("砂地比", 1.0, 0.0, 1.0, G_A)]),
    ("fw_var_mixed", wspec(), [ev("砂地比", 1.0, 0.0, 1.0, G_A),
                               ev("孔隙度", 1.0, 0.0, 0.3, G_VAR2)]),
    ("fw_var_both", wspec(),
     [ev("砂地比", 2.0, 0.0, 1.0,
         dict(G_A, variance_grid=[[0.01, 0.02, 0.01], [0.03, None, 0.01]])),
      ev("孔隙度", 1.0, 0.0, 0.3, G_VAR2)]),
    ("fw_conflict", wspec(), [ev("砂地比", 1.0, 0.0, 1.0, G_CONFLICT),
                              ev("孔隙度", 1.0, 0.0, 0.3, G_CONFLICT2)]),
    ("fw_no_crs", wspec(), [ev("砂地比", 1.0, 0.0, 1.0, G_NO_CRS),
                            ev("孔隙度", 1.0, 0.0, 0.3, dict(EV_B["grid"], crs=None))]),
    ("fw_shape_mismatch", wspec(), [ev("砂地比", 1.0, 0.0, 1.0, G_A),
                                    ev("孔隙度", 1.0, 0.0, 0.3, G_DIFF_SHAPE)]),
    ("fw_axes_mismatch", wspec(), [ev("砂地比", 1.0, 0.0, 1.0, G_A),
                                   ev("孔隙度", 1.0, 0.0, 0.3, G_DIFF_AXES)]),
    ("fw_crs_mixed_decl", wspec(), [ev("砂地比", 1.0, 0.0, 1.0, G_A),
                                     ev("孔隙度", 1.0, 0.0, 0.3, G_NO_CRS)]),
    ("fw_crs_mixed_decl_rev", wspec(), [ev("砂地比", 1.0, 0.0, 1.0, G_NO_CRS),
                                         ev("孔隙度", 1.0, 0.0, 0.3, G_A)]),
    ("fw_crs_different", wspec(), [ev("砂地比", 1.0, 0.0, 1.0, G_A),
                                    ev("孔隙度", 1.0, 0.0, 0.3, G_OTHER_CRS)]),
    ("fw_unit_pct_bounds", wspec(), [ev("孔隙度", 1.0, 0.0, 1.0, G_PCT_NORM_BOUNDS)]),
    ("fw_unit_frac_values", wspec(), [ev("砂地比", 1.0, 0.0, 1.0, G_A)]),
    ("fw_unit_pct_values", wspec(), [ev("孔隙度", 1.0, 0.0, 100.0, G_PCT_VALUES)]),
    ("fw_unit_mixed_span", wspec(), [ev("砂地比", 1.0, 0.0, 100.0, G_MIXED_SPAN)]),
    ("fw_unit_dim_warn", wspec(), [ev("probability", 1.0, 0.0, 100.0, G_PCT_VALUES
                                     | {"unit": "1"})]),
    ("fw_single_class", wspec(class_names=["全部"], class_thresholds=[]),
     [ev("砂地比", 1.0, 0.0, 1.0, G_A)]),
    ("fw_ramp_norm", wspec(), [ev("砂地比", 1.0, -0.5, 1.5, G_A, kind="ramp")]),
    ("fw_weights_extreme", wspec(), [ev("砂地比", 1000.0, 0.0, 1.0, G_A),
                                     ev("孔隙度", 1e-6, 0.0, 0.3, EV_B["grid"])]),
]
for cid, spec, evs in fuse_cases:
    inp = {"model": spec, "evidences": evs}
    add(cid, "fuse", inp,
        capture(lambda s=spec, e=evs: freeze_result(fuse(
            make_model(s, [make_evidence(x) for x in e])))))


# ---------------------------------------------------------------------------
# fuse — rule_based
# ---------------------------------------------------------------------------

rule_cases = [
    ("fr_ordered", {"name": "规则判据", "kind": "rule_based",
                    "rules": [
                        {"conditions": [["砂地比", ">=", 0.6]], "class_name": "河道"},
                        {"conditions": [["砂地比", ">=", 0.4]], "class_name": "漫滩"},
                        {"conditions": [["孔隙度", "<", 0.15]], "class_name": "致密"},
                    ], "default_class": "泥岩"},
     [ev("砂地比", 1.0, 0.0, 1.0, G_A), ev("孔隙度", 1.0, 0.0, 0.3, EV_B["grid"])]),
    ("fr_multi_cond", {"name": "x", "kind": "rule_based",
                       "rules": [{"conditions": [["砂地比", ">=", 0.6],
                                                 ["孔隙度", "<=", 0.2]],
                                  "class_name": "好储层"}]},
     [ev("砂地比", 1.0, 0.0, 1.0, G_A), ev("孔隙度", 1.0, 0.0, 0.3, EV_B["grid"])]),
    ("fr_all_nan", {"name": "x", "kind": "rule_based",
                    "rules": [{"conditions": [["砂地比", ">=", 0.5]],
                               "class_name": "A"}]},
     [ev("砂地比", 1.0, 0.0, 1.0, G_ALL_NAN)]),
    ("fr_unknown_factor", {"name": "x", "kind": "rule_based",
                           "rules": [{"conditions": [["未存在", ">=", 0.5]],
                                      "class_name": "A"}]},
     [ev("砂地比", 1.0, 0.0, 1.0, G_A)]),
    ("fr_same_class", {"name": "x", "kind": "rule_based",
                       "rules": [{"conditions": [["砂地比", ">=", 0.9]],
                                  "class_name": "同名"},
                                 {"conditions": [["砂地比", ">=", 0.4]],
                                  "class_name": "同名"}]},
     [ev("砂地比", 1.0, 0.0, 1.0, G_A)]),
    ("fr_eq_op", {"name": "x", "kind": "rule_based",
                  "rules": [{"conditions": [["砂地比", "==", 0.5]],
                             "class_name": "半"},
                            {"conditions": [["砂地比", "==", 0.5 + 5e-13]],
                             "class_name": "半ε"},
                            {"conditions": [["砂地比", "==", 0.51]],
                             "class_name": "五一"}]},
     [ev("砂地比", 1.0, 0.0, 1.0, G_A)]),
    ("fr_no_evidences", {"name": "x", "kind": "rule_based",
                         "rules": [{"conditions": [["砂地比", ">=", 0.5]],
                                    "class_name": "A"}]}, []),
    ("fr_no_crs", {"name": "x", "kind": "rule_based",
                   "rules": [{"conditions": [["砂地比", ">=", 0.5]],
                              "class_name": "A"}]},
     [ev("砂地比", 1.0, 0.0, 1.0, G_NO_CRS)]),
    ("fr_dup_factor", {"name": "x", "kind": "rule_based",
                       "rules": [{"conditions": [["砂地比", ">=", 0.5]],
                                  "class_name": "A"}]},
     [ev("砂地比", 1.0, 0.0, 1.0, G_A),
      ev("砂地比", 1.0, 0.0, 1.0, dict(G_A, grid_z=[[0.9] * 3, [0.9] * 3]))]),
]
for cid, spec, evs in rule_cases:
    inp = {"model": spec, "evidences": evs}
    add(cid, "fuse", inp,
        capture(lambda s=spec, e=evs: freeze_result(fuse(
            make_model(s, [make_evidence(x) for x in e])))))


# ---------------------------------------------------------------------------
# _aligned_or_raise direct
# ---------------------------------------------------------------------------

for cid, specs in [
    ("align_ok", [G_A, EV_B["grid"]]),
    ("align_both_none", [G_NO_CRS, dict(EV_B["grid"], crs=None)]),
    ("align_shape", [G_A, G_DIFF_SHAPE]),
    ("align_axes", [G_A, G_DIFF_AXES]),
    ("align_mixed_ab", [G_A, G_NO_CRS]),
    ("align_mixed_ba", [G_NO_CRS, G_A]),
    ("align_diff_crs", [G_A, G_OTHER_CRS]),
    ("align_empty", []),
]:
    add(cid, "aligned_or_raise", {"grids": specs},
        capture(lambda g=specs: _aligned_or_raise([make_grid(x) for x in g])))


# ---------------------------------------------------------------------------
# sensitivity_report
# ---------------------------------------------------------------------------

for cid, spec, evs in [
    ("sens_two", wspec(), [ev("砂地比", 2.0, 0.0, 1.0, G_A),
                           ev("孔隙度", 1.0, 0.0, 0.3, EV_B["grid"])]),
    ("sens_three", wspec(),
     [ev("砂地比", 2.0, 0.0, 1.0, G_A),
      ev("孔隙度", 1.0, 0.0, 0.3, EV_B["grid"]),
      ev("TOC", 0.5, 0.0, 5.0,
         dict(G_A, factor_name="TOC",
              grid_z=[[1.0, 3.0, 2.0], [0.5, None, 4.0]]))]),
    ("sens_single", wspec(class_thresholds=[0.5], class_names=["低", "高"]),
     [ev("砂地比", 1.0, 0.0, 1.0, G_A)]),
    ("sens_rule", {"name": "x", "kind": "rule_based",
                   "rules": [{"conditions": [["砂地比", ">=", 0.5]],
                              "class_name": "A"}]},
     [ev("砂地比", 1.0, 0.0, 1.0, G_A)]),
    ("sens_provenance", wspec(weight_provenance={"actor": "e"}),
     [ev("砂地比", 2.0, 0.0, 1.0, G_A),
      ev("孔隙度", 1.0, 0.0, 0.3, EV_B["grid"])]),
]:
    def _sens(s=spec, e=evs):
        m = make_model(s, [make_evidence(x) for x in e])
        return sensitivity_report(m, fuse(m))
    inp = {"model": spec, "evidences": evs}
    add(cid, "sensitivity", inp, capture(_sens))


# ---------------------------------------------------------------------------
# factor_units
# ---------------------------------------------------------------------------

for cid, name in [
    ("key_plain", "porosity"), ("key_upper", "POROSITY"), ("key_ws", "  孔隙度  "),
    ("key_mixed", "Phie"), ("key_alias", "H_pay"), ("key_empty", ""),
    ("key_ws_only", "   "), ("key_umlaut", "PÖR"), ("key_sharp_s", "SS"),
    ("key_turkish", "İ"), ("key_ligature", "ǄHP"),
]:
    add(cid, "normalize_key", {"name": name},
        {"result": fu.normalize_factor_key(name)})

for cid, name in [
    ("unit_cn", "孔隙度"), ("unit_en", "permeability"), ("unit_case", "PERM"),
    ("unit_alias", "H_pay"), ("unit_family", "water_depth"),
    ("unit_unknown", "神秘因子"), ("unit_none", "xxx"),
    ("unit_prob_cn", "概率"), ("unit_toc", "toc"),
]:
    add(cid, "unit_for_factor", {"name": name},
        {"result": fu.unit_for_factor(name)})

for cid, name in [
    ("ramp_cn", "砂岩厚度"), ("ramp_case", "TOC"), ("ramp_unknown", "xyz"),
    ("ramp_alias", "PALEO_WATER_DEPTH"),
]:
    add(cid, "color_ramp_for_factor", {"name": name},
        {"result": fu.color_ramp_for_factor(name)})

for cid, name, unit, values in [
    ("vu_pct_fraction", "孔隙度", "%", [[0.2, 0.5], [0.8, None]]),
    ("vu_pct_mixed", "孔隙度", "%", [[0.2, 50.0], [80.0, None]]),
    ("vu_pct_ok", "孔隙度", "%", [[20.0, 50.0], [80.0, None]]),
    ("vu_pct_ints", "砂地比", "%", [[0.0, 1.0], [0.0, None]]),
    ("vu_percent_word", "孔隙度", "percent", [[0.2, 0.5], [None, None]]),
    ("vu_dim_warn", "probability", "1", [[20.0, 50.0], [None, None]]),
    ("vu_dim_lo_edge", "probability", "1", [[1.5, 2.0], [None, None]]),
    ("vu_dim_hi_edge", "probability", "v/v", [[0.9, 1.6], [None, None]]),
    ("vu_dim_ok", "probability", "fraction", [[0.2, 0.9], [None, None]]),
    ("vu_m_unit", "顶界深度", "m", [[1000.0, 2000.0], [None, None]]),
    ("vu_none_unit", "孔隙度", None, [[0.5, 0.6], [None, None]]),
    ("vu_all_nan", "孔隙度", "%", [[None, None], [None, None]]),
    ("vu_ws_unit", "孔隙度", " % ", [[0.2, 0.5], [None, None]]),
    ("vu_pct_edge_15", "孔隙度", "%", [[1.5, 1.5], [None, None]]),
]:
    arr = np.array(
        [[np.nan if v is None else float(v) for v in row] for row in values]
    )
    add(cid, "validate_unit", {"factor_name": name, "unit": unit, "values": values},
        {"result": fu.validate_factor_unit_against_values(name, unit, arr)})


# ---------------------------------------------------------------------------
# generated data: FACTOR_DEFAULTS / FACTOR_FAMILIES / lower() map
# ---------------------------------------------------------------------------

def _esc(text: str) -> str:
    """UTF-8 bytes as C++ narrow-string \\xNN escapes (byte-exact)."""
    return "".join(f"\\x{b:02X}" for b in text.encode("utf-8"))


def _emit_units_inc() -> None:
    lines = ["// Generated by tools/oracle/generate_factor_fusion_fixtures.py — do not edit.",
             "// FACTOR_DEFAULTS + FACTOR_FAMILIES (insertion order preserved).",
             "static const FactorUnitEntry kFactorDefaults[] = {"]
    for key, entry in fu.FACTOR_DEFAULTS.items():
        lines.append(
            f'    {{"{_esc(key)}", "{_esc(entry["unit"])}", '
            f'"{_esc(entry["color_ramp"])}"}},'
        )
    lines.append("};")
    lines.append("")
    lines.append("static const FactorFamily kFactorFamilies[] = {")
    for family, aliases in fu.FACTOR_FAMILIES.items():
        alias_list = ", ".join(f'"{_esc(a)}"' for a in aliases)
        lines.append(f'    {{"{_esc(family)}", {{{alias_list}}}}},')
    lines.append("};")
    lines.append("")
    INC.write_text("\n".join(lines), encoding="utf-8")


def _emit_lower_inc() -> None:
    # Unicode code points whose lower() result differs from the char itself.
    entries = []
    for cp in range(0x110000):
        ch = chr(cp)
        low = ch.lower()
        if low != ch:
            entries.append((cp, low))
    lines = ["// Generated by tools/oracle/generate_factor_fusion_fixtures.py — do not edit.",
             "// str.lower() map: code point -> lowered UTF-8 bytes (only entries",
             "// where lower() differs from identity).",
             "static const std::pair<char32_t, const char*> kLowerMap[] = {"]
    for cp, low in entries:
        esc = "".join(f"\\x{b:02X}" for b in low.encode("utf-8"))
        literal = f"\\u{cp:04X}" if cp <= 0xFFFF else f"\\U{cp:08X}"
        lines.append(f"    {{U'{literal}', \"{esc}\"}},")
    lines.append("};")
    lines.append("")
    LOWER_INC.write_text("\n".join(lines), encoding="utf-8")


_emit_units_inc()
_emit_lower_inc()


def clean(obj):
    """Strict-JSON-safe: non-finite floats -> "NaN"/"Infinity"/"-Infinity"
    sentinels (factor_host precedent); the C++ runner decodes them back on
    numeric reads."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        if math.isnan(obj):
            return "NaN"
        return "Infinity" if obj > 0 else "-Infinity"
    return obj


payload = {
    "meta": {
        "generator": "tools/oracle/generate_factor_fusion_fixtures.py",
        "source": "paleo_workbench/workflow/factor_fusion.py + factor_units.py",
        "cases": len(cases),
    },
    "cases": clean(cases),
}
FIXTURE.parent.mkdir(parents=True, exist_ok=True)
FIXTURE.write_text(
    json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
)
print(f"wrote {len(cases)} cases -> {FIXTURE}")
print(f"units table -> {INC}")
print(f"lower map -> {LOWER_INC}")
