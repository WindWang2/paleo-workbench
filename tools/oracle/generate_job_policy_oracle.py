#!/usr/bin/env python3
"""CONV-30 — freeze the job policy oracle from the REAL Python runtime.

Generates job_policy_oracle.json for libs/job_runtime/job_runtime_tests:
the category policy ladder and kind→category mapping come verbatim from
paleo_workbench.runtime.task_categories (the production source of truth);
the aging series and the supersede decision table come from the frozen
TaskScheduler formulas/contracts (task_scheduler.py, #1224). The C++ test
(job_runtime.policy_oracle) replays every row and runs a negative
self-check over deliberate perturbations.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import _legacy_reference

_legacy_reference.ensure_legacy_reference()  # archived-reference shim

from paleo_workbench.runtime.task_categories import (  # noqa: E402
    CATEGORY_POLICIES,
    TaskCategory,
    category_for_kind,
    policy_for,
)

# TaskScheduler aging constants (frozen in task_scheduler.py).
AGING_INTERVAL_S = 5.0
AGING_STEP = 5
AGING_MAX_BOOST = 50


def effective_priority(base: int, wait_s: float) -> int:
    """Python TaskScheduler._effective_priority (floor/step/cap formula)."""
    boost = min(int(wait_s // AGING_INTERVAL_S) * AGING_STEP, AGING_MAX_BOOST)
    return base + boost


def main() -> int:
    policies = []
    for category in TaskCategory:
        p = policy_for(category)
        policies.append(
            {
                "category": category.value,
                "base_priority": p.base_priority,
                "interactive": p.interactive,
                "io_weight": p.io_weight,
                "default_cpu_cores": p.default_cpu_cores,
            }
        )

    probe_kinds = [
        "interactive.render",
        "interactive.query",
        "render.frame",
        "query.catalog",
        "preview.waveform",
        "seismic.transcode",
        "seismic.attribute",
        "prediction.inference",
        "inference.tile",
        "export.map",
        "verify.catalog",
        "scan.volume",
        "index.documents",
        "maintenance.gc",
        "background.compute",
        "background.io",
        "io",
        "transcode",
        "seismic.slice",
        "RENDER",
        "Seismic.Attribute",
        "prediction",
        "unknown.kind",
        "",
    ]
    kind_mappings = [
        {"kind": kind, "category": category_for_kind(kind).value}
        for kind in probe_kinds
    ]

    aging = []
    for base in (0, 10, 40, 100):
        for wait_s in (0.0, 2.5, 4.999, 5.0, 5.001, 9.999, 10.0, 30.0, 59.999,
                       60.0, 100.0):
            aging.append(
                {
                    "base_priority": base,
                    "wait_s": wait_s,
                    "effective": effective_priority(base, wait_s),
                }
            )

    # #1224 supersede decision table (submit against an active task_key).
    # Messages are the exact Python ValueError strings INCLUDING the
    # key prefix (task_scheduler.py submit()); the Chinese variant is only
    # for a RUNNING predecessor — cancelling falls to the generic text.
    probe_key = "k"
    supersede = [
        {"active_state": "queued", "decision": "supersede",
         "old_terminal": "cancelled", "unwinds_on_cancel": True,
         "message": ""},
        {"active_state": "running", "decision": "reject",
         "message": "task with key '" + probe_key + "' "
                    "正在运行且尚未退出（已请求取消的旧任务需先实际结束）"},
        {"active_state": "cancelling", "decision": "reject",
         "message": "task with key '" + probe_key + "' "
                    "is already queued or running"},
    ]

    oracle = {
        "schema": "pwb.job_policy_oracle/1",
        "source": "paleo_workbench/runtime/task_categories.py + "
                  "runtime/task_scheduler.py (aging + #1224 supersede)",
        "aging_interval_s": AGING_INTERVAL_S,
        "aging_step": AGING_STEP,
        "aging_max_boost": AGING_MAX_BOOST,
        "policies": policies,
        "kind_mappings": kind_mappings,
        "aging": aging,
        "supersede": supersede,
    }

    out_dir = REPO_ROOT / "libs" / "job_runtime" / "job_runtime_tests" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "job_policy_oracle.json"
    out_path.write_text(
        json.dumps(oracle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"frozen {out_path} ({len(policies)} policies, "
          f"{len(kind_mappings)} kinds, {len(aging)} aging rows, "
          f"{len(supersede)} supersede rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
