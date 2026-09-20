# 14 — findings ledger

Base SHA `06211541ae1ccce22b0d5ba9258ce722170ca98b`. All line refs are that
base; re-verify after each rebase.

## Capability inventory (implemented / merged / wired / verified)

| Capability | implemented | merged | wired | verified |
| --- | --- | --- | --- | --- |
| tiled inference core (stub seam) | yes | yes | libs/prediction | prediction.tiled_stub ctest |
| prediction runtime (ONNX session, pipeline) | yes | yes | libs/prediction (PWB_BUILD_PREDICTION_RUNTIME) | contract tests; ONNX absent on this host |
| catalog repository + manifest + paged SQL | yes | yes | libs/catalog via data_suite | catalog tests |
| project manager save/load/recovery | yes | yes | libs/project | project tests |
| seismic_io PWBVOL1/SEG-Y window reads + TileCache | yes | yes | libs/seismic_io | seismic_io tests |
| QGIS mirror/export native path | platform-gated | yes | libs/qgis (platform) | NOT executable here (no QGIS SDK/Qt build) |
| GUI startup/asset list (Qt pages) | platform-gated | yes | libs/ui_* (platform) | NOT executable here |
| pwb-bench harness | this line | this branch | tools/pwb-bench | self-checks in report digests |

Frozen Python reference sources (for oracle semantics, not executed by the
bench): `paleo_workbench/prediction/tiled_onnx.py` (tiled inference),
`paleo_workbench/catalog/{db,service,store,models}.py` (catalog),
`paleo_workbench/project/manager.py` (project persistence),
`geoviz_seismic` readers (window-read contract). Recorded from repo docs;
exact file SHAs are in the inventory generator output — see
`docs/development/cpp-migration-inventory.md` at the base SHA.

## Confirmed hotspot candidates (evidence gathered, measurement pending)

H1. Per-voxel heap allocation in tile fusion — `run_tile_group` inner loop,
`libs/prediction/src/tiled_inference.cpp` (~L384): `std::vector<float>`
allocated per voxel for per-class logits. Fix shape: reuse a
`std::vector<float>` scratch sized `classes` outside the voxel loop.
Owner: line 03 (prediction). Lease: claim registered in coordination file.

H2. Repeated model SHA-256 — `check_onnx_model_file` hashes the whole model
file at least 3× per pipeline run: `OnnxRuntimeSession::open_file` L664,
discarded result inside `run_tiled_inference` L558, binding re-check in
`prediction_pipeline.cpp` L993. Fix shape: propagate the validated
ModelBinding instead of re-hashing. Owner: 03. Lease: registered.

H3. Quadratic resume lookup — `tiled_inference.cpp` L621-629: `completed`
markers held in `std::vector<std::string>`, per-tile `std::find` →
O(tiles × done). Fix shape: `std::unordered_set<std::string>` built once;
marker naming/order semantics unchanged. Owner: 03. Lease: registered.

H4. Catalog doc-path sort is quadratic + materializes all rows —
`entity_view.cpp::search_assets_page`:
   * `current_version_of` → `CatalogDocument::find_version` = LINEAR scan,
     called once per asset in `filtered_assets` (L119) and again at L207 →
     O(N²) (2×10^10 comparisons at 100k). `DocumentIndex` (document_index
     .hpp, O(1) `version()`, first-wins `emplace` parity with find_version)
     exists but is unused here.
   * `asset_page_row` builds a 20-key `Json` for EVERY filtered asset
     (~L208), then `rows.push_back(entry.row)` copies each row again
     (~L312-317) — ~2×N JSON objects per page call regardless of `limit`.
   * comparators do `row["key"].get<std::string>()` per comparison —
     ordered_json key lookup is a linear member scan + string copy, paid
     O(N log N) times.
   Fix shape: index once (DocumentIndex), sort key-extracted indices,
   materialize only the sliced page. Owner: 01 (catalog); function not in
   01's declared write leases — line-14 lease registered; measure first.

H5. RawVolumeReader per-window file open — `prediction_pipeline.cpp`
`RawVolumeReader::read_voxel_window` opens the raw file per tile request +
per-request output/row buffers. Owner: 03. Measure under
PWB_BUILD_PREDICTION_RUNTIME (`raw-read` scenario).

## Resolution (post-measurement, this branch)

- H1 CONFIRMED+FIXED: 104.9M allocs / 6.09 GB requested on the 21M-voxel
  baseline → 3,210 allocs; median −13.8%; digest identical.
- H2 CONFIRMED+FIXED: hash-free validate path for the discarded re-check +
  binding from session.model_info(). Per-call check_onnx_model_file cost
  unchanged (400 ms/64 MiB — still hashes once by design); per-run saving
  ≈800 ms/64 MiB not reachable end-to-end here (no ONNX).
  Review-flagged intended delta: a mid-run file swap no longer re-throws
  post-run; binding now reports the model that actually ran (strictly
  better provenance). Pre-existing TOCTOU inside open_file (hash-then-read)
  is unchanged and noted in the PR.
- H3 CONFIRMED+FIXED: 847→26 ms on the 20k-marker scan (−96.9%); marker
  filter/format/counts unchanged; tiles_done identical.
- H4 CONFIRMED+FIXED: doc/name 246.9s→365.8ms (−99.85%), doc/modified
  239.8s→430.8ms (−99.82%), allocs 52–65M→2.85M; sql path unchanged
  (7.4ms); page digests byte-identical to baseline AND to the sql path.
- H5 MEASURED, NOT A HOTSPOT: raw-read 148.9 ms for 2.6 GB of windowed
  reads, 965 allocs — per-window open is noise at this scale. No change.
- manifest-load (2486 ms) measured but not modified: line-01 owns catalog
  lifecycle; sqlite path (386 ms) is the fast path already.

## Already-optimized areas (do not touch)

- `seismic_io::TileCache`: byte-budget LRU, shared immutable buffers,
  loader outside lock, stats. Bench only.
- `paged_sql.cpp`: index-ordered paging, version batch-fetch in 100-id
  chunks, no full materialization.
- `paged_asset_core.cpp`: bounded page/inflight caches + seen-row index
  (platform lib — not in the Qt-free bench closure).
- `ProjectManager`: atomic tmp+fsync+rename, three-phase save, disk-sha
  baseline. Clean-skip optimization is explicitly not ported yet — do NOT
  add without measurement + invalidation contract.

## Unreachable on this host (explicitly not executed)

- QGIS mirror/export native path: needs PWB_BUILD_PLATFORM + vendored QGIS
  SDK + Qt; unavailable. Marked unexecuted, not skipped-by-choice.
- Real ONNX inference: only `libonnxruntime.so` on the host is Firefox's
  bundled copy — not a usable SDK. `model-binding` measures the model-file
  gate cost; `tiled` uses the oracle-frozen stub session (the production
  seam, not a mock of the pipeline).
- True cold OS page cache: cannot drop caches without privileges. Cold
  signal reported as `first_ms` (first sample); warm = remaining samples.
- GUI cold I/O / key-thread latency: platform app not buildable here; the
  Qt-free proxies are catalog-load + project-load/save on the real
  persistence paths.
