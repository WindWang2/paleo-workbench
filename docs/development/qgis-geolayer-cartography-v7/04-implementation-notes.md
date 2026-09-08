# 04 — Implementation notes

Chronological implementation record; see git log on
`feat/qgis-geolayer-cartography-v7` for atomic commits.

## Commits (order)

| Commit | Goal § | Content |
|---|---|---|
| 9cc04645 | docs | audit baseline + 4 matrices + 00–03 docs |
| d6f63fba | build | Windows/MSVC vendor-build enablement (version.rc.in restored from pinned upstream, CheckFunctionSystems include; UPSTREAM.md documents both) |
| c1a40d9a | P0 | status vocabulary (FACTOR_TASK_STATUS_* constants; 4 readers fixed + source-guard test) + write_product_manifest staging helper (directory-payload bug) |
| bf3784ae | §3 | GeologicalLayerSpec V2 registry (27 roles; LayerType↔LayerRole binding; fields_json wire adapter; policies derived from ROLE_EDITABLE/ROLE_RAW_PROTECTED/stages_for_role) |
| 5e4aefce | §4 | geometry_operations facade (bridge-first, engine disclosure; 21 ops), geometry_planar shared kernels (PIP ray-cast ×3 → 1; clip-to-ring ×2 → 1; extent util), single repair entry, real validity in readiness |
| 96a9a05e | §5 | scalar_data_mirror (float32 GeoTIFF, data-revision-keyed), ScalarStyleSpec + classification (equal/quantile/natural-breaks/explicit), bridge raster renderer codec + upsert_raster_mirror_layer + offscreen renderer-XML path + grid_array getter in grid_render_core; canvas no longer skips raster layers |
| e825dcfe | §8 | LayerPresentationState (16 fields, derived-only; agent) |
| bb40a61c | §10–12 | factor group 6/6 children, confidence overlays, integrated boundary, constraint geometry sync-back + fingerprints (agent; fixed 2 latent bugs: contour overlay always failed, stage_save unpack crash) |
| d2a5f0e1 | §9 | mirror publish ledger (tokens), no-op O(changed), canvas delta channel (C++ delete+re-add by __pwb_fid, base-revision guarded), benchmarks 50–1000 layers |
| 691a35a3 | §6 | geological symbols V2 — 15 symbols, fault classes + confidence gradations, role-compat validation (agent) |
| 404f07d3 | §13–14 | layout native mapping (15 native, 6 explicit hybrid, itemized hybrid report) + 15 cartographic QA rules with localization (agent) |
| 125c0bbb | §12 | fusion production entry (evidence-set → FusionModel → run_integrated_fusion + stage action; also carries the run_qa cartographic wiring) |
| (follow-ups) | — | bridge tests for new APIs (qgis-marked), docs, review fixes |

## Key seams

- **Scalar publish** (mapping/scalar_publish.py): one helper feeds BOTH the
  offscreen encoder and the canvas mirror; `scalar_style_pipeline_ready()`
  gates the whole path (bridge + osgeo). RGBA mirror = documented fallback.
- **Renderer XML is authored by QGIS itself**: `build_scalar_renderer_xml`
  builds QgsSingleBandPseudoColorRenderer + QgsColorRampShader and
  serializes through QGIS's writer; classification runs host-side (numpy,
  deterministic). No hand-rolled renderer markup anywhere.
- **Style never rewrites data**: data mirror keyed by data_revision only;
  bridge reapplies raster renderer on style_revision change without
  reopening the source (offscreen path verified by mirror_reuses
  diagnostics).
- **Delta channel** (canvas): mirrors the proven offscreen #932 semantics;
  host ledger computes diffs; C++ applies delete+re-add by __pwb_fid;
  geometry-kind drift and stale bases fall back to full ship (never error,
  never silent loss).
- **Environment**: vendor QGIS built at
  `C:\Users\wangj.KEVIN\paleo-qgis-build\qgis-vendor` (neutral, reusable via
  PALEO_QGIS_REUSE_VENDOR); deps in conda env `paleo-qgis-deps`
  (qt6-main=6.11.2 == PySide6's bundled Qt, per ADR 0059); qt6keychain
  v0.14.0 built from source (win-64 conda has no Qt6 flavor); runtime needs
  vendor output/bin + deps Library/bin first on PATH, QT_QPA_PLATFORM
  offscreen for headless tests; osgeo comes from the deps env (cp312 ABI
  match with the workbench venv).

## Latent defects found and fixed beyond the goal list

1. `overlay_factor_results` called `calculate_nice_contour_levels(grid)`
   against a `(vmin, vmax)` signature — the contour child ALWAYS raised and
   was silently skipped (Phase-2 factor groups were really 1/6, not 2/6).
2. `stage_save` unpacked two values from `flush_edit_sessions()` which
   returns an int — every stage save crashed into its except-branch.
3. QGIS upstream: `include(CheckFunctionExists)` only under NOT WIN32 —
   pure-MSVC configure failed (vendored patch, UPSTREAM.md).
