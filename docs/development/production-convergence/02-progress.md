# 02 — Progress

Worklog per batch; updated as batches complete.

- 2026-08-29: baseline audit done (00-current-state.md); worktree + submodules initialized; plan fixed (01-plan.md).
- B1 Catalog P0: re-landed #1099 (3 commits onto latest main, identity-removal merge), #1059 lineage deque+tag map, catalog_scale benchmark — committed 62596dd.
- B2 Seismic foundations: `geoviz_seismic/chunked.py` (ChunkedVolumeReader + SegyVolumeReader + open_volume, LOD logical coords, batched arbitrary-line) + `seismic_transcode` grid attrs — committed c50df44 / c6bef1d4. Test: 14/14 `test_chunked_volume_reader` (step≠1, LOD cell semantics, 100-pt line <200ms).
- Global scheduler + budget (#1081): `paleo_workbench/runtime/{task_scheduler,resource_budget}` — committed 1f81b6a8. Tests 11/11.
- B3 Import lifecycle (#1079): `register_derived_store` (directory DERIVED), `seismic_lifecycle.SeismicLifecycleService` (scheduler-driven transcode + DataRun + stale marking + resume + hook), UI wired in data_page + app_shell + seismic_view_panel — committed 9372cd7f. Tests `test_seismic_lifecycle` 6/6.
- #1103 re-land: RenderContext DPI contract (two commits from open #1106) — committed a39c525c / fd77f21b. 24 tests.
- B4 LOD render (#1082): `geoviz_seismic/{lod,chunked_worker}` + SeismicView.set_chunked_volume + panel auto-switch — committed c0fab0e8 / 637f8e20. Tests 9/9 `test_lod_render_path` (policy, prefetch, worker, idle refine).
- B5 Attributes (#1083/#1084): `seismic_attributes.py` (roi_attribute + VolumeAttributeJob, band-halo bitwise parity) + lifecycle `start_attribute_job` — committed 79ac9955. Tests 8/8 `test_seismic_attributes` (C3 parity, resume, cancel).
- B6 Inference (#1085): `prediction/tiled_onnx.py` (64×128×128, overlap=center-crop, classmap u8 + probmap f16, resume, OOM backoff, CPU fallback) — committed 715fbe56. Tests 5/5 `test_tiled_onnx` (real ORT, tiled==whole-volume).
- B7 Acceptance script: `benchmarks/acceptance_100g.py` + quick2g synthetic volume (2.4 GB) — staged, run pending.
- B8 Mapping: agent batch (#1048-#1052, #1102, #1049 residue, engine CRS fix) — committed 26777722 / 30133bda. 26 new tests + full mapping regression.
- B9 Well-log: agent batch (#1053 native engine, #1054 DTW min-max) — committed f82e05e2. 14 new + 4 old DTW tests, 22 well-log tests.
- B10 Multiview: agent batch (seismic cursor producer + well registry) — committed 04745443. 25 new + 50+ wiring tests.
- Review: first adversarial round findings → 05-review.md (all H-* fixed, verified).
