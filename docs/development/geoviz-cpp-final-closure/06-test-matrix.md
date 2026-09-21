# 06 — Test matrix

Full-suite result at final HEAD: see `12-final-verification.md`
(**247/247 CTest green** in the correct environment; the 14 "failures" in a
bare environment are libodbc/onnxruntime environment issues, reproduced
and explained there).

## Geoviz-relevant suites (selection)

| Suite | Covers | Status |
| --- | --- | --- |
| `viz_a.*` + science.viewer gates | LAS load (WLE), tracks, patterns, robust scale | green (viewer stack in config) |
| `viz_b.*` (3 suites) | cross-well canvas/DTW/well-tie oracle + MALLOC audits | green |
| `viz_c.joint_oracle` / `joint_scene` / `store_concurrency` / `joint3d_closure` | joint core + platform host (multi-fence, project state, teardown, real fixtures) | green |
| **`viz_c.joint_analysis` (new)** | hooks contract: sidecar round-trip, RGB overlay geometry (40×40/3042 faces), demo stratal end-to-end, **real .dat E2E over the frozen volume** (render-space verts, z within sample bounds), refusal texts | green (5 cases) |
| `viz_d.*` (core/widget/preview/closure) | slice widget, horizon picks, exports, view state, **wiggle-pins-attribute regression (new)** | green |
| `seismic_attributes.*` (4) | E-line + S-line oracles vs pinned geoviz fixtures; registration contract (11 ids incl. c3 coexistence) | green |
| `science.coherence_c3_oracle` | C3 vs 7 frozen fixtures (real tiny.sgy windows) incl. negative self-check | green (pre-existing; kernel newly product-registered) |
| `geo3d_viz.*` (27) + ui_wellseis suites | scene manager, workspace controller, pages (incl. new 振幅-leaf vocabulary assertions) | green |
| `platform.*` | MainWindow construction, capabilities parity, self-check battery, python-free ldd | green |

## Oracle discipline

Every numeric kernel port in scope keeps its frozen-Python oracle
(seismic attributes, well tie, horizon parse, DTW, C3, viz_charts,
joint core). This branch added **no new numeric kernel** (the C3 wiring
reuses `libs/algorithms`' oracle-frozen kernel; the first-duplicate C3
port written in-session was caught and deleted before commit). The one
new numeric glue (grids_fn: parse → fill → stride-lattice resample →
ms→sample) is exercised by the real-volume E2E and the sline-oracle-backed
kernels it composes; its nearest Python counterpart semantics
(`build_stratal_grids`) were line-audited in review round 1 (P3-1: the
stride-lattice direct take is exactly numpy `map_coordinates(order=1)`
at integer lattice points).
