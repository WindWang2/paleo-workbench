# P2-A — Global Resource & Performance Governance

## Authority graph (single authorities, extended — never duplicated)

```
ResourceBudget (policy: CPU/RAM/VRAM/IO columns, pressure thresholds)
      │ for_total_ram_gb / with_pressure_scale / apply_all_budgets
      ▼
ResourceGovernor (admission · reservation · release · pressure · throttling · metrics)
      │ scheduler_admission_hook (lease protocol)          │ cpu_allowance/io_slots
      ▼                                                     ▼
TaskScheduler (1 heavy lane + 1 interactive lane, aging,   transcode workers,
cooperative cancel, crash-safe work dirs)                   factor-prepare workers,
      ▲                                                     ONNX intra-op threads,
      │ estimates in TaskSpec.payload["resources"]          scanner pool, BLAS pin
SeismicLifecycleService (transcode/attribute submissions)

MemoryPressureMonitor ── relief evictables ──► seismic volume cache, L1 slice ledger
telemetry.snapshot() ──► scheduler + governor + pressure + cache stats
```

## What changed (files)

- `runtime/task_categories.py` (new): 11 categories, priority ladder, IO weights, kind→category mapping.
- `runtime/resource_budget.py`: +CPU/IO columns (`logical_cores`, `interactive_reserve_cores`, `background_core_ceiling`, `io_slots`), +pressure fractions, `background_nice`; `apply_l1_budget`/`apply_compute_budget`/`apply_all_budgets`.
- `runtime/resource_governor.py` (new): TaskRequest/ResourceLease/ResourceGovernor (`try_admit`/`admit`/`cpu_allowance`/`onnx_thread_allowance`/`runtime_status`), ResourceExhausted (retryable vs pressure-shed), pressure-scaled allowances (NORMAL 1.0 / PRESSURE 0.5 / CRITICAL 0.25 + interactive exemption).
- `runtime/memory_pressure.py` (new): NORMAL/PRESSURE/CRITICAL, rate-limited lazy sampling (psutil → /proc → permanent NORMAL), non-blocking reads (sample gate), cache relief evictables.
- `runtime/task_scheduler.py`: admission hook with lease protocol + release on every terminal path; bounded priority aging (5/5s, cap +50); strict interactive lane (`interactive_workers`); heavy lanes OS-niced (`background_nice`); deferred tasks never dropped.
- `runtime/governance.py` (new): `ensure_global_governance()` idempotent install; GIL switch-interval latency policy (≤2 ms).
- `runtime/telemetry.py` (new): one snapshot over all authorities.
- `runtime/cancellation.py` (new): adapters across TaskContext / geoviz token / callable+Event dialects.
- Wiring: `seismic_transcode.default_workers` + in-flight window from `streaming_buffer_bytes`; `factor_prepare_scheduler.prepare_worker_count`; `tiled_onnx._make_session` intra-op threads; `resources/scanner` pool from io_slots; `seismic_lifecycle` task payloads carry estimates; `main.py` installs governance at boot.
- `geo-viz-engine` submodule: `cache.set_global_budget()`/`global_stats()` public (was hardcoded 1 GiB ledger).

## Priority & fairness

interactive.render(100) > interactive.query(90) > preview(70) > attribute/inference(50) > transcode(45) > export(40) > background(30) > indexing(20) > maintenance(10); aging +5/5s capped +50 ⇒ maintenance peaks at 60 < preview — background can never permanently starve, interactive never preempts.

## Measured (benchmarks/p2_resource_governance_benchmark.py, this host)

| Scenario | Result |
|---|---|
| 1 catalog 100k + verify | (见 05-performance-budget.md 最终数字) |
| 2 transcode + browse | slice p95 0.07ms → 0.21ms under load (2.89× tiny volume, still sub-ms) |
| 3 attribute + render | dispatch p99 0.60 ms — PASS |
| 4 export + query | dispatch p99 23.24 ms — PASS; query p95 0.11→18.8ms (SQLite read tail under IO: pre-existing, documented) |
| 5 pressure | shed/evict/bound/recover/no-deadlock — 8/8 PASS |

## Known limitations (honest)

- SQLite index reads show a 20–60 ms tail under heavy concurrent file IO (present without governance; catalog-domain follow-up, not scheduler).
- `background_nice` is Linux-only (guarded no-op elsewhere).
- VRAM governance remains the VramTextureCache LRU contract; the governor only *reports* VRAM and guards reservations.
- No process-pool isolation for pure-Python CPU burns (GIL); mitigated by switch-interval policy + niceness, documented as follow-up if exports grow.
