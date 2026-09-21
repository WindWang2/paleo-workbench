#!/usr/bin/env python3
"""CONV-34 — freeze the resource-governance oracle from the REAL Python
runtime (paleo_workbench/runtime/resource_budget.py + memory_pressure.py +
resource_governor.py + governance.py).

Generated fixture: libs/job_runtime/job_runtime_tests/fixtures/
governor_oracle.json — replayed by job_runtime.governor_oracle.

Determinism: every scenario injects a scripted clock and a scripted memory
sampler, so results are machine-independent (no real /proc reads, no real
monotonic clock). Lease hold-seconds use Python's real time.monotonic
inside ResourceLease — hold-duration metrics are therefore NOT frozen
(the C++ test asserts counters only).

Case format is replayable: each case stores its INPUTS (budget config /
env / scripted samples+clock / op list) plus the frozen EXPECTED outputs.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from paleo_workbench.runtime import resource_budget as rb  # noqa: E402
from paleo_workbench.runtime.memory_pressure import (  # noqa: E402
    MemoryPressureMonitor,
    PressureState,
)
from paleo_workbench.runtime.resource_budget import ResourceBudget  # noqa: E402
from paleo_workbench.runtime.resource_governor import (  # noqa: E402
    ResourceExhausted,
    ResourceGovernor,
    TaskRequest,
)
from paleo_workbench.runtime.task_categories import TaskCategory  # noqa: E402

GIB = 1024**3


def budget_dict(b: ResourceBudget) -> dict:
    return {
        "total_ram_gb": b.total_ram_gb,
        "os_reserve_gb": b.os_reserve_gb,
        "python_reserve_gb": b.python_reserve_gb,
        "l1_slice_cache_bytes": b.l1_slice_cache_bytes,
        "streaming_buffer_bytes": b.streaming_buffer_bytes,
        "vram_budget_mb": b.vram_budget_mb,
        "logical_cores": b.logical_cores,
        "interactive_reserve_cores": b.interactive_reserve_cores,
        "background_core_ceiling": b.background_core_ceiling,
        "io_slots": b.io_slots,
        "background_nice": b.background_nice,
        "ram_pressure_frac": b.ram_pressure_frac,
        "ram_critical_frac": b.ram_critical_frac,
        "page_cache_floor_gb": b.page_cache_floor_gb,
        "background_cores": b.background_cores,
        "heavy_task_core_allowance": b.heavy_task_core_allowance,
    }


def freeze_budgets() -> list[dict]:
    cases = []

    def emit(name, b):
        cases.append({"name": name, "expected": budget_dict(b)})

    for cores in (1, 2, 4, 8, 16, 32):
        emit(f"cores:{cores}", ResourceBudget(logical_cores=cores))
    for cores, ceiling in ((8, 3), (8, 20), (4, 1)):
        emit(f"cores:{cores},ceiling:{ceiling}",
             ResourceBudget(logical_cores=cores,
                            background_core_ceiling=ceiling))
    for gb in (8.0, 12.0, 16.0, 24.0, 32.0, 48.0, 64.0, 128.0):
        emit(f"for_total_ram:{gb:g}", ResourceBudget.for_total_ram_gb(gb))
    for reserve in (0, 1, 4):
        emit(f"cores:8,reserve:{reserve}",
             ResourceBudget(logical_cores=8,
                            interactive_reserve_cores=reserve))
    return cases


def freeze_pressure_scale() -> list[dict]:
    cases = []
    # Banker's-rounding territory: cores*f hits .5 boundaries (e.g.
    # 5*0.5=2.5 -> round=2, not 3 — Python to-nearest-even).
    for cores, ceiling, factor in (
        (8, 0, 1.0), (8, 0, 0.5), (8, 0, 0.25), (8, 0, 0.1), (8, 0, 0.05),
        (8, 0, 1.5), (5, 0, 0.5), (3, 0, 0.5), (7, 0, 0.25),
        (8, 5, 0.5), (8, 3, 0.5), (4, 0, 0.5), (2, 0, 0.25),
    ):
        b = ResourceBudget(logical_cores=cores, background_core_ceiling=ceiling,
                           io_slots=4.0)
        scaled = b.with_pressure_scale(factor)
        cases.append({
            "input": {"logical_cores": cores,
                      "background_core_ceiling": ceiling,
                      "io_slots": 4.0, "factor": factor},
            "expected": {
                "background_core_ceiling": scaled.background_core_ceiling,
                "background_cores": scaled.background_cores,
                "io_slots": scaled.io_slots,
            },
        })
    return cases


def freeze_env_overrides() -> list[dict]:
    """active_budget() under PALEO_* pins; module _ACTIVE reset per case."""
    cases = []
    matrix = [
        ("32_only", {"PALEO_BUDGET_RAM_GB": "32"}),
        ("cores8", {"PALEO_BUDGET_RAM_GB": "32", "PALEO_BUDGET_CORES": "8"}),
        ("cores0_falsy", {"PALEO_BUDGET_RAM_GB": "32", "PALEO_BUDGET_CORES": "0"}),
        ("cores_bad", {"PALEO_BUDGET_RAM_GB": "32", "PALEO_BUDGET_CORES": "abc"}),
        ("cores_space", {"PALEO_BUDGET_RAM_GB": "32", "PALEO_BUDGET_CORES": " 6 "}),
        ("io2", {"PALEO_BUDGET_RAM_GB": "32", "PALEO_IO_SLOTS": "2"}),
        ("io0_falsy", {"PALEO_BUDGET_RAM_GB": "32", "PALEO_IO_SLOTS": "0"}),
        ("io_bad", {"PALEO_BUDGET_RAM_GB": "32", "PALEO_IO_SLOTS": "z"}),
        ("nice0", {"PALEO_BUDGET_RAM_GB": "32", "PALEO_BACKGROUND_NICE": "0"}),
        ("nice_bad", {"PALEO_BUDGET_RAM_GB": "32", "PALEO_BACKGROUND_NICE": "x"}),
        ("ram_bad", {"PALEO_BUDGET_RAM_GB": "junk", "PALEO_BUDGET_CORES": "4"}),
        ("ram_16", {"PALEO_BUDGET_RAM_GB": "16", "PALEO_BUDGET_CORES": "4"}),
        ("ram_float", {"PALEO_BUDGET_RAM_GB": " 48.5 ", "PALEO_BUDGET_CORES": "4"}),
        ("ram_trail", {"PALEO_BUDGET_RAM_GB": "64x", "PALEO_BUDGET_CORES": "4"}),
    ]
    keys = ("PALEO_BUDGET_RAM_GB", "PALEO_BUDGET_CORES", "PALEO_IO_SLOTS",
            "PALEO_BACKGROUND_NICE")
    for name, env in matrix:
        saved = {k: os.environ.get(k) for k in keys}
        try:
            for k in keys:
                os.environ.pop(k, None)
            os.environ.update(env)
            rb._ACTIVE = None
            b = rb.active_budget()
            cases.append({
                "name": name,
                "env": env,
                "expected": {
                    "logical_cores": b.logical_cores,
                    "io_slots": b.io_slots,
                    "background_nice": b.background_nice,
                    "total_ram_gb": b.total_ram_gb,
                    "background_cores": b.background_cores,
                },
            })
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            rb._ACTIVE = None
    return cases


class ScriptedClock:
    def __init__(self, times):
        self._times = list(times)
        self._i = 0

    def __call__(self):
        t = self._times[min(self._i, len(self._times) - 1)]
        self._i += 1
        return t


def freeze_monitor() -> list[dict]:
    cases = []
    grid = []
    for frac in (0.0, 0.5, 0.84, 0.85, 0.9, 0.94, 0.95, 0.99, 1.0):
        grid.append({"used_frac": frac,
                     "pressure_frac": 0.85, "critical_frac": 0.95,
                     "state": PressureState(
                         "critical" if frac >= 0.95 else
                         "pressure" if frac >= 0.85 else "normal").value})
    cases.append({"name": "classify_grid", "grid": grid})

    def run_seq(name, samples, interval, clock_times, ops, evictables,
                rebind_at=None, rebind_thresholds=None):
        it = iter(samples)
        last = samples[-1]
        mon = MemoryPressureMonitor(
            ResourceBudget(logical_cores=8),
            sample_interval_s=interval,
            clock=ScriptedClock(clock_times),
            sampler=lambda _b: next(it, last),
        )
        for e_name, freed in evictables.items():
            if freed == "raise":
                def _boom():
                    raise RuntimeError("evictable exploded")
                mon.register_evictable(e_name, _boom)
            else:
                mon.register_evictable(e_name, (lambda f=freed: f))
        states = []
        for i, op in enumerate(ops):
            if rebind_at is not None and i == rebind_at:
                mon.rebind_budget(ResourceBudget(
                    logical_cores=8, **(rebind_thresholds or {})))
            states.append(mon.state(refresh=(op == "refresh")).value)
        snap = mon.snapshot()
        cases.append({
            "name": name,
            "input": {
                "samples": [list(s) for s in samples],
                "interval": interval,
                "clock": clock_times,
                "ops": ops,
                "evictables": evictables,
                "rebind_at": rebind_at,
                "rebind": rebind_thresholds,
            },
            "expected": {
                "states": states,
                "relief_runs": snap["relief_runs"],
                "relief_freed_bytes": snap["relief_freed_bytes"],
                "evictables": snap["evictables"],
            },
        })

    run_seq(
        "transitions_with_relief",
        [(0.5, 0, 32 * GIB), (0.9, 0, 32 * GIB), (0.97, 0, 32 * GIB),
         (0.5, 0, 32 * GIB), (0.9, 0, 32 * GIB)],
        0.0, [float(i) for i in range(64)],
        ["state", "refresh", "refresh", "refresh", "refresh"],
        {"cache_a": 1000, "cache_b": 250},
    )
    # An evictable that raises must not kill relief (failure swallowed).
    run_seq(
        "evictable_failure_swallowed",
        [(0.9, 0, 32 * GIB)],
        0.0, [0.0, 1.0],
        ["refresh"],
        {"bad": "raise", "ok": 100},
    )
    # interval > 0: state() calls clock once for the staleness check and
    # once inside _sample for sampled_at — the clock sequence matters.
    run_seq(
        "rate_limited_sampling",
        [(0.5, 0, 32 * GIB), (0.9, 0, 32 * GIB)],
        10.0, [0.0, 5.0, 20.0],
        ["state", "state", "state"],
        {},
    )
    # rebind tighter thresholds: same sample reclassifies.
    run_seq(
        "rebind_thresholds",
        [(0.5, 0, 32 * GIB), (0.5, 0, 32 * GIB)],
        0.0, [0.0, 1.0, 2.0, 3.0],
        ["state", "state"],
        {},
        rebind_at=1, rebind_thresholds={"ram_pressure_frac": 0.4},
    )
    return cases


def freeze_governor() -> list[dict]:
    cases = []

    def emit(name, *, cores, ceiling=0, io_slots=4.0, ram_gb=32.0,
             vram_mb=1024, pressure_samples, ops):
        samples = [(f, 0, int(ram_gb * GIB)) for f in pressure_samples]
        it = iter(samples)
        last = samples[-1]
        monitor = MemoryPressureMonitor(
            ResourceBudget(logical_cores=cores),
            sample_interval_s=0.0,
            clock=ScriptedClock([float(i) for i in range(1024)]),
            sampler=lambda _b: next(it, last),
        )
        budget = ResourceBudget(logical_cores=cores,
                                background_core_ceiling=ceiling,
                                io_slots=io_slots,
                                total_ram_gb=ram_gb,
                                vram_budget_mb=vram_mb)
        gov = ResourceGovernor(budget, pressure_monitor=monitor,
                               clock=ScriptedClock([0.0] * 2048))

        leases = []
        steps = []
        for op in ops:
            kind = op[0]
            if kind == "admit" or kind == "try":
                request = TaskRequest.from_kind(op[1], **op[2])
                if kind == "admit":
                    try:
                        leases.append(gov.admit(request))
                        steps.append({"result": "lease"})
                    except ResourceExhausted as exc:
                        steps.append({"result": "raise",
                                      "reason": exc.reason,
                                      "retryable": exc.retryable,
                                      "pressure": exc.pressure})
                else:
                    lease = gov.try_admit(request)
                    if lease is not None:
                        leases.append(lease)
                    steps.append({"result": "lease" if lease else "defer"})
            elif kind == "release":
                idx = op[1]
                if 0 <= idx < len(leases) and leases[idx] is not None:
                    leases[idx].release()
                    leases[idx] = None
                steps.append({})
            elif kind == "allowance":
                steps.append({"value": gov.cpu_allowance(
                    TaskCategory(op[1]), requested=op[2])})
            elif kind == "io_slots":
                steps.append({"value": gov.io_slots()})
            elif kind == "onnx":
                steps.append({"value": gov.onnx_thread_allowance()})
            elif kind == "pressure":
                steps.append({"value": gov.pressure_state().value})
            elif kind == "status":
                s = gov.runtime_status()
                steps.append({"reserved": s["reserved"],
                              "bg_effective": s["budget"][
                                  "background_cores_effective"],
                              "io_effective": s["budget"]["io_slots_effective"]})
            else:
                raise AssertionError(op)
        for lease in leases:
            if lease is not None:
                lease.release()
        m = gov.metrics.snapshot()
        cases.append({
            "name": name,
            "input": {
                "cores": cores, "ceiling": ceiling, "io_slots": io_slots,
                "ram_gb": ram_gb, "vram_mb": vram_mb,
                "pressure_samples": [list(s) for s in samples],
            },
            "ops": [
                [o[0], o[1], o[2]] if o[0] in ("admit", "try")
                else ([o[0], o[1], o[2]] if o[0] == "allowance"
                      else [o[0], o[1]] if o[0] == "release"
                      else [o[0]])
                for o in ops
            ],
            "steps": steps,
            "metrics": {
                "admitted": m["admitted"], "deferred": m["deferred"],
                "rejected": m["rejected"], "released": m["released"],
                "pressure_rejections": m["pressure_rejections"],
                "active_leases": m["active_leases"],
            },
        })

    emit("background_ceiling_defer", cores=8, pressure_samples=(0.5,), ops=[
        ("admit", "seismic.transcode", {"estimated_cpu_cores": 4.0}),
        ("admit", "seismic.attribute", {"estimated_cpu_cores": 2.0}),
        ("try", "background.io", {"estimated_cpu_cores": 1.0}),
        ("admit", "index.documents", {"estimated_cpu_cores": 1.0}),
        ("release", 1),
        ("try", "background.io", {"estimated_cpu_cores": 1.0}),
        ("status",),
    ])
    emit("interactive_pool", cores=8, pressure_samples=(0.5,), ops=[
        ("admit", "seismic.transcode", {"estimated_cpu_cores": 6.0}),
        ("admit", "interactive.render", {"estimated_cpu_cores": 1.0}),
        ("admit", "interactive.query", {"estimated_cpu_cores": 7.0}),
        ("admit", "preview.thumb", {"estimated_cpu_cores": 1.0}),
        ("release", 0),
        ("admit", "interactive.query", {"estimated_cpu_cores": 7.0}),
    ])
    emit("ram_soft_limit", cores=8, pressure_samples=(0.5,), ops=[
        ("admit", "background.io",
         {"estimated_ram_bytes": 4 * GIB, "estimated_cpu_cores": 1.0}),
        ("admit", "background.compute",
         {"estimated_ram_bytes": 2 * GIB, "estimated_cpu_cores": 1.0}),
        ("admit", "interactive.render",
         {"estimated_ram_bytes": 8 * GIB, "estimated_cpu_cores": 1.0}),
        ("try", "background.io", {"estimated_ram_bytes": 1}),
    ])
    emit("io_slots", cores=8, pressure_samples=(0.5,), ops=[
        ("admit", "seismic.transcode", {}),
        ("try", "export.map", {}),
        ("release", 0),
        ("admit", "export.map", {}),
        ("admit", "background.io", {}),
        ("admit", "interactive.render", {}),
    ])
    emit("vram_guard", cores=8, vram_mb=64, pressure_samples=(0.5,), ops=[
        ("admit", "seismic.transcode",
         {"estimated_vram_bytes": 64 * 1024 * 1024}),
        ("try", "seismic.attribute", {"estimated_vram_bytes": 1}),
        ("admit", "interactive.render",
         {"estimated_vram_bytes": 128 * 1024 * 1024}),
    ])
    emit("pressure_scaling", cores=8, pressure_samples=(0.5, 0.9), ops=[
        ("pressure",),
        ("admit", "seismic.transcode", {"estimated_cpu_cores": 6.0}),
        ("release", 0),
        ("pressure",),
        ("admit", "seismic.transcode", {"estimated_cpu_cores": 4.0}),
        ("admit", "seismic.transcode", {"estimated_cpu_cores": 3.0}),
        ("admit", "interactive.render", {"estimated_cpu_cores": 2.0}),
        ("io_slots",),
        ("status",),
    ])
    emit("critical_shed", cores=8, pressure_samples=(0.97,), ops=[
        ("admit", "seismic.transcode", {}),
        ("admit", "background.io", {}),
        ("admit", "interactive.render", {"estimated_cpu_cores": 0.5}),
        ("admit", "interactive.query", {"estimated_cpu_cores": 0.5}),
        ("admit", "preview.thumb", {"estimated_cpu_cores": 0.5}),
        ("try", "maintenance.gc", {}),
        ("pressure",),
    ])
    emit("allowances", cores=8, pressure_samples=(0.5, 0.9), ops=[
        ("allowance", "background.compute", None),
        ("allowance", "background.compute", 4),
        ("allowance", "background.compute", 0),
        ("allowance", "interactive.render", None),
        ("allowance", "interactive.render", 99),
        ("onnx",),
        ("io_slots",),
        ("pressure",),
        ("allowance", "background.compute", None),
        ("onnx",),
        ("io_slots",),
    ])
    emit("admit_raise_semantics", cores=2, pressure_samples=(0.5,), ops=[
        ("admit", "seismic.transcode", {"estimated_cpu_cores": 4.0}),
        ("try", "seismic.attribute", {}),
        ("status",),
    ])
    emit("release_idempotent", cores=8, pressure_samples=(0.5,), ops=[
        ("admit", "background.io", {"estimated_cpu_cores": 2.0}),
        ("release", 0),
        ("release", 0),
        ("release", 9),
        ("status",),
    ])
    # from_kind mapping + effective defaults (pure request math).
    kind_cases = []
    for kind in ("seismic.transcode", "interactive.render", "preview.x",
                 "export", "weird", "", "RENDER"):
        r = TaskRequest.from_kind(kind)
        kind_cases.append({
            "kind": kind,
            "category": r.category.value,
            "effective_priority": r.effective_priority,
            "effective_io_weight": r.effective_io_weight,
        })
    cases.append({"name": "from_kind_defaults", "requests": kind_cases})
    return cases


def main() -> int:
    oracle = {
        "schema": "pwb.governor_oracle/1",
        "source": "paleo_workbench/runtime/resource_budget.py + "
                  "memory_pressure.py + resource_governor.py + governance.py",
        "budgets": freeze_budgets(),
        "pressure_scale": freeze_pressure_scale(),
        "env_overrides": freeze_env_overrides(),
        "monitor": freeze_monitor(),
        "governor": freeze_governor(),
    }
    out_dir = REPO_ROOT / "libs" / "job_runtime" / "job_runtime_tests" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "governor_oracle.json"
    out_path.write_text(
        json.dumps(oracle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    total = (len(oracle["budgets"]) + len(oracle["pressure_scale"]) +
             len(oracle["env_overrides"]) + len(oracle["monitor"]) +
             len(oracle["governor"]))
    print(f"frozen {out_path} ({total} case groups)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
