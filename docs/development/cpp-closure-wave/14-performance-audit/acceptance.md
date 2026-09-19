# 14 — acceptance ledger

Status: DELIVERED. Commit e00ff1a6 on base 06211541 (origin/main verified
unchanged at push time). PR: https://github.com/WindWang2/paleo-workbench/pull/1413

## Acceptance criteria (from task text)

- [x] Fixed machine/build/data/thread conditions recorded per run
      (environment block in every report: host, gcc 16.2, ndebug,
      thread env; gate-serialized, bench-exclusive runs).
- [x] Cold/warm cache signal (`first_ms` vs steady samples; OS cache drop
      is privileged → documented limitation in findings.md).
- [x] ≥5 samples per scenario (doc-path catalog runs capped at 3 via
      --doc-samples — recorded); median + p95 + raw samples in JSON.
- [x] Peak RSS + /proc io counters + per-scenario latency recorded.
- [x] Coverage: project-open (catalog-load + project), 100k-asset list
      (catalog-list doc+sql), prediction large data (tiled 21M voxels),
      slicing/preview (slice, tile-cache, raw-read), save/reopen (project).
      UNEXECUTED: QGIS mirror/export + GUI cold I/O (platform SDK absent),
      real ONNX inference (libonnxruntime.so absent) — findings.md §unreachable.
- [x] Only profile-confirmed, unclaimed hotspots modified (H1–H4; leases
      registered; line-03 disclaimed libs/prediction, entity_view not in
      line-01 leases). Semantics + default precision unchanged — digests
      identical, oracle tests green.
- [x] Baseline vs changed runs with equivalence regression: digest anchors
      all IDENTICAL (tiled, resume, catalog doc paths == sql path,
      raw-read). Gains reproducible: −13.8% / −96.9% / −99.8%.
- [x] Independent review (explore subagent, exhaustive parity check vs
      base) → 2 MED + 4 LOW findings; MED-1 documented as intended
      (binding = identity of model that ran), MED-2 confirmed untracked/
      gitignored, LOWs fixed (comment hardening, MSVC block removal,
      vestigial include) or accepted (unconditional version lookup —
      matches old behavior).
- [x] Branch pushed (`codex/cpp-close-14-performance-audit-20260919`,
      head e00ff1a6); PR #1413 opened against main@06211541 with workflow
      deltas, scope, dependencies, test commands/results, resource limits,
      and the real limitations listed.

## Evidence index

- bench reports: `bench-out/*.json` in the worktree (regenerated; archived
  copies under `docs/development/cpp-closure-wave/14-performance-audit/bench/`).
- resource leases: gate invocations logged in progress.md.

## Baseline snapshot (base 06211541, Release/ndebug, gate-exclusivo, 5 samples)

| scenario | median | p95 | allocs | peak RSS | anchor |
| --- | --- | --- | --- | --- | --- |
| tiled (160×256×512, tile 64×128×128, ov8, b4 — 45 tiles, 21.0M voxels) | 2593.2 ms | 2708.1 ms | 104.9M / 6.09 GB | 229.5 MiB | digest 5725887231168153417 |
| resume (20k done markers, 0 tiles left) | 846.9 ms | 849.1 ms | 1.20M | 9.0 MiB | tiles_done=0 |
| model-binding (64 MiB .onnx) | 400.1 ms | 400.6 ms | 50 | 6.4 MiB | io_rchar 335 MB |
| catalog-list doc/name (100k) | 246,948 ms | 256,765 ms | 51.9M / 3.00 GB | 638.5 MiB | digest 409542645217192479 |
| catalog-list doc/modified (100k) | 239,820 ms | 240,200 ms | 64.8M / 3.40 GB | 638.5 MiB | digest 10391575517663678567 |
| catalog-list sql/name (100k) | 7.4 ms | 8.6 ms | 355k | 638.5 MiB | digest 409542645217192479 |
| catalog-load manifest / sqlite (100k) | 2486 / 386 ms | — | — | — | — |
| raw-read (2.6 GB windowed reads) | 148.9 ms | 155.5 ms | 965 | 6.3 MiB | digest 3800085169046703236 |
| slice | 75.4 ms | — | — | — | — |
| tile-cache | 46.8 ms | — | — | — | — |
| project save + reopen | 478 + 501 ms | — | — | — | — |

## Optimized snapshot (same machine/config, same fixtures, gate-held run)

| scenario | base median | opt median | Δ | allocs base→opt | digest |
| --- | --- | --- | --- | --- | --- |
| tiled | 2593.2 ms | 2235.0 ms | −13.8% | 104.9M→3,210 | IDENTICAL |
| resume | 846.9 ms | 26.2 ms | −96.9% | 1.20M→1.30M | IDENTICAL |
| model-binding | 400.1 ms | 398.2 ms | −0.5% (per-call fn unchanged; H2 removes 2 of 3 calls/run ≈ −800 ms/64 MiB, not reachable end-to-end without ONNX) | 50→50 | — |
| catalog-list doc/name | 246,948 ms | 365.8 ms | −99.85% (~675×) | 51.9M→2.85M | IDENTICAL == sql |
| catalog-list doc/modified | 239,820 ms | 430.8 ms | −99.82% (~557×) | 64.8M→2.85M | IDENTICAL |
| catalog-list sql/name | 7.45 ms | 7.33 ms | no regression | 355k→355k | IDENTICAL |
| raw-read / slice / tile-cache | 148.9 / 75.4 / 46.8 ms | 150.7 / 78.2 / 48.1 ms | ≤+3.8% noise, code untouched | same | IDENTICAL |
| project save+load / catalog-load | unchanged code paths — noise-band results | | | | |

Equivalence anchors ALL HELD: every digest identical to baseline; the doc
path still emits rows byte-identical to the SQL oracle path at 100k assets.
