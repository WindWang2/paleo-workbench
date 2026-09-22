# 02 — Migration truth matrix (GeoViz scope)

## A. General matrix — methodology fixed, regenerated at final HEAD

`tools/migration/pwb_migration_inventory.py` + `pwb_final_closure_matrix.py`
(both regenerated docs committed in this branch). Commit 01fd5565 fixed the
#1448 methodology defects — this branch and the parallel session's #1448
fix converged on the same three problems (aliases last-wins, apps/-only
wiring scan, no TU-consumer evidence); this branch's implementation is the
one merged here:

* **all aliases/targets** per unit (was: last `Pwb::` alias wins);
* **whole-repository link graph** with paren-aware `target_link_libraries`
  parsing + transitive closure from the `pwb-platform` executable; edge
  guards classified `always` / `product` (every guard implied by
  PWB_BUILD_NATIVE_PRODUCT through the PwbFeatures IMPLIES closure) /
  `opt-in`;
* **TU-level consumer evidence**: a unit counts as product-wired only when
  a product translation unit actually `#include`s its public headers
  (linked-but-never-included no longer promotes a module).

Final counts (678 modules): **205 NATIVE_PRODUCT / 1 NOT_WIRED /
77 PARTIAL_NATIVE / 395 LEGACY_REFERENCE / 0 oracle-only by design / 0
dead-candidates**. The single NOT_WIRED row is
`paleo_workbench/mapping/geological_pipeline/native_bind.py` → the pybind
compat module (`mapping_bind`), which is *by-design* never in the product
binary (compatibility-only class; audit `05`).

`paleo_workbench/viz/` slice: 17 NATIVE_PRODUCT, 1 PARTIAL, 56
LEGACY_REFERENCE — the LEGACY rows are the Python legacy product's own
implementation modules (the Python shell stays a supported legacy product
with geoviz as its hard import; see `04-python-retirement.md`).

## B. GeoViz capability matrix (strict per-domain classification)

Legend: class follows /goal §4 — `NATIVE_PRODUCT_COMPLETE` requires
implementation + target + build + product link + runtime reach + user-flow
reach + no Python at runtime + tests. "Product path" names the user flow in
pwb-platform.

| # | Domain (Python source) | Native implementation | Product path | Class | Evidence |
|---|---|---|---|---|---|
| 1 | LAS parse/preview (geoviz_well_log las_parser/las_preview) | well-log-engine SDK + `Pwb::IngestLasWle` + viz_a install | 测井→打开 LAS(后台)→well log dock; data page preview | COMPLETE | viz_a gate suites; self-check `well_log_dock` (real A1.Las); 14/14 with viewer stack |
| 2 | Well log tracks/curves/ruler/markers/patterns/LOD/export | `libs/visualization` + WLE + `WellLogTrackPanel` | dock interactions; SVG/PDF/PNG export | COMPLETE | viz-a ledger (23 oracle cases), run16 gates |
| 3 | Cross-well correlation + picks + DTW + formation tops | `libs/visualization/cross_well` + `VizBCrossWellDock` | 连井 dock: load wells → auto-arrange → DTW 传播; picks/tops; sidecar save/reopen | COMPLETE | `viz_b.*` suites, `viz_c.joint3d_closure` multi-fence/closure suites |
| 4 | Well tie (synthetic/wavelet/auto-tie/TD/report) | `libs/visualization/src/well_tie` (verbatim ports) | 连井 dock 标定 page: AC/DT+DEN → synthetic → auto-tie → SVG/PDF report | COMPLETE | `viz_b.well_tie.oracle` (real-well pipeline), calibration parity frozen |
| 5 | Seismic IO (SEG-Y/PWBVOL/tiled) | `libs/seismic_io` + `libs/seismic_service` | 地震→导入 SEG-Y / 打开体版本; tiled reads feed all viewers | COMPLETE | seismic_io oracle suites; self-check `seismic_chain` |
| 6 | Seismic attributes (envelope/RMS/phase/freq/sweetness/relImp/dips/azimuth/curvMean/C3) | `libs/seismic_attributes` (10) + `libs/algorithms` C3 | 地震→计算属性 (volume-level dialog, **11 kernels** registered); 2D panel inline: 6 single-trace kernels + RGB fusion | COMPLETE | sline/E-line oracle suites + `science.coherence_c3_oracle` (7 fixtures incl. real tiny.sgy) |
| 7 | Seismic 2D viewer (VD/wiggle/clip/gain/polarity/colormap/horizon picks/state/export) | `libs/seismic_viewer` + viz_d install | 地震 dock menus: picks save/load JSON, slice npy/csv/png, view-state JSON | COMPLETE | `viz_d.*` suites; wiggle-pinned-attribute regression (this branch) |
| 8 | Arbitrary line | — | — | **GAP** | see `11-known-limitations.md` #1 |
| 9 | Geo3D scene/clip/measure/views/screenshot | `libs/geo3d_viz` + `Geo3DDock` | Geo3D dock (6 measure modes, clip sliders, views, screenshot); workspace sidecar now persisted (this branch) | COMPLETE | geo3d 27/27 suites; `geo3d_workspace.json` sidecar restore/persist |
| 10 | Joint well-seismic 3D (scene/fences/slices/TD/probe) | `libs/geo3d_viz/joint` + `VizCJointHost` | 井震联合 3D page + Geo3D dock; fences (well-pair + manual well-click), time slices, project-scoped state | COMPLETE | `viz_c.joint_oracle` 9/9, `viz_c.joint3d_closure` (real fixtures), `viz_c.joint_analysis` (this branch) |
| 11 | Joint analysis tabs (stratal/RGB/crossplot/export/advisor) | `ui_workers` + `seismic_viewer` + `geomodel` + joint_analysis_install (this branch) | 井震联合 3D page 分析 card: stratal demo + REAL .dat path, RGB overlay, crossplot report, FLAC3D/Abaqus export, advisor | COMPLETE (stratal texture: partial — limitation #4) | `viz_c.joint_analysis` 5 cases incl. real-volume .dat E2E |
| 12 | Charts (axes/series/LTTB/colorbar/cross-plot/surface/contours/hull/QC/fence plots/SVG-PDF) | `libs/viz_charts` + viz_e hosts | hub5 dock: xy_scatter/surface targets; export | COMPLETE | viz_e 792-check oracle suite + pa_flow |
| 13 | Preview/data page (text/table/image/pdf/json/media/geotiff/seismic/LAS) | `closure_preview` install + ui_pages_data/preview + ingest registry | hub0 数据 page (adopts shell workspace), hub4 可视化 preview | COMPLETE | closure-wave 04 acceptance; pa_flow 143 checks |
| 14 | Geomodel viz (builders/QC/section/measurements/export) | `libs/geomodel` + geo3d workspace controller | Geo3D workspace objects + advisor/export flows (11) | COMPLETE | geomodel oracle suites; export/advisor E2E in `viz_c.joint_analysis` |
| 15 | Paleo map canvas + facies + legend/north/scale/title | QGIS runtime + `closure_mapping` + mapping_document/composer | hub3 编图 page + composer templates (25 component types) | COMPLETE | cartography/mapping oracle suites; layout_export self-check |
| 16 | Professional figure export (geographic graticule/degree frame) | composer grid is mm-decorative only | QGIS layout export path | **GAP** | limitation #3 |
| 17 | 2D fence VD profile (profile_2d) | — (3D curtains only) | — | **GAP** | limitation #2 |
| 18 | Cartography free-item editor window | — (engine-level; no Python product entry either) | — | RETIRED/REFERENCE | Python window unreachable from both products' UIs (audit A) |

Rows 1–7, 9–15, 17 classifications unchanged by reviews; GAP rows are the
explicit unfinished-migration items (NOT environment limits) — see
`11-known-limitations.md`.
