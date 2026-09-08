# 03 — Decisions

Auto-selected per goal rules (evidence-based, long-term-maintenance-weighted).
New decisions appended as the work proceeds; each records alternatives.

- **D1 — Build the vendored QGIS on Windows (this machine).** No completed
  vendor build exists anywhere (audited: projects tree, both WSL distros,
  no srs.db/qgis-vendor anywhere); prior builds were Linux-only. The goal's
  QGIS verification is impossible locally without it, and WSL produces a
  Linux .so the Windows cp312 venv cannot import. Path: conda-forge prefix
  `C:\Users\wangj.KEVIN\paleo-qgis-deps` (qt6-main=6.11.2 to match
  PySide6's bundled Qt exactly — ADR 0059 private-ABI rule) + MSVC 14.38,
  `-j2`, neutral build dir `C:\Users\wangj.KEVIN\paleo-qgis-build\qgis-vendor`
  for cross-worktree `PALEO_QGIS_REUSE_VENDOR` reuse. Rejected: vcpkg
  (bootstrap + hours), aqtinstall (documented broken in-repo), OSGeo4W
  (second package manager, no in-repo precedent), WSL build (wrong ABI).
- **D1a — Missing win-64 deps filled from source only where conda-forge
  has no package:** qt6keychain built from v0.14.0 (conda ships only the
  Qt5 flavor); `qca-qt6` + `expat` (dev files; the runtime `libexpat`
  package ships only a DLL) from conda-forge. Vendored QGIS gained two
  documented Windows patches (UPSTREAM.md): restored
  `platform/windows/rc/version.rc.in` from the pinned commit, and
  `include(CheckFunctionExists)` inside the internal-spatialindex block
  (upstream bug: module only included under NOT WIN32).
- **D1b — external libspatialindex 2.0.0 instead of the internal copy.**
  The internal spatialindex sources compile INTO qgis_core; on MSVC their
  symbols lack dllexport so qgis_analysis fails to LINK (LNK2019; Linux is
  unaffected — default visibility exports everything). Upstream Windows
  practice is an external libspatialindex; conda-forge 2.0.0 satisfies the
  vendored `<2.1` ceiling. Configure flag flipped to
  `-DWITH_INTERNAL_SPATIALINDEX=OFF` in `.scratch/configure-qgis-vendor.cmd`
  (the repo setup.py default stays ON for the CI Linux leg — no repo change
  was needed since we configure manually per B3 procedure).
  pseudocolor renderer, not RGBA.** Data mirror keyed by data_revision
  ONLY (styles never rewrite science values). Classification (equal
  interval / quantile / explicit / natural breaks) computed host-side
  (numpy, deterministic); the bridge receives only a raster renderer XML
  string — minimal C++ surface, maximal host testability. RGBA mirror
  stays as disclosed fallback when bridge/gdal absent.
- **D3 — One geometry facade, bridge-first, honest engines.**
  `mapping/geometry_operations.py` wraps the bridge's 15 ops plus
  dissolve/polygonize/linemerge/PIP/topology composites; every result
  carries the engine used. Degraded engines only where they pre-exist
  (shapely merge/split/repair, host PIP/stitching). Hot editing paths
  (snapping index, render culling) stay host-authoritative — these are
  editing-internals, not a parallel GIS (documented per goal §4 "逐步迁移").
  Scientific kernels (marching squares, deterministic polygonization,
  kriging/IDW, fusion) remain Paleo per goal §4 exceptions.
- **D4 — GeologicalLayerSpec lives in mapping_workspace (pure data);
  QGIS mapping in mapping/ adapter.** Spec → `fields_json` reaches the
  mirror via a narrow bridge extension; without the bridge the spec still
  validates host-side (GeoJSON properties path) with disclosed
  degradation. One registry binds LayerType ↔ LayerRole ↔ spec.
- **D5 — Canvas mirror delta channel mirrors the proven offscreen #932
  wire** ({base_revision, changed_features, removed_ids}); C++ applies by
  `__pwb_fid` instead of truncate+re-add. Publish ledger host-side
  computes content/style/placement/visibility diffs (the existing layer
  revisions ARE the tokens).
- **D6 — COLOR_BAR in QGIS layout via QgsLayoutItemLegend bound to the
  scalar raster layer** (same renderer XML ⇒ screen/export consistency).
  STAT_CHART / PROFILE / TIMESCALE remain composer-rendered with an
  explicit hybrid boundary reported in the export report (goal §13 allows
  documented mixing). No second persisted layout authority.
- **D7 — ui/workstation edits are surgical call-sites only.** New logic
  lives in mapping//mapping_workspace//workflow/. P0 status-string fix
  touches stage_actions.py/readiness.py literals; factor-group and
  overlay producers are mapping/-side builders invoked from thin stage
  actions. Cross-branch contract with workstation-ux-v7 (they own
  ui/workstation + layer_decorations UI; they do NOT touch bridge C++):
  we export `LayerPresentationState` (mapping_workspace/presentation.py),
  `GeologicalLayerSpec`, capability snapshots; they consume.
- **D8 — Status vocabulary: canonical `"complete"`.** FactorMapTask.status
  is written "complete" by the interpolation authority; the stray
  "completed" readers are the defect (audit P0-1). Fix readers, add a
  module-level constant `TASK_STATUS_COMPLETE` in one place, regression
  test that greps for the literal drift pattern.
- **D9 — LayerPresentationState is derived, never stored.** Computed from
  memberships + MappingDependencyService + QualityReports + catalog
  versions on demand; no new DB, no duplication of freshness state.
