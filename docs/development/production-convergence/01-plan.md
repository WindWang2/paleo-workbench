# 01 — Plan

Batch order (dependencies: seismic reader → scheduler → import wiring → render path → attributes → inference → acceptance; catalog/mapping/welllog/multiview independent).

| Batch | Scope | Issues | Key deliverables |
|---|---|---|---|
| B1 Catalog P0 | re-land #1099 + lineage complexity + 100k benchmarks | #1027/#1099, #1059 | SQLite canonical (WAL, apply_changes, reconcile, migration) on latest main; deque lineage; honest 10k/50k/100k benchmark table |
| B2 Seismic foundations | production `geoviz_seismic/chunked.py` + `open_volume()` + LOD logical coords; global `HeavyTaskScheduler` + resource budget | #1080, #1081 | ChunkedVolumeReader productized (submodule branch + pin bump), SegyVolume adapter, read_inline/crossline/timeslice/trace/voxel_window/arbitrary_line(lod=); scheduler singleton w/ FIFO+priority+cancel+resume+progress, IO concurrency 1 |
| B3 Import lifecycle | background transcode on import, browse-during-transcode, DERIVED DataVersion + DataRun lineage, stale marking, re-transcode, trash semantics | #1079 | transcode integration service + catalog registration + UI status |
| B4 LOD render path | frame-budget LOD selection, viewport clipping, 250 ms idle refine, direction-aware prefetch honoring VRAM≈viewport | #1082 | render loop changes in geoviz seismic_view/profile path + prefetch generation |
| B5 Attributes | ROI C3 (voxel window + halo + native GIL-release + cancel) + parity tests; full-volume attribute job (same kernel) → float32 zarr DERIVED + DataRun | #1083, #1084 | shared band kernel, band-vs-full parity (assert_allclose), scheduler-driven jobs |
| B6 Inference | TiledOnnxProvider (64×128×128, receptive-field overlap, center-crop fusion, ClassMap u8 + ProbMap f16), tile-scan resume, OOM backoff, CPU fallback labeled | #1085 | provider + integration behind existing ModelProvider/DataRun contract |
| B7 Acceptance | honest 100G acceptance: measured (tiny/quick2g) vs simulated vs extrapolated | #1086 | 04-benchmarks.md matrix |
| B8 Mapping | #1050 CRS entry, #1048 IDW cKDTree+chunk, #1051 fallback reprojection (pyproj), #1052/#1102 QGIS label parity (C++ bridge + wire), #1049 residue (stale alias), re-land #1103 DPI contract from PR #1106 | #1048–#1052, #1102, #1103 | dispatch contract tests, CRS propagation audit test, parity tests |
| B9 Well Log | enable native engine in WellLogHost with QPainter fallback (same payload); DTW min-max peak-preserving decimation + thin-bed fixture | #1053, #1054 | host engine branch + synthetic extrema regression |
| B10 Multiview | seismic cursor producer (IL/XL/TWT), well registry on project open/close, hub seismic geometry | #1029-followup | end-to-end Map↔Well↔Seismic↔3D |
| B11 Review/docs/PR | adversarial review rounds, full local regression, docs, branch push + PR | — | 05-final-review.md, 06-architecture-after.md, 07-known-limitations.md |

Rules: main read-only; per-batch targeted tests via `run_env.sh`; no fake tests (production paths only); commit per logical batch; BLOCKER/HIGH review findings must be fixed before PR.

Deferred-by-design (issue-only, if not blocking): #1045 Windows CI, #1055–#1058 (P2 outside this scope unless cheap), #1101/#1107 test-infra flakes (verify & address if low-risk).
