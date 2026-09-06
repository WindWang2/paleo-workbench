# 00 — Baseline: Scientific Audit Before Coding

Program: **Scientific Interpretation & Algorithm V6**
Branch: `feat/scientific-interpretation-v6` (base: main @ 295fabc3)
Method: five parallel read-only audits (A–Q) over wells, coordinates/seismic,
interpolation/constraints, factor maps/fusion/QC, and harness/native parity.
Every claim below carries a `file:line` reference valid at the base commit.
Paths are relative to the repository root (superproject) unless prefixed
`WT\` (= worktree root, identical content at base).

The audit thesis — *"a result must never look scientifically valid when an
input unit, identity, null convention, coordinate convention, geological
constraint, calibration, or algorithm capability was actually missing or
ignored"* — is **violated today in 7 P0-class ways and ~20 P1-class ways**,
enumerated in the defect register at the end of this document.

---

## 1. Wells: parsing, engine adapter, correlation, registry (A–D)

### 1.1 Operation baseline

| operation | scientific inputs | units | depth domain | identity | null semantics | constraints | outputs | provenance | unsupported cases | silent-approx risk |
|---|---|---|---|---|---|---|---|---|---|---|
| LAS header inspect (`geo-viz-engine/.../las_preview.py:126-214`) | ~V/~W/~C blocks | per-curve unit string kept; depth unit not promoted to document | DEPT/DEPTH else curve 0 | `well_name` = WELL item else file stem — **display name** | **inferred −999.25 default when file declares none** (`:141`) | — | LASPreviewHeader | header facts | wrapped rows via token reassembly | HIGH |
| LAS read (python) (`las_preview.py:217-403`) | ~A rows | raw passthrough | null/non-finite depth rows dropped | n/a | sentinel `abs_tol=1e-6` → NaN | — | float64 arrays, NaN preserved | decimation info only | — | LOW |
| LAS read (fast native) (`native_backend.py:890-979`) | full text | none | declared index | same | `np.isclose` 1e-6 vs **exact `==` in native tokenizer** (`:875`); fast API default sentinel **−999.0** (`:891`) | — | sampled arrays | same | wrapped files → python path | MED |
| Interchange LAS inspect (`paleo_workbench/interchange/adapters/las_adapter.py:59-272`) | header + stream | units per mnemonic | STRT/STOP/STEP, monotonic detection | well_name | −999.25 default (`:123,215`) | — | InspectionResult | warnings | >64 MB skip depth scan | MED |
| XML well-log load (`xml_preview.py:195-220`) | rows | none | **hardcoded `<= -9000` null threshold** | well_name | unbounded inferred threshold | — | arrays | none | — | HIGH |
| Well tops .dat (`resources/well_tops_parser.py:16-43`) | 8-col rows | **MD unit undeclared, assumed m** | MD | **display name only** | garbage rows silently skipped | — | WellTop rows | none | short rows | MED |
| Load façade (`viz/well_log_load.py:158-182, 348-350`) | LAS/XML | `detect_depth_unit` **falls back `"m"` for unknown/undeclared/error**; wrapper only when `!= "m"` | preview (100k cap) vs full-res caches separated | (path, mtime) cache | upstream conversion | — | WellLogData (+unit wrapper) | decimation provenance | — | MED |
| depth_shift (`workflow/curve_interpretation.py:56-58,180-183`) | delta_m | **no unit check — raw add** | file axis | — | — | — | DERIVED version | full (op/params) | — | MED |
| resample (`workflow/curve_operations.py:220-262`) | step | no unit check | file axis | — | **`interp_nan_aware` bridges NaN holes linearly** (`:243-262`) | — | DERIVED | step recorded | — | MED |
| depth_unit_normalize (`curve_interpretation.py:201-214`) | target unit | whitelist convert, **empty unit → `"m"`** (`:203-205`) | — | — | — | — | DERIVED | unit_from/to | — | HIGH |
| Derived LAS write (`curve_interpretation.py:255-329`) | op result | STRT/STOP `or "M"` (`:306`) | — | — | **writes `NULL -999.25` when source declared none** (`:313-317`) | — | DERIVED version | create_derived | — | MED |
| Engine submit prep (`viz/welllog_engine_adapter.py:273-300, 557-567`) | depth/values | `_normalize_depth_unit` **unknown → `"m"`** (`:303-314`) | arrays | document/curve ids = `stable_entity_id(well_name)` — **name-keyed** | **non-finite pairs filtered + compacted; `null_indices` never submitted** | — | engine payload | diagnostics list | — | HIGH |
| Multi-well submit (`viz/welllog_multi_well_adapter.py:142-276`) | logs + tops | per-well unit accepted, **no cross-well harmonization; raw shared range** (`:245-259`) | first well's unit pinned (`scene.cpp:3903-3922`) | `rid = resource_ids[i] else name` — **name fallback collides** (`:186,219`) | same filtered arrays | — | payload + parity snapshot | snapshot | no binding → raise | HIGH |
| Tops save (`workflow/correlation_session.py:20-106`; `ui/pages/stratigraphy_correlation_page.py:832-846, 926-990`) | canvas rows | depth 0.0 default when missing | per-top depth_domain | `stable_top_id = sha(well_id\|name\|marker)` — **name-keyed when well_id empty**; page `name→rid` dict — **duplicate names: last rid wins** | NaN depths skipped | — | catalog artifact | full (fingerprint, versions) | — | HIGH |
| Tops overlay (`correlation_session.py:306-342`) | payload tops | MD assumed | per-top | **same-name top from another well passes all filters** (`:324-329`) | — | — | overlay rows | — | — | HIGH |
| Tops load (`workflow/stratigraphy_correlation.py:98-163`) | stratification rows | MD, **default 10 m thickness** (`:160`) | MD | `tops_by_well[name]` — **merge across duplicate-named wells/files** | malformed → warnings | — | dict name→tops | warnings | — | HIGH |
| Section datum shifts (`viz/well_section_datum.py:14-65`) | wells | **raw units, no harmonization** | MD/TVDSS/marker | shifts **keyed by name — duplicates overwrite** | missing KB → 0 + diag | — | dict name→shift | diagnostics | — | HIGH |
| DTW top recommend (`viz/formation_top_correlator.py:94-175`) | curves/axes | **fallback grid 0.0 start / 0.5 m step** (`:132-135`) | asc/desc | — | NaN-aware | — | recommendation | confidence | silent when no axes | MED |
| Registry binding (`project/domain.py:700-760`; `catalog/domain_binding.py:331-418`) | extracts | — | — | `resolve_well` **rebuilds WellRegistry per extract** (O(N·W·K) per pass); ambiguity refused | — | — | entity links | link upserts | — | scale defect |

### 1.2 Key answers

- **Depth unit defaulting sites** (the `or "m"` family):
  `well_log_load.py:167,173,177,182`; `welllog_engine_adapter.py:314,423`;
  `curve_interpretation.py:203-205,306`; `ui/pages/well_log_canvas_panel.py:208`
  (this one is fail-closed after detection); `harness/actions/well.py:409`
  (hardcoded `"m"`); `workflow/correlation_overlay.py:199` (empty → m);
  `viz/hosts/well_tie_host.py:188-193`; `stratigraphy_correlation.py:160`;
  wellplot-desktop `core_model.py:139,169,205`, `core_dialog.py:68`.
- **Curve ops unit validation**: only `unit_conversion` and
  `depth_unit_normalize` validate (whitelist, raise on unknown);
  `depth_shift`/`resample`/DTW-step do not inspect the axis unit at all.
- **Duplicate-name tops leakage**: page map `stratigraphy_correlation_page.py:832-835`
  collapses duplicates (guard at `:931-939` checks lengths only);
  `stable_top_id` name-keyed; `tops_overlay_for_well` name-passes;
  `stratigraphy_correlation.py:117` merges by name; engine
  `document_id` falls back to name. The codebase's own
  `viz/joint_well_identity.py:63-95` (occurrence ordinal + geometry hash)
  is the correct pattern these paths lack.
- **Registry scale**: `bind_well_extracts` = O(N·W·K) construction +
  O(N·W) scans + O(N·L) link upserts per pass (`domain_binding.py:348-417`);
  registry rebuilt per extract instead of per pass.
- **Gap rendering**: the native engine **can** split runs at nulls
  (`well-log-engine/src/scene/curve_lod.cpp:109-115,495-527`, `scene.cpp:831-835`)
  and engine-native LAS IO builds null bitmasks (`src/io/las.cpp:162-225`),
  but the workbench adapter pre-filters/compacts non-finite pairs
  (`welllog_engine_adapter.py:288-299`) and the payload schema carries no
  nulls key (bridge always sets `Curve.nulls = {}`,
  `well-log-engine/src/python/numpy_bridge.cpp:583,627`). Legacy QPainter
  path splits at NaN (`curve_track.py:52-77`). → **engine backend bridges
  gaps as straight lines; fallback does not; no rendering-level parity test**.
- **Null sentinels**: three inconsistent defaults (−999.25 / −999.0 /
  −9000-threshold) + tolerance mismatch (1e-6 vs exact) + derived-LAS writer
  *injects* a `NULL` declaration the source never had
  (`curve_interpretation.py:313-317`). Declared-vs-inferred is nowhere
  distinguished in Python models.

## 2. Coordinates, calibration, SEG-Y geometry, seismic interpretation (E–G)

### 2.1 Operation baseline

| operation | scientific inputs | units | coordinate domain | identity | null semantics | outputs | provenance | unsupported | risk |
|---|---|---|---|---|---|---|---|---|---|
| `TimeDepthCalibration` (`viz/coordinate_hub.py:79-101`) | (MD, TWT) pairs | m→ms | per well | well_id + provenance | out-of-range → None (fail-closed) | conversions | checkshot/td-table authority | <2 pairs, non-monotonic rejected | LOW |
| Hub well↔twt (`coordinate_hub.py:304-338`) | well_id+MD | m/ms | MD↔TWT↔(IL,XL) | calibration | no calibration → None | cursor | authority | — | MED (IL/XL from possibly default grid) |
| Hub map↔seismic xy (`coordinate_hub.py:521-582`) | x,y / il,xl | m | bin grid | bin-grid geometry | degenerate → ValueError | nearest int | bin-grid | — | **MED — fabricated default grid (origin 100,200 / 25 m bins) answers when no survey bound** (`:209-213`; reinstalled at `ui/view_coordination.py:263`) |
| Typed conversions (`viz/domain_coords.py:273-522`) | typed coords | m/ft/ms | all | authority strings | ok=False + reason codes | typed values | authority travels | CRS compare only when both tagged | LOW |
| Trajectory (`coordinate_hub.py:120-198`) | stations | m | local x=east/y=north | — | no stations + no TD → **fabricated 0–10000 m vertical line** (`:136-142`) | md/tvd/x/y | — | azimuth reference unverifiable | MED |
| SEG-Y scalar (`geoviz_seismic/loader.py:91-105`) | byte 71-72 | — | header→m | per-trace | **read-exception → 0 → identity** (`:91-95`) | scaled xy | — | — | MED |
| Corner/bin-grid inference (`loader.py:108-189`) | 3 corner traces | m | XY↔bin | headers | missing → None (fail-closed) | BinGridGeometry | headers | GroupX/Y never consulted; inconsistent scalars unchecked | MED |
| Text-header survey (`geoviz_well_seismic_3d/segy_survey.py:115-253`) | EBCDIC regex | m | IL/XL↔XY | source label | mismatch → trace scan | corners | cross-checked | **hardcoded 40.014634 m spacing repair** (`:24,60,310-316`) | MED |
| Trace-scan survey (`segy_survey.py:323-459`) | SourceX/Y raw ints | **unscaled** | corners | source label | missing → `or 0` | corners | — | — | **HIGH — SourceGroupScalar never applied; footprint wrong by scalar factor** |
| `survey_from_corners` (`geoviz_well_seismic_3d/survey.py:57-163`) | 3 corners + counts | m | SurveySpec | — | — | spec | — | **zero-length edges fabricate spacing=1.0 m → valid-looking survey at (0,0)** (`:120-121`) | HIGH |
| Loader meta (`loader.py:228-288`) | headers | ms | axes | geometry_source label | pseudo mock ilines=[1] | meta | labelled | **first-diff uniform step assumption** (`:277-279`); **dt fallback 4.0 ms** (`:249-254`) | MED |
| Picks sync (`viz/picking_controller.py:82-162`) | (IL,XL,TWT) | ms | survey→grid | interpretation_id | between-node → None **silently dropped** (`:143-145`) | draft patch | engine picks | — | MED (no reject count) |
| Draft NaN convention (`viz/interpretation_draft.py:124-155`; `ui/pages/seismic_view_panel.py:905-915`) | rows/cols/values | ms | grid | fingerprint | NaN = not interpreted, never 0 | patch/artifact | lineage | out-of-grid raises | LOW |
| Engine TD table (`geoviz_well_seismic_3d/models.py:116-122`) | table | m↔ms | per well | — | **clamps outside range ("extrapolates with edge values")** | trajectories/tops | — | — | **P1 — contradicts hub fail-closed policy** |

### 2.2 Key answers

- **CRS guessing**: hub itself never guesses; guess sites are
  `project/models.py:36-38` (default `EPSG:4326`),
  `services/geological_mapping_service.py:160-166` (`or "EPSG:4326"`),
  `ui/workstation/composite_document.py:510,1159,1599`,
  `resources/well_location_xml.py:68-72`, `layer_tree_panel.py:182`,
  geoviz_plots `crs/__init__.py:20` (contextvar default),
  `agent/agents/gis_agent.py:56` (hardcoded EPSG:4547).
  SEG-Y chain reads no CRS at all; `bin_grid is None` → honest 未标定.
- **Velocity/depth==time**: workbench call sites verified fail-closed
  (`_require_velocity` raises; `publish_depth_cursor` refuses;
  `select_depth_transform` defaults NONE). Exception: engine
  `TimeDepthTable` clamps outside calibrated range (above).
- **Scalar unification verdict**: ONE helper (`_apply_coord_scalar`,
  `loader.py:98`) wired at ONE site (`loader.py:130`). The trace-scan
  survey builder (`segy_survey.py:359-364,404-411`) and spacing
  (`:63-112`) never apply it. GroupX/GroupY used nowhere.

## 3. Interpolation methods × constraints (H–L)

Methods in production:

| method | file:line | constraints honored | silently ignored | duplicates | zero-distance | variance | notable risks |
|---|---|---|---|---|---|---|---|
| IDW (workflow) | `geoviz_plots/interpolation/idw.py:195` | barriers (break lines routed as faults) | **boundary mask, anisotropy, trend weights** (computed by host for every method at `workflow/factor_interpolation.py:415-417`, consumed only by directional) | none — double-vote | ε=1e-12 floor (≈1e24 weight) | no | full-rectangle extrapolation |
| Ordinary kriging | `geoviz_plots/factor/kriging.py:311,528` | **none** | **barriers dropped for non-IDW backends** (`geoviz_plots/factor/interpolation.py:317,357`); anisotropy recorded as None | exact-dup → mean | C(0)=sill | **yes** + exact LOO + fit diagnostics | auto-fit silent; isotropic only |
| Kriging numpy fallback | `mapping/geological_pipeline/interpolator.py:459` | none (post-mask only) | same | tol-1e-9 mean-merge (reported) | — | yes | **different variogram fitter than engine (12 bins/0.5·dmax vs WLS) — silent surface switch on ImportError** |
| Pipeline IDW | `interpolator.py:115` | boundary ring post-mask (never set by workflow) | anisotropy fields are **dead** (`mapping/geological_pipeline/models.py:114-115` no consumer) | none | exact-hit takes value | no | separate semantics from workflow IDW |
| Spline (cubic/linear/nearest) | `geoviz_plots/interpolation/scipy_grid.py:14` | convex hull of samples (not user boundary) | barriers, anisotropy, user rings | none (Qhull degenerate → silent nearest fallback, flagged degraded) | exact at samples | no | hull regime differs from IDW/kriging |
| RBF | `scipy_grid.py:55-57` | hull | same | none | exact | no | **not reachable from UI** (`tokens.py:311`) |
| Directional trend | `geoviz_plots/interpolation/directional.py:163` | azimuth + semi-axes (multi-line **averaged into one global angle**, `factor/directional.py:54-67`) | barriers, boundary | none | nearest fallback | no | only consumer of q/b_i weights |
| Constrained IDW (vendored) | `_vendored/haiyou_constrained_idw/drawing/single_factor/constrained_engine.py:582`; adapter `workflow/constrained_idw_adapter.py:507` | **all four** (boundary rings, barrier LOS + region partition, corridor anisotropy, declustering) | q/b_i | first-wins (reported) | exact-hit rule | no | **host+engine magic constants shape output invisibly** (ratio floor 16/default 18; search 1.05×diag; decluster 0.15×search; anchor 4/10·step; residual cap 0.16 span; corridor 0.35; buffer formula; 300 m degree buffer; grid clamp 20–200); rich engine diagnostics **discarded** by `FactorGridResult.from_constrained_idw_dict` (`workflow/factor_grid_result.py:466-529`) |

Sample prep is **not shared**: workflow tasks export via
`sample_points_from_well_table` (`workflow/well_table.py:142`, QC `ok`-only),
each backend re-parses with its own extractor; the geological-mapping-service
path has a separate prep with different QC acceptance (`ok|good|""`,
`mapping/geological_pipeline/models.py:50-55`); CV scorer is QC-blind.
No artifact anywhere records "requested N / applied M / ignored K" constraints
— the fingerprint even *changes* silently when a constraint is backend-gated
away (`workflow/interpolation_fingerprint.py:156-169,217+`).

## 4. Factor maps, contour/polygon QA, fusion, MapProduct gate (M–O)

- **Factor units**: curated name-alias table `FACTOR_DEFAULTS`
  (`workflow/factor_units.py:27-92`; "porosity"→"%", unknown → None) — a
  declared-by-name unit, **never validated against value magnitudes**; a
  0–1 fraction column named porosity is silently declared "%".
  Unit travels task → grid → contour label → quality_metrics.
- **Contouring** (`mapping/geological_pipeline/contouring.py`): nodata cells
  skipped (contours never cross nodata) but skipped count unreported;
  endpoint stitching rounded 6 dp; **polyline `length` Euclidean in CRS axes
  (degrees under EPSG:4326 default)**.
- **Polygonization** (`mapping/geological_pipeline/polygonization.py`):
  holes/islands assigned with promotion counted; min-area drop visible in
  `polygon_qc`; **`area`/`area_percent`/`min_area` in square degrees under
  geographic CRS with no unit label**; default thresholds = data-derived
  ⅓/⅔ span **not recorded** in QC; `repair_invalid_geometry` swallows
  exceptions returning invalid geometry (`mapping/topology.py:176-179`).
  Engine filled-contours silently drop clipping when shapely absent/invalid
  ring (`geoviz_plots/surface/marching_squares.py:86-93`).
- **Fusion** (`workflow/factor_fusion.py`): weighted-evidence (membership
  bounds + per-cell weight renormalization; no-evidence stays NaN;
  confidence = coverage×agreement) and rule-based (first match wins,
  explicit default class). Defects: **threshold/bounds unit-consistency
  never checked against grid units**; `_aligned_or_raise` compares
  shape/axes but **not CRS** (`:287-298`); factors without variance grids
  contribute weight but zero variance → **fused variance understated**
  (`:364-377`); confidence/variance grids **not persisted** by
  `register_output` (only likelihood); `sensitivity_report`
  (leave-one-factor-out, `:473-524`) implemented but **wired to no
  production path**.
- **MapProduct gate** (`workflow/map_product.py:603-628`): assembly refuses
  mock/mixed factors, unpersisted grids, missing payload; publish gates only
  (1) not superseded, (2) staleness fingerprint. **Not gated**: QC report
  status, units declared, CRS explicit, constraint diagnostics,
  fallback-renderer state, uncertainty attachment. Ghost-run prevention is
  strong elsewhere (demote-to-pending on evicted grid; failed registration
  compensates run). Workspace V5 staleness is honest and warn-only.

## 5. Harness actions, native parity, tests (P–R)

- **51 ActionSpecs registered**; honest unavailability is structural
  (`ActionUnavailableError` → status `unavailable`, never fabricated).
  But: **15 of the 17 requested scientific actions are missing**
  (`well.validate/describe_units/process_curve/resample/list_tops`,
  `seismic.validate_geometry/describe_calibration`, the entire
  `factor.*` family, `map.describe_product`, `map.publish`);
  `interpolation.kriging/idw` providers exist but are unreachable (nothing
  populates `factor_datasets`).
- **Verifiers**: 50/51 specs declare none; executor auto-verification
  reaches only grid-shaped `values` and map documents. `well.process`
  (WRITE) commits QC annotations with no scientific verification.
- **Render-decimation leak**: `seismic.get_slice(lod>0)` returns
  stride/mean-decimated arrays as scientific payload (labelled but
  unenforced); `well.open`/`well.describe` load via the 100k-decimated
  preview loader into the session's scientific log stash with **no
  decimation disclosure** (`harness/actions/well.py:309,451`) — violating
  the repo's own #1193 policy (only the prediction provider honors it).
- **Provenance**: `ActionResult` has no provenance field;
  `map.create_factor_map` starts runs with `input_version_ids=[]` and
  swallows registration failure.
- **Parity**: 12 native functions with fallbacks; SymmetricParityContract
  tests exist but all C++↔Python legs skip on a build-less machine, and
  `test_native_backend.py` self-parity passes **vacuously**; no
  native-vs-legacy *rendering* parity for well-log gap semantics.
- **Tests**: ~640 files / ~6000 tests; fast gate
  `-m "not slow and not welllog_binding"`; expected skips on fresh venv:
  qgis (43 files), welllog_binding, opengl, native parity files, osgeo.
  **Pre-existing failure on main**: `tests/e2e/test_integrity_guard.py::test_no_tautological_assertions`
  (5 tautological assertion sites) — confirmed before any V6 change.

---

## Defect register (merged, ranked)

### P0 — invalid-science bugs (fix in this program)

| # | defect | site |
|---|---|---|
| P0-1 | Engine backend bridges NaN gaps as straight lines (missing data rendered as trend); no null channel in payload; parity break with legacy renderer | `welllog_engine_adapter.py:288-299,557-567`; `numpy_bridge.cpp:583,627`; legacy splits at `curve_track.py:52-77` |
| P0-2 | Display well name used as identity across correlation/tops/datum/multi-well — duplicate names collide, leak, overwrite | `stratigraphy_correlation_page.py:832-835`; `correlation_session.py:20-29,324-329`; `stratigraphy_correlation.py:117`; `well_section_datum.py:31-57`; `welllog_multi_well_adapter.py:186,219`; `stratigraphic_correlation_engine.py:187-203` |
| P0-3 | Undeclared/unknown depth unit silently treated as meters across load→ops→overlay→engine submit | `well_log_load.py:182`; `welllog_engine_adapter.py:314`; `curve_interpretation.py:203-205`; `correlation_overlay.py:199-211`; `harness/actions/well.py:409` |
| P0-4 | Trace-scan SEG-Y survey ignores SourceGroupScalar — footprint wrong by scalar factor; scalar applied at only 1 of its consumer sites | `segy_survey.py:359-364,404-411,63-112`; helper `loader.py:98-105` |
| P0-5 | Valid-looking 1 m-bin survey fabricated from all-zero coordinates | `survey.py:120-121` |
| P0-6 | Constraints silently ignored by kriging/spline/directional in the workflow path (faults dropped for non-IDW; `n_break_lines: 0` reported while UI shows faults) | `factor_interpolation.py:409-417`; `geoviz_plots/factor/interpolation.py:317,357` |
| P0-7 | `map.create_factor_map` dialog/agent path ignores ALL constraint layers for both offered methods | `geological_mapping_service.py:174-246`; `create_factor_map_dialog.py:104-142` |
| P0-8 | Harness well actions feed decimated preview logs into scientific session stash without disclosure | `harness/actions/well.py:309,451` vs policy `well_log_load.py:217-228` |
| P0-9 | One well's predicted facies attached to every correlation well, stretched to each span | `stratigraphy_correlation.py:67,81-83`; `viz/prediction_helpers.py:98-103` |
| P0-10 | Area/length/min-area geometry math in raw CRS units (square degrees under geographic default), unlabelled | `polygonization.py:15-23,94-113,434-447`; `contouring.py:59-64,441` |

### P1 — honesty/provenance/scale defects

| # | defect | site |
|---|---|---|
| P1-1 | Null sentinel anarchy: −999.25 default for undeclared files; −999.0 fast-API default; −9000 XML threshold; 1e-6 vs exact match; derived-LAS injects NULL declaration | `las_preview.py:141`; `native_backend.py:875,891`; `xml_preview.py:204-216`; `curve_interpretation.py:313-317` |
| P1-2 | `resample` interpolates ramps across NaN holes | `curve_operations.py:243-262` |
| P1-3 | O(N·W) registry rebuild per extract | `domain.py:723-727`; `domain_binding.py:348-417` |
| P1-4 | Engine TD table extrapolates by clamping (contradicts fail-closed policy) | `geoviz_well_seismic_3d/models.py:116-122` |
| P1-5 | Loader assumes uniform IL/XL step from first diff; dt fallback 4.0 ms | `loader.py:277-279,249-254` |
| P1-6 | Hub fabricated default bin grid answers map↔seismic before any survey bound | `coordinate_hub.py:209-213`; `view_coordination.py:263` |
| P1-7 | Boundary/coverage regime switches silently with method (rect vs hull vs rings) | interpolation §3 above |
| P1-8 | Duplicate-sample semantics differ per method (double-vote / mean / first-wins) | §3 |
| P1-9 | Two variogram fitters; silent surface switch on ImportError | `kriging.py:222` vs `interpolator.py:410-456` |
| P1-10 | Constrained-IDW magic constants shape output invisibly; diagnostics discarded | `constrained_idw_adapter.py:213-222,449-471`; `factor_grid_result.py:466-529` |
| P1-11 | Fusion unit-consistency unchecked; CRS not compared in alignment; variance understated when factors lack variance; confidence/variance not persisted | `factor_fusion.py:89-92,287-298,364-377,539-573` |
| P1-12 | Publish gate omits QC-status/units/CRS/constraint-diag/fallback/uncertainty checks | `map_product.py:603-628` |
| P1-13 | Verifier coverage near-zero for scientific WRITE actions; 15/17 requested actions missing | harness §5 |
| P1-14 | `seismic.get_slice(lod>0)` decimated payload unenforced | `harness/actions/seismic.py:89,256-276` |
| P1-15 | Factor unit declared by name, never validated against magnitudes | `factor_units.py:27-92` |
| P1-16 | Default facies thresholds data-derived but unrecorded in QC | `polygonization.py:369-375` |
| P1-17 | Engine filled-contour clip silently dropped | `geoviz_plots/surface/marching_squares.py:86-93` |
| P1-18 | `sensitivity_report` dead in production | `factor_fusion.py:473-524` |
| P1-19 | Mixed m/ft wells composited on one unconverted shared range | `welllog_multi_well_adapter.py:245-259`; `scene.cpp:3903-3922` |
| P1-20 | `map.create_factor_map` provenance: empty lineage + swallowed registration failure | `harness/actions/mapping.py:388-421` |

### P2 — targeted improvements

Dead anisotropy options (`mapping/geological_pipeline/models.py:114-115`);
RBF unreachable from UI; directional multi-line averaging; QC-filter
inconsistency (`ok` vs `ok|good|""`); float32 grid downgrade; R² sign
conventions differ by path; contour endpoint 6-dp rounding; nodata counts
absent from contour/polygon QC; `repair_invalid_geometry` exception
swallowing; `area_percent` over full padded bbox; `data.search` fallback not
flagging degraded; `register_all` swallowing domain failures; vacuous
self-parity on build-less machines; doc drift (ADR 0066 "20 actions" vs 51);
trajectory fabrication for station-less wells; CRS fallback sites
(`geological_mapping_service.py:166`, `composite_document.py:510,1159,1599`);
`_header_int` exception→0 conflation; TD-table ms unit assumption
(`joint_well_parsers.py:104-105`); DTW fallback grid fabrication
(`formation_top_correlator.py:132-135`); `_finite_pairs` silent length
truncation; LAS→CSV null contract loss; duplicate marker names collapse
(`formation_top_correlator.py:56-62`); pick rejection counts unreported.

### Preserved strengths (do not regress)

haiyou ATTRIBUTION/byte-parity discipline; fail-closed kriging numerics
(#145/#877/#118); synthetic-data anti-laundering (#848); explicit
distance-policy annotation (D5); honest CV authority (#921); TimeDepth
fail-closed policy in the hub; NaN-not-interpreted draft convention;
ghost-run demotion; workspace V5 staleness honesty; `joint_well_identity`
duplicate disambiguation; catalog single-write-path (ADR 0056).

---

## Baseline test status (Windows cp312 fresh venv, offscreen)

Fast gate `-m "not slow and not opengl and not qgis"`:
**pre-existing failure on main** — `tests/e2e/test_integrity_guard.py::test_no_tautological_assertions`
(5 tautological sites in test files). No V6 changes were present when
measured. Full-suite baseline recorded in `baseline_tests_full.log`
(program artifact, not committed).
