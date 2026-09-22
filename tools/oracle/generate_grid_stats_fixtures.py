#!/usr/bin/env python3
"""Oracle for GridStatistics.from_grid (factor_grid_result.py, M7)."""

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

from paleo_workbench.workflow.factor_grid_result import GridStatistics  # noqa: E402

OUT = (
    REPO_ROOT
    / "libs"
    / "mapping_kernel"
    / "mapping_kernel_tests"
    / "fixtures"
)


def _cells(arr: np.ndarray) -> list:
    flat = np.asarray(arr, dtype=np.float32).reshape(-1)
    return [None if not math.isfinite(float(v)) else float(v) for v in flat]


def _stats(arr: np.ndarray) -> dict:
    s = GridStatistics.from_grid(np.asarray(arr, dtype=np.float32))
    return {
        "min": None if not math.isfinite(s.min) else float(s.min),
        "max": None if not math.isfinite(s.max) else float(s.max),
        "mean": None if not math.isfinite(s.mean) else float(s.mean),
        "std": None if not math.isfinite(s.std) else float(s.std),
        "valid_count": int(s.valid_count),
        "total_count": int(s.total_count),
        "to_dict": s.to_dict(),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = [
        {"id": "seq_2x2", "cells": _cells([[1.0, 2.0], [3.0, 4.0]]),
         "stats": _stats([[1.0, 2.0], [3.0, 4.0]])},
        {"id": "with_nan", "cells": _cells([[1.0, np.nan], [3.0, 5.0]]),
         "stats": _stats([[1.0, np.nan], [3.0, 5.0]])},
        {"id": "all_nan", "cells": _cells([[np.nan, np.nan], [np.nan, np.nan]]),
         "stats": _stats([[np.nan, np.nan], [np.nan, np.nan]])},
        {"id": "with_inf", "cells": _cells([[1.0, np.inf], [-2.0, 4.0]]),
         "stats": _stats([[1.0, np.inf], [-2.0, 4.0]])},
        {"id": "single", "cells": _cells([[7.5]]),
         "stats": _stats([[7.5]])},
        {"id": "empty", "cells": [],
         "stats": _stats(np.zeros((0, 0), dtype=np.float32))},
        {"id": "constant", "cells": _cells([[2.0, 2.0], [2.0, 2.0]]),
         "stats": _stats([[2.0, 2.0], [2.0, 2.0]])},
        {"id": "negatives", "cells": _cells([[-4.0, -1.0], [0.0, 3.0]]),
         "stats": _stats([[-4.0, -1.0], [0.0, 3.0]])},
    ]
    target = OUT / "grid_stats_oracle.json"
    target.write_text(json.dumps({"cases": cases}, ensure_ascii=False),
                      encoding="utf-8")
    print(f"wrote {target} ({len(cases)} cases)")


if __name__ == "__main__":
    main()
