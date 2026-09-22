#!/usr/bin/env python3
"""Oracle for normalize_factor_samples (sample_normalization.py, M7)."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.workflow.sample_normalization import (  # noqa: E402
    DEFAULT_DUPLICATE_POLICY,
    duplicate_policy_from_params,
    normalize_factor_samples,
)

OUT = (
    REPO_ROOT
    / "libs"
    / "mapping_kernel"
    / "mapping_kernel_tests"
    / "fixtures"
)

TWIN_A = {"x": 1.0, "y": 2.0, "value": 10.0, "well_id": "w1"}
TWIN_B = {"x": 1.0, "y": 2.0, "value": 20.0, "well_id": "w2"}
OTHER = {"x": 3.0, "y": 4.0, "value": 30.0, "well_id": "w3"}


def _num(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def _points_json(points):
    out = []
    for p in points:
        rec = {}
        for k, v in p.items():
            rec[k] = _num(v) if isinstance(v, float) else v
        out.append(rec)
    return out


def _run(cid, pts, policy="mean"):
    try:
        points, report = normalize_factor_samples(pts, policy=policy)
        return {
            "id": cid,
            "policy": policy,
            "input": pts,
            "ok": True,
            "points": _points_json(points),
            "report": report.to_dict(),
        }
    except ValueError as exc:
        return {
            "id": cid,
            "policy": policy,
            "input": pts,
            "ok": False,
            "error": str(exc),
        }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    flagged = {**TWIN_A, "qc_flag": "suspect"}
    a = {**TWIN_A, "q": 2.0, "b_i": 4.0}
    b = {**TWIN_B, "q": 4.0, "b_i": 8.0}
    cases = [
        _run("mean_twins", [TWIN_A, TWIN_B, OTHER]),
        _run("first_twins", [TWIN_A, TWIN_B, OTHER], "first"),
        _run("error_twins", [TWIN_A, TWIN_B], "error"),
        _run("error_clean", [TWIN_A, OTHER], "error"),
        _run("keep_twins", [TWIN_A, TWIN_B], "keep"),
        _run("nonfinite", [
            {"x": math.inf, "y": 0.0, "value": 1.0},
            {"x": 0.0, "y": 0.0, "value": math.nan},
            OTHER,
        ]),
        _run("qc_worst_flag", [flagged, TWIN_B, OTHER]),
        _run("lnglat", [{"lng": 5.0, "lat": 6.0, "z": 7.0}]),
        _run("unknown_policy", [OTHER], "median"),
        _run("numeric_extras", [a, b, OTHER]),
        _run("empty", []),
        _run("z_key", [{"x": 1.0, "y": 1.0, "z": 9.0}]),
        _run("v_key", [{"x": 1.0, "y": 1.0, "v": 8.0}]),
        _run("name_join", [
            {"x": 0.0, "y": 0.0, "value": 1.0, "name": "a"},
            {"x": 0.0, "y": 0.0, "value": 3.0, "well_id": "b"},
        ]),
    ]
    params = {
        "none": duplicate_policy_from_params(None),
        "empty": duplicate_policy_from_params({}),
        "error": duplicate_policy_from_params({"duplicate_policy": "error"}),
        "median": duplicate_policy_from_params({"duplicate_policy": "median"}),
        "default": DEFAULT_DUPLICATE_POLICY,
    }
    # JSON cannot store inf in input; rewrite nonfinite input with sentinels.
    for c in cases:
        cleaned = []
        for rec in c["input"]:
            item = {}
            for k, v in rec.items():
                if isinstance(v, float) and not math.isfinite(v):
                    item[k] = None if math.isnan(v) else "inf"
                else:
                    item[k] = v
            cleaned.append(item)
        c["input"] = cleaned

    target = OUT / "sample_norm_oracle.json"
    target.write_text(
        json.dumps({"cases": cases, "params": params}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"wrote {target} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
