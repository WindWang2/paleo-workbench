# 14 — C++ 性能基准与有证据的优化 · task_plan

- branch: `codex/cpp-close-14-performance-audit-20260919`
- worktree: `/home/kevin/project/worktrees/cpp-close-14-performance-audit`
- base SHA (origin/main at start): `06211541ae1ccce22b0d5ba9258ce722170ca98b`
- host: linux (cachyos), same physical host as lines 01–05; resource gate =
  `scripts/cpp-migration/invoke-resource-gate.sh` (flock on
  `.git/cpp-migration-heavy.lock`, jobs ≤ 2 default, ≥ 8 GiB free).
- /goal and /goal-loop: NOT supported by this Devin CLI platform (no command
  docs found) → file-persistence loop via this ledger directory instead.
- Token budget: platform has no /goal budget metering; progress tracked by
  ledger rounds. Requested 3亿 tokens is not enforceable here — recorded as
  requested-not-applicable.

## Scope (exclusive)

Benchmark/profiling tooling + evidence-backed local optimizations on already
existing hotspots. No feature conversion, no scientific-semantics change, no
default-precision change. Optimize only profile-confirmed hotspots not
claimed by lines 01–13 (lease = registration entry + no conflicting
registration/commits from the owning line).

## Named hotspot patterns to trace (from task)

| Pattern | Candidate site | Owner line | Status |
| --- | --- | --- | --- |
| per-voxel allocation | `libs/prediction/src/tiled_inference.cpp` `run_tile_group` (~L384) | 03 (lease requested) | found |
| repeated model SHA256 | `check_onnx_model_file` ×3/run: `onnx_session.cpp` L664, `tiled_inference.cpp` L558 (discarded), `prediction_pipeline.cpp` L993 | 03 (lease requested) | found |
| linear resume lookup | `tiled_inference.cpp` L621-629 `std::find` over `completed` per tile | 03 (lease requested) | found |
| repeated JSON/geometry conversion | TBD (mapping/ui_composite) | — | open |
| table comparator re-parse/copy | `libs/catalog/src/entity_view.cpp` comparators (`tail()` copies 2 strings/compare; full JSON row materialization pre-slice) | 01 (lease requested) | found |
| full-volume copy | TBD (seismic service / prediction input) | — | open |
| GUI cold IO | app startup path (12 owns shell — measure only) | 12 | open |

## Benchmark flows (merged native paths)

1. tiled inference run (stub session, no ONNX dependency) — tiles/sec, allocs
2. prediction pipeline model-binding overhead (SHA256 counts)
3. resume scan with N completed markers (lookup complexity)
4. catalog 100k-asset paged SQL reads + canonical sort path
5. project save/reopen (data_suite/project manager)
6. QGIS mirror/export — measure only if reachable Qt-free; else mark
   not-executed (needs vendored QGIS SDK, platform ON)

## Method

- new `tools/pwb-bench` (or benchmark test target) + Python-free JSON report:
  wall median/p95 of ≥5 samples, peak RSS (`/proc/self/status` VmHWM or
  getrusage), IO bytes (`/proc/self/io`), per-phase timings.
- baseline measured on base SHA build; optimized build same config/machine;
  correctness = existing oracle tests + targeted equivalence checks.
- keep an optimization only with reproducible gain and no unacceptable
  regression; otherwise revert.

## Build plan

Minimal Qt-free closure for the bench targets:
`PWB_BUILD_DATA=ON PWB_BUILD_CONV_13=ON PWB_BUILD_CONV_21=ON
PWB_BUILD_PREDICTION_RUNTIME=ON PWB_BUILD_TOOLS=ON` (+ CONV_14/19 implied).
Platform/QGIS-dependent flows are measured only if a platform configure is
feasible on this host under the resource gate; otherwise reported as
not-executed with the replay commands.
