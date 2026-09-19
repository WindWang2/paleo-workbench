# 14 — progress ledger

## Round 1 — reconnaissance + harness (candidate: base 06211541)

- objective: stand up pwb-bench, baseline the named hotspots.
- scope delta: +tools/pwb-bench, root CMake LINE-14 block, ledger dir.
- commands / exit codes:
  - `invoke-resource-gate.sh Configure … -DPWB_BUILD_BENCH=ON
    -DPWB_BUILD_PREDICTION_RUNTIME=ON` → exit 75 RESOURCE_BUSY
    (holder_pid=3706969, sibling build ~22 min). Queued with backoff;
    continued lightweight ledger/survey work.
- resource lease: none held yet (refused, honored).
- findings: H1–H5 (findings.md). Sibling worktrees 01/02/03/04/05/13 all at
  base SHA with zero commits — no concrete ownership conflicts, but function
  leases registered anyway.
- next: acquire gate → configure `build/bench` (Release, platform OFF) →
  build pwb-bench → baseline runs.

## Round 2 — configure + queue (candidate: base 06211541)

- `gate Configure -s . -b build/bench -c Release -j4 -a
  '-DPWB_BUILD_PLATFORM=OFF;-DPWB_BUILD_BENCH=ON;-DPWB_BUILD_PREDICTION_RUNTIME=ON;-DBUILD_TESTING=ON'`
  → exit 0 after ~30 min queued behind line-04 build (lock honored, no
  bypass). Cache: bench ON; DATA/CONV_13/SEISMIC_IO implied via normal vars
  (PREDICTION-RUNTIME block precedent — cache shows OFF, normal var shadows;
  targets all generated: pwb_catalog incl. entity_view/paged_sql, pwb_project,
  pwb_prediction+tests, pwb_seismic_io, pwb-bench).
- `gate Build -t pwb-bench` → queued behind line-13 platform build
  (holder_pid=3866750, `pwb-platform` + UI test targets); background retry
  loop armed (60s backoff).
- Host toolchain: cmake 4.4.3 + ninja from `/tmp/pwb-oracle-venv/bin`,
  gcc 16.2.1. Bench binary overrides global operator new for alloc counting
  (bench-only instrumentation, not in libs).
- Syntax-only g++ pass over tools/pwb-bench/*.cpp: clean after StrongId
  construction fixes.
- build: `gate Build -t pwb-bench -j4` → exit 0 (95 steps, clean compile).
- smoke: `pwb-bench --list` → 9 scenarios; `model-binding 32MiB` ≈ 199 ms/hash.
- BASELINE `tiled` (shape 160×256×512, tile 64×128×128, overlap 8, batch 4,
  45 tiles / 20,971,520 voxels, 5 samples):
  median 2593.2 ms, p95 2708.1 ms, first 2708.1 ms;
  **alloc_calls 104,860,775 (~1 heap alloc per voxel — H1 confirmed)**,
  alloc_bytes 6.09 GB; io_write 921.6 KB; peak RSS 229.5 MiB;
  digest=5725887231168153417 (equivalence anchor).
  file: bench-out/baseline-tiled.json
- queued: resume(20k markers), model-binding(64MiB), raw-read,
  catalog-load(100k), catalog-list(100k), slice, tile-cache, project —
  single gate-held serial run (bench exclusivity rule).
- next: collect remaining baselines → apply measured fixes → re-run +
  prediction.tiled_stub regression + identical digests.

## Round 3 — baseline suite complete (candidate: base 06211541)

- single gate-held serial run (exec pid 3972390), 5 samples each unless noted.
- resume: 20,000 tile markers, all completed. median 846.9 ms, p95 849.1 ms;
  allocs 1,200,385; RSS 9.0 MiB. Pure quadratic lookup — H3 confirmed.
- model-binding: 64 MiB model, check_onnx_model_file ×5. median 400.1 ms,
  p95 400.6 ms; file reads ≈335 MiB across samples. ×3 calls/run (open_file,
  discarded re-check in run_tiled_inference, pipeline binding) ≈ 800 ms/run
  waste — H2 confirmed.
- catalog-list (100k assets, manifest document path): name median
  246,948.1 ms / modified 239,820.4 ms per page call; allocs 51.9M/64.8M.
  SQL path (paged_sql, same data): median 7.4 ms, p95 8.6 ms, allocs 355k.
  Doc path = O(N²) find_version ×2 per asset + full-row materialization
  before slice — H4 confirmed catastrophic; SQL path healthy.
- catalog-load: manifest 2486.2 ms vs sqlite 385.9 ms — evidence only
  (manifest canonical-JSON parse cost; not selected: line-01 owns catalog
  lifecycle, sqlite path already preferred).
- raw-read 148.9 ms / slice 75.4 ms / tile-cache 46.8 ms / project
  save 478.2 ms + load 501.0 ms — healthy, no optimization justified.
- reports: bench-out/baseline-*.json (9 files).

## Round 4 — optimizations applied (candidate: base 06211541 + line-14 diff)

- H1 libs/prediction/src/tiled_inference.cpp run_tile_group: per-voxel
  `std::vector<float> values(prob_channels)` hoisted to one scratch buffer
  outside the fusion loops; fully rewritten each iteration → identical
  argmax/NaN/half-float semantics, zero per-voxel allocs.
- H2a same file: split check_onnx_model_file into validate_onnx_model_file
  (regular/.onnx/cap gate, no hash) + hashing wrapper; the discarded
  re-validation inside run_tiled_inference now calls the hash-free gate.
- H2b libs/prediction/src/prediction_pipeline.cpp: result.binding populated
  from session.model_info() (identity of the model that actually ran —
  strictly better provenance than a post-run re-hash) instead of a third
  full-file SHA-256. Net: 3 hashes/run → 1.
- H3 same file: completed-marker membership moved std::vector+std::find →
  std::unordered_set<std::string>; marker names/filters/counts unchanged.
- H4 libs/catalog/src/entity_view.cpp search_assets_page/count_assets:
  DocumentIndex built once (O(N), emplace first-match = find_version parity),
  sort runs on per-entry extracted keys (string_view fields + owned stage
  value + numeric + per-column NULLs-first flag), stable order + (name,id)
  tail preserved exactly, after-cursor stable_partition on indices, and
  asset_page_row now materializes ONLY the returned slice (was: all 100k
  rows → 20-key Json each → 52M allocs).
- not touched: raw-read/slice/tile-cache/project (no measured problem),
  catalog manifest-load (line-01 ownership + not selected), SQL path
  (already fast), ui_composite JSON/geometry (platform-gated, line-08).
- pending: build under gate → targeted tests → optimized bench suite →
  digest equivalence (tiled digest 5725887231168153417 must match).

## Round 5 — gated rebuild + verification (candidate: line-14 diff)

- `gate Build -s . -b build/bench -c Release -j4` → exit 0 (162 steps).
  Note: two earlier queue attempts were wasted — malformed arg + PATH
  missing cmake in one shell; corrected, re-queued, honored.
- Single gate-held Exec: ctest affected set + full optimized bench suite
  (exclusive serial run, bench isolation rule kept).
- ctest `-R 'prediction\.|data\.(paged_sql|catalog_service|catalog_gc|
  catalog_read|metadata_scale|catalog_domain|oracle_compare|lifecycle_e2e)|
  seismic_io\.'` → 13/14 PASS in 11 s. Sole failure: prediction.runtime —
  every case aborts at session open with "libonnxruntime.so unavailable"
  (environmental; ONNX absent on host — pre-existing limitation, unchanged
  by this diff; the lines it would cover sit after session open).
  Oracle coverage that DID run: prediction.tiled_stub (H1+H3 digests),
  data.paged_sql (doc-path rows cross-checked vs SQL oracle over all
  order_by variants + after cursors), catalog_service/catalog_gc/
  metadata_scale/lifecycle_e2e (H4 + DocumentIndex paths).
- OPTIMIZED results (5 samples; doc paths 3):
  - tiled 2593.2→2235.0 ms (−13.8%), allocs 104,860,775→3,210
    (−99.997%), digest 5725887231168153417 IDENTICAL.
  - resume 846.9→26.2 ms (−96.9%), digest/tiles_done identical.
  - catalog doc_name 246,948→365.8 ms (−99.85%), allocs 51.9M→2.85M,
    digest 409542645217192479 IDENTICAL (and still == sql_name digest).
  - catalog doc_modified 239,820→430.8 ms (−99.82%), allocs 64.8M→2.85M,
    digest 10391575517663678567 IDENTICAL.
  - catalog sql_name 7.45→7.33 ms — no regression on the fast path.
  - model-binding 400.1→398.2 ms — per-call cost unchanged by design
    (the function still hashes once; H2 removed the 2 duplicate calls
    per pipeline run, ~800 ms/64 MiB — pipeline end-to-end unreachable
    without ONNX, so saving is measured per-call-site arithmetic).
  - unchanged paths (raw-read 148.9→150.7, slice 75.4→78.2,
    tile-cache 46.8→48.1, project save/load, catalog-load) within noise.
- reports: bench-out/opt-*.json archived to docs …/bench/.
- next: independent review of the 4-file diff → ledgers → commit/push/PR.

## Round 6 — independent review + reverify (candidate: line-14 diff)

- explore subagent audited the full diff vs base checkout (byte-level):
  A–G all CLEAN; ordering/null/cursor/first-match parity proven for every
  order_by + after + slicing path in entity_view.
- Findings → actions:
  - MED binding delta: intended — binding now = identity of the model that
    actually ran (post-run file swap no longer re-throws); pre-existing
    open_file TOCTOU unchanged; noted in PR body.
  - MED stray files (.snapchk2 etc.): untracked + gitignored; not staged.
  - LOW k.text self-view: hardened with comment (keys sized once, ord-only
    permutation — never reallocate keys while sorting).
  - LOW MSVC block in tools/pwb-bench/CMakeLists.txt: removed, replaced
    with POSIX-only note (bench uses unistd/utsname//proc).
  - LOW vestigial <tuple>: removed.
  - LOW unconditional version lookup in filtered_assets: kept — identical
    to old behavior, now O(1).
- reverify (gate Exec): incremental rebuild 35 steps clean;
  ctest prediction.tiled_stub + data.paged_sql + data.catalog_service
  3/3 PASS; tiled --samples 2 digest=0 = XOR of two identical per-run
  digests (even-sample artifact; the 5-sample opt run already matched
  5725887231168153417), allocs 1287 / median 2209 ms consistent.
- next: commit → push → PR.
