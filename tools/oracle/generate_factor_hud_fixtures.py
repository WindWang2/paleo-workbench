#!/usr/bin/env python3
"""Oracle for the conv-16 factor statistics HUD (platform.factor_hud).

Freezes, against the REAL Python modules:
* ``GridStatistics.from_grid`` / ``FactorGridResult.statistics``
  (paleo_workbench.workflow.factor_grid_result) — the exact numbers the C++
  dock must display;
* the user-facing text the C++ FactorStatsDock must render, formatted with
  the same ``:g`` vocabulary the workstation inspector uses for the factor
  grid rows (``f"{min:g} ~ {max:g}"``, tests/test_inspector_v7.py).

No expected value is hand-written: every number and every display string in
the fixture is produced by the real Python module / real f-string formatting.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.workflow.factor_grid_result import (  # noqa: E402
    FactorGridResult,
    GridStatistics,
)


def _cells(arr) -> list:
    flat = np.asarray(arr, dtype=np.float32).reshape(-1)
    return [None if not math.isfinite(float(v)) else float(v) for v in flat]


def _g(value: float) -> str:
    """The workstation factor-row format (inspector.py: f"{v:g}")."""
    return f"{value:g}"


def _display(stats: GridStatistics) -> dict:
    finite_range = (
        math.isfinite(stats.min)
        and math.isfinite(stats.max)
        and stats.valid_count > 0
    )
    return {
        "factor": "砂岩厚度",
        "range": (
            f"{_g(stats.min)} ~ {_g(stats.max)}" if finite_range else "—"
        ),
        "mean": _g(stats.mean) if math.isfinite(stats.mean) else "—",
        "std": _g(stats.std) if math.isfinite(stats.std) else "—",
        "valid_count": f"{stats.valid_count} / {stats.total_count}",
    }


def _payload(stats: GridStatistics) -> dict:
    return {
        "min": stats.min if math.isfinite(stats.min) else None,
        "max": stats.max if math.isfinite(stats.max) else None,
        "mean": stats.mean if math.isfinite(stats.mean) else None,
        "std": stats.std if math.isfinite(stats.std) else None,
        "valid_count": stats.valid_count,
        "total_count": stats.total_count,
    }


def _stats_payload(arr) -> dict:
    return _payload(
        GridStatistics.from_grid(np.asarray(arr, dtype=np.float32))
    )


def _case(id_: str, arr, *, via_factor_grid: bool = False) -> dict:
    if via_factor_grid:
        arr = np.asarray(arr, dtype=np.float32)
        height, width = arr.shape
        grid_x = np.linspace(0.0, float(width - 1), width)
        grid_y = np.linspace(10.0, 10.0 + float(height - 1), height)
        result = FactorGridResult(
            grid_z=arr,
            grid_x=grid_x,
            grid_y=grid_y,
            factor_name="砂岩厚度",
            algorithm_id="idw",
            unit="m",
        )
        payload = _payload(result.statistics)
    else:
        payload = _stats_payload(arr)
    return {
        "id": id_,
        "cells": _cells(arr),
        "stats": payload,
        "display": _display(
            GridStatistics(
                min=payload["min"] if payload["min"] is not None else math.nan,
                max=payload["max"] if payload["max"] is not None else math.nan,
                mean=payload["mean"] if payload["mean"] is not None else math.nan,
                std=payload["std"] if payload["std"] is not None else math.nan,
                valid_count=payload["valid_count"],
                total_count=payload["total_count"],
            )
        ),
    }


def main() -> None:
    out_dir = REPO_ROOT / "tests" / "cpp" / "platform" / "fixtures" / "factor_hud"
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = [
        _case("seq_2x2", [[1.0, 2.0], [3.0, 4.0]]),
        _case("with_nan", [[1.0, np.nan], [3.0, 5.0]]),
        _case("all_nan", [[np.nan, np.nan], [np.nan, np.nan]]),
        _case("with_inf", [[1.0, np.inf], [-2.0, 4.0]]),
        _case("single_cell", [[7.5]]),
        _case("empty_grid", np.zeros((0, 0), dtype=np.float32)),
        _case("constant_field", [[2.0, 2.0], [2.0, 2.0]]),
        _case("negatives", [[-4.0, -1.0], [0.0, 3.0]]),
        _case("float32_rounding", [[0.1, 0.2], [0.3, 0.7]]),
        _case("large_magnitude_g", [[1234567.0, 0.0001]]),
        _case(
            "via_factor_grid_result",
            [[10.0, 220.5, 47.25], [np.nan, 88.0, 3.5]],
            via_factor_grid=True,
        ),
    ]
    target = out_dir / "oracle.json"
    target.write_text(
        json.dumps({"cases": cases}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(f"wrote {target} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
