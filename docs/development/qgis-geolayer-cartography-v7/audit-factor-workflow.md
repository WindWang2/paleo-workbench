# Audit: Scientific Factor-Map & Map-Product Workflow

Worktree: `.worktrees/qgis-geolayer-cartography-v7` (branch `qgis-geolayer-cartography-v7`).
Scope: `paleo_workbench/workflow/factor_*`, `workflow/map_*`, `mapping/geological_pipeline/**`, factor/map/scientific harness ActionSpecs, and the FactorGridResult → layers/canvas/RGBA-mirror flow. All file:line refs are to this worktree.

---

## 1. Factor Pipeline Flow (end-to-end)

### 1.1 Stage flow diagram (data, not UI)

```
WellTable / WellEntity / PaleoMapDocument constraints
        │  (a) workflow path                    │  (b) geological_pipeline path
        ▼                                       ▼
workflow/factor_interpolation.py           services/geological_mapping_service.py
  apply_interpolation_to_task (:450)         → mapping/geological_pipeline/pipeline.py
  batch_prepare_factor_maps (:667)             GeologicalMappingPipeline.extract_factors (:121)
  │                                            GeologicalMappingPipeline.interpolate (:337)
  │  engines: geoviz facade (IDW/kriging/     │  engines: geological_pipeline/interpolator.py
  │  spline/directional) or vendored             KrigingInterpolator (:29) / IDWInterpolator (:115)
  │  constrained-IDW (constrained_idw_adapter)   interpolate_factor dispatcher (:650)
  ▼                                       ▼
FactorGridResult  (workflow/factor_grid_result.py:239)   ← single typed authority
        │ store_live_factor_grid (project/factor_grid_artifacts.py:287)
        │ write_grid_artifact → .factor_grid.npz (catalog/grid_artifact.py:46)
        ▼
FactorMapTask (project/models.py:158) — metadata only (grid_metadata, artifact ids)
        ├── viz/native_factor_map.scene_from_factor_task (:771) → C++ ScalarGridLayer → canvas/QGIS RGBA mirror
        ├── geological_pipeline.contouring/polygonization → ContourMapLayer / PolygonMapLayer
        ├── workflow/contour_draft.py → ContourDraft (editable isolines)
        └── workflow/map_product.assemble_map_product (:82) → catalog OUTPUT + MapProductRecord
```

### 1.2 Input models

| Model | Location | Key fields |
|---|---|---|
| `WellTable` / `WellTableRow` | `project/models.py:145` / `~:130` | `rows[].well_id,name,x,y,z,H_s,H_t,R_s,qc_flag,attributes`; `linked_factor_task_id` |
| `FactorMapTask` | `project/models.py:158-181` | `id, name, target_horizon, factor_type, input_resource_ids, well_table_id, method, parameters, output_resource_ids, quality_metrics, status ("pending"/"complete"/"failed"), source_kind (real/imported/mock/mixed), input_snapshot_hash, generator_version, seed, grid_artifact_path, grid_artifact_version_id, grid_metadata` |
| `ConstraintLayers` / `ConstraintLine` | `project/models.py:304` / `:281` | see §3 |
| `UserVectorLayer` | `project/models.py:550` | digitized vector layers; `template` key = geological template; `field_schema`, `features` |

### 1.3 Factor extraction

* `GeologicalMappingPipeline.extract_factors` — `mapping/geological_pipeline/pipeline.py:121-335`.
  * CRS-consistent coordinate key families `(project_x,project_y)/(x,y)/(lng,lat)/(longitude,latitude)/(surface_x,surface_y)` — `pipeline.py:52-58`; presence tested with `is not None` (`_first_present`, `:97`); mixed-family detection logged + diagnostics (`:311-327`).
  * Alias groups for factor mnemonics — `pipeline.py:71-82` (e.g. sand_ratio ↔ 砂地比/R_s).
  * Derived-factor rules (D11): `sand_ratio = H_s/H_t`, `formation_thickness = base−top` with `derived` provenance marker in point metadata — `pipeline.py:219-273`; rule constants in `workflow/factor_units.py:144-145`.
  * Output `GeologicalFactorDataset` (`geological_pipeline/models.py:35`) with `valid_points`, `to_arrays`, `extent` (10% padded), `validate`.
* `GeologicalMappingService.extract_well_factors` — `services/geological_mapping_service.py:34` (WellTables → WellEntity fallback).

### 1.4 Interpolation (two parallel authorities)

**Workflow task path** (`workflow/factor_interpolation.py`):

* `METHOD_LABEL_TO_ENGINE` — `:126-136`: 克里金→kriging, IDW, 样条, 方向趋势, 约束IDW→`CONSTRAINED_IDW_ENGINE_LABEL` (`constrained_idw_adapter.py:45`).
* `apply_interpolation_to_task` — `:450-631`: loads `sample_points` from task parameters; resolves project constraint layers (`:476-484`); evaluates requested-vs-capability constraints BEFORE interpolating (`:512-515`, see §3.4); fingerprints inputs (`:518`); dispatches to plan-backed IDW (`:532-562`), vendored constrained-IDW (`:564-582`), or geoviz engine (`:583-617`, kriging variogram kwargs `variogram_model/range/nugget` `:587-597`).
* `_attach_result_to_task` — `:192-343`: stores `FactorGridResult` in process-global live cache, writes metadata-only parameters (`constraint_diagnostics`, `distance_policy`, variance min/max, break polylines, small `grid_boundary` ring), `task.grid_metadata = grid_result.to_descriptor()`, invalidates artifact refs (`:306-307`), `task.status = "complete"` (`:299`).
* `batch_prepare_factor_maps` — `:667-938`: fingerprint CLEAN/DIRTY classification (`:742-758`), plain-IDW geometry grouping via `InterpolationPlan` (`workflow/interpolation_plan.py`), vectorised multi-factor pass `apply_idw_plan_multi` (`:846-850`), per-task failure isolation (`_apply_interpolation_isolated`, `:346`).
* Incremental recompute fingerprints — `workflow/interpolation_fingerprint.py` (`FactorFingerprints` `:70`, `classify_factor_recompute` `:520`, `FactorDirtyState` `:59`).
* Scheduler (Stage-5) — `workflow/factor_prepare_scheduler.py`: `FactorPrepareSnapshot` (`:147`, clones only coordinate/stratigraphy/constraints/tasks), `run_factor_prepare_schedule` (`:284`), host-side `commit_prepare_batch_result` (`:647`) with generation + fingerprint stale-input guards and fingerprint-conditional live-cache eviction.
* Cross-validation — `cross_validate_factor_task` (`:1001`), `attach_cross_validation` (`:1094`, writes `cv/cv_rmse/cv_mae/cv_bias` into `quality_metrics`), `attach_surface_check` (`:1068`, in-sample residuals).

**Geological-pipeline path** (`mapping/geological_pipeline/interpolator.py`, used by services + harness `map.create_factor_map`):

* `KrigingInterpolator.interpolate` — `:29-112`: geoviz `fit_variogram`/`kriging_grid`/`leave_one_out_predictions` with pure-numpy fallback `_pure_numpy_kriging` (`:459`, sample dedup `:342`, empirical variogram `:380`, closed-form sill fit `:410`, chunked target evaluation `:548`). Returns `FactorGridResult` **with `variance_grid`**.
* `IDWInterpolator.interpolate` — `:115-260`: scipy cKDTree chunked kNN (`:198`) or BLAS all-neighbours path `_idw_all_neighbors` (`:270`); power/min/max neighbours/radius; NaN nodata.
* `interpolate_factor` dispatcher — `:650-666`: single place applying user domain ring mask `_apply_domain_options` (`:624`, ray-cast `_domain_mask` `:595`, masked-cell count recorded in `algorithm_parameters["domain_masked_cells"]`) and D5 distance policy annotation.

### 1.5 `FactorGridResult` — exact field list (`workflow/factor_grid_result.py:239-272`)

| Field | Type | Line | Notes |
|---|---|---|---|
| `grid_z` | `np.ndarray` float32 `(h,w)`, NaN=nodata | `:248` | canonical nodata `NODATA=NaN` (`:47`) |
| `grid_x` | `np.ndarray` float64 `(w,)` | `:249` | column coords |
| `grid_y` | `np.ndarray` float64 `(h,)` | `:250` | row coords (ascending y) |
| `factor_name` | `str` | `:253` | |
| `algorithm_id` | `str` | `:254` | `idw / kriging / spline / directional / constrained_idw / factor_fusion / kriging_fallback` |
| `algorithm_parameters` | `dict` | `:255` | carries r_squared, n_points, variance_min/max, constraint_diagnostics, distance_policy(+annotation), kriging_diagnostics, contour_levels, geometry_id, fingerprint fields, fusion kind/name, class_thresholds |
| `crs` | `str \| None` | `:256` | `None` = source XY, never guessed (`crs_is_known` `:309`) |
| `unit` | `str \| None` | `:257` | declared-only (`factor_units.py:130`) |
| `generator_version` | `str \| None` | `:258` | |
| `source_refs` | `list[str]` | `:259` | catalog asset/version ids; aliased `input_version_ids` (`:334-341`) |
| `run_ref` | `str \| None` | `:260` | catalog DataRun id; aliased `run_id` (`:343`) |
| `created_at` | `str \| None` | `:261` | ISO-8601 |
| `variance_grid` | `np.ndarray \| None` float32 | `:264` | kriging variance only — never fabricated |
| `boundary` | `list[(x,y)] \| None` | `:265` | closed domain ring (constrained-IDW) |
| `contours` | `dict[level_str, [[[x,y],...],...]] \| None` | `:269` | engine-refined isolines (#928), constrained-IDW runs only |
| `statistics` | `GridStatistics` (init=False) | `:272` | computed in `_finalise` (`:356-382`) |

Properties: `width/height/shape` (`:276-285`), `extent` `(xmin,ymin,xmax,ymax)` (`:288-301`), `mask = isfinite(grid_z)` (`:304`), `dx/dy/cell_size` (`:313-327`), `input_points` from `algorithm_parameters["sample_points"]` (`:330`).
Constructors: `from_engine_dict` (`:408`), `from_constrained_idw_dict` (`:465`, preserves boundary, n_break_lines/n_direction_lines, search_radius/decluster_radius/barrier_buffer_mode/duplicate_wells_dropped/r_squared_method/anchored_fidelity passthrough `:507-517`), `from_legacy_task_parameters` (`:545`), `copied()` (`:384`).
Serialisation: `to_descriptor()` — metadata only, **no grid arrays** (`:617-648`); `to_legacy_dict()` (`:650`).
`GridStatistics` — `:50-102` (`min,max,mean,std,valid_count,total_count`, float64, JSON-safe).

### 1.6 Persistence & cache

| Concern | Where | Detail |
|---|---|---|
| Live session cache | `project/factor_grid_artifacts.py:287` (`store_live_factor_grid`), `:341` (`peek`), `:371` (`clear_…_if_fingerprint`), bounded LRU by count+bytes (`:95-105`), frozen/sealed arrays (`:162-263`), axis interning pool (`:187`) | |
| Load-for-task | `factor_grid_result_for_task` — `project/factor_grid_artifacts.py:460` (live cache → managed NPZ artifact → legacy inline parameters) | |
| Managed artifact | `catalog/grid_artifact.py`: `write_grid_artifact` `:46`, `read_grid_artifact` `:159`; V2 uncompressed NPZ `grid_z/grid_x/grid_y[/variance_grid]/__descriptor__`; suffix `.factor_grid.npz` (`:35`); atomic tmp+replace (`:114` area) | |
| Task-side reference | `FactorMapTask.grid_artifact_path / grid_artifact_version_id / grid_metadata` — `project/models.py:177-181` | |

### 1.7 Typed input/output contracts (M1)

* `FactorMapSpec` — `workflow/factor_map.py:51-178`: `factor_name, method, target_horizon, unit, crs, distance_policy ("planar"/"planar_degrees"/"projected", D5), parameters, bounds, mask_polygon, exclusion_polygons, fault_polylines, source_refs, task_id, derived_rule`; `fingerprint()` `:150`; `with_declared_unit()` `:158`; `spec_from_task()` `:305`.
* `FactorMapOutput` — `workflow/factor_map.py:181-302`: `spec, grid (FactorGridResult), qc, provenance`; `from_task_result` `:197` (QC = r_squared/n_points/variance_min-max/duplicate_wells_dropped); `build_map_layers()` `:246` — delegates to `GeologicalMappingPipeline.create_grid_layer / create_contour_layer / create_polygon_layer / create_well_point_layer`.

---

## 2. Scalar → Visual Path

### 2.1 Yes — there IS a pre-rasterized RGBA mirror

| Item | Location | Detail |
|---|---|---|
| **RGBA GeoTIFF mirror for QGIS** | `paleo_workbench/mapping/scalar_raster_mirror.py` — class `ScalarRasterMirrorCache` `:18`, `ensure(layer)` `:52-80`, `_write_geotiff` `:139-202` | Consumes the **already-rasterized** RGBA array from `layer.renderer_payload.rasterize()` (`:147`). Writes a **4-band Byte RGBA GeoTIFF** (GDAL `GTiff`, TILED; COMPRESS=DEFLATE only on disk) into GDAL `/vsimem/paleo-qgis-scalar-<uuid>/<layer>-<revs>-<serial>.tif` (virtual, production) or a caller-supplied directory (diagnostics). GeoTransform from layer extent (`:170`), CRS via `osr.SpatialReference().ExportToWkt()` (`:172-175`), RGBA color interpretation (`:196-199`). Keyed by `(data_revision, style_revision, scalar data_revision, scalar style_revision)` (`:58-62`); superseded mirrors unlinked only after the bridge stops rendering (`map_render_backend.py:1862-1863, 1938-1939`). |
| Cache construction | `mapping/map_render_backend.py:1793-1805` (`QgisMapRenderBackend._native_snapshot`), gated by `qgis_scalar_pipeline_ready` (`mapping/qgis_style.py:51-69`, bridge + `osgeo.gdal`) | |
| Bridge payload | `map_render_backend.py:2044-2060` (`_qgis_snapshot`): scalar_grid layer → `{"kind": "raster", "source_path": scalar_raster_cache.ensure(layer)}` | **No scalar values cross the bridge — only the RGBA file path.** |
| QGIS layer creation | `native/qgis_render_bridge/src/qgis_render_bridge.cpp:383-389` | `std::make_unique<QgsRasterLayer>(source_path, name, "gdal")` — **default renderer** (multiband RGBA). No shader/pseudocolor applied. |

### 2.2 Is scalar data preserved for QGIS raster rendering?

* **Scalar float32 data is preserved** in exactly three places: `FactorGridResult` (live), `.factor_grid.npz` artifact (disk, catalog INTERMEDIATE/DERIVED version), `task.grid_metadata` (descriptor only). It is **never handed to QGIS**: the Python package contains **zero** `QgsRasterLayer` / `QgsRasterRenderer` / single-band-pseudocolor usage (grep-verified across `paleo_workbench/`; the only `QgsRasterLayer` is the C++ bridge opening the RGBA mirror). A QGIS user therefore cannot re-classify/stretch the factor grid — the color ramp, range and gamma are baked in host-side before the mirror.

### 2.3 Rasterisation sources (two parallel stacks)

1. **Native C++ stack (production canvas):** `viz/native_factor_map.py`
   * `MapScene.add_factor_grid` — `:218-278`: transfers `FactorGridResult` once into `grid_render_core.ScalarGridLayer` (rows flipped to north-up by `_north_up_grid` `:162-175`), sets LUT (`_rgba_lut` `:111`, named ramps `_named_color_ramp` `:125` — grayscale/warm_cool only; default from `viz/grid_render.py:38 default_rgba_lut` purple→teal→yellow), `set_color_range` (stats min/max), `set_gamma`; registry layer gets extent/CRS/`source_ref`/`provenance_ref`/`result_fingerprint` (`:254-269`).
   * Style-only mutations: `set_scalar_style` `:442` (ramp/range/gamma/nodata-transparent), `set_scalar_data` `:483`; stale-refresh upsert `_refresh_scalar_payload_if_stale` `:733` (#920); `scene_from_factor_task` `:771-840` (group + scalar + sample points + contour drafts per task).
   * `render_snapshot` — `:656-700`: emits `MapLayerSnapshot` with `layer_type="scalar_grid"`, `renderer_payload = ScalarGridLayer` object.
2. **Software QPainter stack:** `mapping/map_render_backend.py`
   * `MapRenderBackend._draw_scalar_grid` — `:1644-1667`: `scalar.rasterize()` → `QImage(Format_RGBA8888)` stretched onto layer extent.
   * Rasterisation kernels: C++ `grid_render_core.render_grid_rgba` via `viz/grid_render.py:render_grid_rgba` / `render_factor_grid`; legacy pure-python ramp LUT in `GridMapLayer.rasterize_rgba`.
3. **Legacy compose dataclass:** `mapping/layers.py` `GridMapLayer` (`:202-315`): `layer_type="grid"` internally, snapshot `layer_type="scalar_grid"` with duck-typed `_ScalarPayload.rasterize()` (`:291-311`) using `mapping/color_ramps.get_color_ramp`. Used by `geological_pipeline` MapDocuments and composer, not the unified canvas.

### 2.4 Contours (marching squares)

* **Implementation:** `mapping/geological_pipeline/contouring.py`
  * `_marching_squares_pure_python` — `:221-311`: 16-case pure-Python marching squares with linear edge interpolation, NaN-cell skipping (`:246`), saddle cases 5/10 disambiguated via cell-centre mean (`:279-306`).
  * `_stitch_segments` — `:132-218`: endpoint-hash graph stitch → open chains then closed loops; optional Douglas-Peucker (`:67`) and Chaikin smoothing (`:99`).
  * Levels: `calculate_nice_contour_levels` `:15` (1/2/5×10^k), `calculate_quantile_contour_levels` `:45`; interval or explicit list.
  * `generate_contour_layer` — `:356-475`: **output = `ContourMapLayer`** (GeoJSON `LineString` features with `level / label_text / is_index_contour / length / is_closed / factor / unit`, `levels`, `contour_interval`, style, `metadata.contour_qc` incl. clip counts); optional shapely `clip_ring` clip (`_clip_polyline_to_ring` `:314`).
* **Second contour authority (workflow):** `workflow/contour_draft.py`
  * `contour_draft_from_factor_task` — `:249-301`: prefers engine-refined isolines stored on the grid result at prepare time (`_engine_contours_for_task` `:140-195`, #928) else re-extracts via geoviz `extract_contour_lines` (`:198-220`); nice levels `suggest_nice_levels` `:67`.
  * **Output = `ContourDraft`** (`project/models.py:325-346`: `levels`, `segments[ContourSegment(level,coordinates,closed,properties)]`, `linked_factor_task_id`, `source_grid_n/backend/value_range`, `status draft|editing|final`).
  * Draft → map: `apply_contour_draft_to_map` `:355` (pushes `role=contour` line_features into `PaleoMapDocument.line_features`); export `line_features_from_contour_draft` `:327`.
  * Native canvas: `MapScene.add_contour_draft` `native_factor_map.py:543` (display-only `ContourGeometry`).

### 2.5 Polygonization

* **Implementation:** `mapping/geological_pipeline/polygonization.py`
  * `generate_facies_polygon_layer` — `:333-516`: threshold classification (`np.int16` class grid, default thresholds at ⅓/⅔ span — recorded in `polygon_qc.thresholds_source = "data_derived_default"|"explicit"` `:374-413`), then per-class `_polygonize_raster_boundaries` `:121-268`: cell-boundary segment tracing → loop stitching → collinear simplification (`:73`) → signed-area exterior/hole split → **majority-vote hole nesting** (`:234-259`, unmatched holes promoted to islands + counted) → `repair_invalid_geometry`.
  * Extras: `min_area` filter with visible drop count (`_filter_small_polygons` `:315`), shapely clip to `clip_ring` (`:281`), per-feature `area` (CRS axis units) + `area_unit` + geographic `area_approx_m2` labelling (`:458-483`), categorized renderer style dict (`:498-505`).
  * **Output = `PolygonMapLayer`** (GeoJSON Polygon/MultiPolygon features with `facies_id/facies_name/facies/color/area/area_percent/mean_value`, `categories`, `metadata.polygon_qc`).

### 2.6 Uncertainty representation

* Kriging: `FactorGridResult.variance_grid` (float32) + `variance_min/max` in `algorithm_parameters` and `task.quality_metrics` (`factor_interpolation.py:280-282, 326-328`).
* Fusion: `FusionResult.confidence` / `.variance` as `FactorGridResult` (see §5).
* **No visualization exists**: grep over `paleo_workbench/viz`, `ui`, `mapping` finds **zero consumers** of `variance_grid`/confidence outside the interpolator/fusion modules. Uncertainty surfaces only surface as: publish-gate warning "no uncertainty surface" (`map_product.py:698-699`) and QA `low_confidence` rule on fusion confidence stats (`map_qa_rules.py:303-328`). There is no FACTOR_UNCERTAINTY layer construction anywhere yet (the role exists — see §4).

---

## 3. Constraints

### 3.1 Three vocabularies (deliberate, but easy to confuse)

| Vocabulary | Where | Values |
|---|---|---|
| (a) Engine-role on lines | `project/models.py:293` `ConstraintLine.role` | `break` (fault/barrier), `direction` (anisotropy axis: `azimuth_deg/semi_major/semi_minor`), `boundary` (study-area ring), `other` |
| (b) Interpolation-capability kinds | `workflow/constraint_capabilities.py:41-47` `ConstraintKind` | `boundary_mask, barrier, direction, anisotropy, trend` |
| (c) Geological semantic kinds (V5 §22) | `mapping_workspace/layer_roles.py:149-166` `ConstraintKind` | `source_direction(物源方向), provenance_line(物源线), distribution_line(展布线), paleo_shoreline(古岸线), facies_boundary(相带控制线), fault(断层), interpolation_boundary(插值限制边界), mask(掩膜), exclusion_area(排除区), trend_line(趋势线)` |

Mapping (c)→(a): `CONSTRAINT_INTERPOLATION_ROLE` — `layer_roles.py:219-230` (shoreline/facies_boundary/interp_boundary/mask/exclusion → `boundary`; fault → `break`; provenance/distribution/trend/source_direction → `direction`).
Mapping (c)→layer roles: `CONSTRAINT_KIND_ROLE` `:205-216` (each kind → `LayerRole`, mask+exclusion share `MASK_BOUNDARY`; polygon-affine kinds: mask, exclusion_area — `:200-203`).

### 3.2 Storage & digitizing

* Authoritative storage: `ProjectDocument.constraint_layers: list[ConstraintLayers]` (`project/models.py:602`); `ConstraintLayers(id,name,target_horizon,lines,linked_factor_task_ids,crs)` `:304-312`.
* **Stage-2 typed creation:** `ui/workstation/stage_actions.py:383-437` `StageActionDispatcher.create_constraint(kind)` — creates an editable `UserVectorLayer` (via edit controller, template = kind value) + registers role membership + **appends a `ConstraintLine` with `role=kind.interpolation_role` and `properties={"layer_id", "constraint_kind"}` but EMPTY `coordinates`** (`:421-436`). Geometry is digitized into the vector layer; note there is **no automated sync of edited vector geometry back into `ConstraintLine.coordinates`** — the engine-side line and the canvas layer can diverge until something re-harvests them.
* Legacy templates digitizing: `ui/workstation/composite_editing.py:170-208` (物源线/展布线/打断线/方向线 business fields; `UserVectorLayer` creation `:694`).
* Map-document harvest/export: `workflow/constraints.py` — `constraint_line_from_map_feature` `:135-167` (role-stamped `line_features`), `constraints_from_map_document` `:170-187`, reverse export `line_features_from_constraints` `:190-222`, upsert `:124`.

### 3.3 Consumption by interpolation

`workflow/constraints.py` adapters: `active_lines` `:33` (active + role + horizon filter), `break_polylines_for_idw` `:62`, `direction_line_params` `:76` (unset axes stay None → haiyou 18:1 default, #927), `boundary_rings_for_engine` `:234` (rings auto-closed, need ≥4 pts; consumer added in #928), `constraint_layers_for_project` `:110`.

Routing in `apply_interpolation_to_task` (`workflow/factor_interpolation.py`):
* breaks → `fault_polylines` for IDW/constrained-IDW (`:481`, `:287-290`);
* direction lines → anisotropy params for 方向趋势 and constrained-IDW corridors (`:482-484`; adapter `_build_directions` `constrained_idw_adapter.py:191-231`);
* boundary rings → constrained-IDW domain (user ring beats synthesized sample hull, `constrained_idw_adapter.py:561-574`; `_boundary_from_samples` `:234` fallback hull);
* per-sample `q`/`b_i` weights → TREND kind (constrained-IDW decluster / directional kernel).

### 3.4 Requested / applied / ignored / unsupported semantics (V6 §10)

* Capability matrix `_METHODS` — `workflow/constraint_capabilities.py:70-160`. Summary (method × kind):

| method | boundary_mask | barrier | direction | anisotropy | trend |
|---|---|---|---|---|---|
| idw | unsupported | **supported** | unsupported | unsupported | unsupported |
| constrained_idw | **supported** | **supported** | **supported** (corridor) | partial (ratio floored at 16) | **supported** (decluster; b_i not consumed) |
| kriging | unsupported | unsupported | unsupported | **supported** (anisotropic variogram, V6 §11) | unsupported |
| spline/linear/nearest/rbf | partial (convex hull clip) | unsupported | unsupported | unsupported | unsupported |
| directional | unsupported | unsupported | partial (multi-line → one global azimuth) | partial | **supported** (q/b_i kernel) |

* `evaluate_request` — `:253-294` produces `ConstraintApplication` (`:178-207`): `requested / applied / partial / ignored / unsupported / diagnostics`; `strict=True` raises `ConstraintViolationError` `:163` (harness scientific actions). `capability_matrix()` `:210` serializes for UI/docs.
* Requested-kind inference: `_requested_constraint_kinds` — `factor_interpolation.py:412-447` (breaks→BARRIER; directions→DIRECTION+ANISOTROPY; boundary rings→BOUNDARY_MASK; task azimuth→ANISOTROPY; sample q/b_i→TREND).
* The record travels twice: `grid_result.algorithm_parameters["constraint_diagnostics"]` (`:245-247`) AND `task.parameters["constraint_diagnostics"]` (with engine-reported ignorances merged, `:265-272`); kriging variogram choice provenance `:273-276`.

### 3.5 Versioning

* Constraint lines are **not catalog-versioned**. The Phase-3 evidence set references them as `constraints:current` — an honest, version-less key: freshness evaluation cannot assert STALE without a comparison baseline, so it stays UNKNOWN (`mapping_workspace/dependencies.py:322-324`). Constraint content fingerprints are planned (mentioned in `dependencies.py:22`) but not implemented.
* Versioned siblings that constraints interact with: `FaultInterpretationRef` (`project/models.py:227`, catalog-versioned fault interpretation) is a separate authority from `ConstraintLine(role="break")` — no bridge between them today.

---

## 4. Stages (Phase/Stage 1–3)

### 4.1 Framework

* `MappingStage` — `mapping_workspace/stages.py:22-27`: `FACIES_CALIBRATION(① 初始相图校正)`, `CONSTRAINT_FACTOR(② 约束与单因素)`, `INTEGRATED_COMPILATION(③ 综合编图)`; free bidirectional switching, no scientific recompute on switch (`:1-16`).
* `LayerRole` — `mapping_workspace/layer_roles.py:17-59` (see table below); `ROLE_EDITABLE` `:120-134`; `ROLE_RAW_PROTECTED` `:138-146` (initial facies source, all prediction/confidence roles, FACTOR_GRID, FACTOR_CLASSIFICATION are non-editable RAW).
* Union layer tree groups — `mapping_workspace/layer_groups.py:101-166`: `phase3.cartography / phase3.qc / phase3.integrated / phase3.geology / phase1.interpretation (visible all stages, locked P2/P3) / phase2.constraints (locked P3) / phase2.factors (root of `factor.<task_id>` groups, locked P3) / phase1.well_predictions / phase1.seismic_predictions / phase2.analysis / phase1.initial_facies / phase1.aux / base.reference / legacy.unclassified`.
* Factor sub-group child order — `FACTOR_CHILD_ORDER` `layer_groups.py:173-180`: input → grid → contour → classification → uncertainty → QC. `home_group_for_role` `:254`; migration classify `:323-353` (template keys `_TEMPLATE_CONSTRAINT_KINDS` `:36-54`).
* State: `MappingWorkspaceState` (`stage_state.py`) — `LayerMembershipRecord(layer_id, role, factor_task_id, constraint_kind, created_stage, source_version_id, created_at)` `:56`, `ArtifactMaturity` draft/reviewed/frozen/published `:29-44`, `compilation_input_set`.
* Controller: `MappingStageController` (`controller.py:47`) + `LayerGroupController` (`layer_group_controller.py:49`, incremental QGIS-tree reconcile `:333`, stage visibility `:452`).
* Stage profiles: `stage_profiles.py:78-187` — per-stage active editing roles, tool/dock recommendations, readiness check ids, evidence-locked groups.
* Readiness: `readiness.py` `evaluate_stage_readiness` `:356`; per-check implementations (e.g. `check_factors_complete` `:243`, `check_factor_staleness` `:265`, `check_evidence_available` `:277`).

### 4.2 What exists per stage (today) — `ui/workstation/stage_actions.py` (616 lines)

**Phase 1 — FACIES_CALIBRATION**

| Target item | Status | Where |
|---|---|---|
| initial-facies RAW layer | **exists** | `load_initial_facies` `stage_actions.py:126-160` — `PaleoMapDocument.facies_polygons` → polygon layer role `INITIAL_FACIES_SOURCE` (RAW, non-editable); requires a PaleoMapDocument that already has facies polygons (made on the mapping page) |
| editable derived draft | **exists** | `create_facies_draft` `:245-297` — RAW→DERIVED copy, role `INITIAL_FACIES_DRAFT`, pins `source_version_id`, maturity draft |
| well prediction overlay | **partial** | `add_well_prediction_overlay` `:162-243` — only prediction tasks with VECTOR_POLYGONS spatial results; curve-domain results deliberately stay out of map |
| seismic prediction overlay | **partial** | `add_seismic_prediction_overlay` `:184-243` — same polygon-only path |
| confidence overlay | **missing** | roles `WELL_FACIES_CONFIDENCE`/`SEISMIC_FACIES_CONFIDENCE` defined (`layer_roles.py:26,28`) and profile context action `toggle_prediction_confidence` declared (`stage_profiles.py:100`) but **no handler exists** (dispatch table `stage_actions.py:46-60` lacks it → “未知阶段动作”) |
| RAW lock | **exists** | `ROLE_RAW_PROTECTED` + flush-gate (`stage_actions.py:1404` comment; `stage_save` `:597-615` blocks RAW edits) |

**Phase 2 — CONSTRAINT_FACTOR**

| Target item | Status | Where |
|---|---|---|
| all constraints as real QGIS vector layers | **exists (V5 §22)** | `create_constraint` `:383-437`; template menu `ui/workstation/mapping_stage_panel.py:160`; layers land in `phase2.constraints` group |
| constraint → interpolation engine sync | **partial** | `ConstraintLine` appended with empty coordinates; geometry lives only in the vector layer (see §3.2) |
| per-factor layer group (input/grid/uncertainty/contour/polygon/QC) | **partial — 2 of 6 children** | `overlay_factor_results` `:329-381` creates only `FACTOR_INPUT` (WellTable points) and `FACTOR_CONTOUR` (marching squares from `peek_live_factor_grid`); **no FACTOR_GRID raster layer, no FACTOR_CLASSIFICATION polygons, no FACTOR_UNCERTAINTY, no FACTOR_QC**; skipped tasks reported honestly (no silent recompute) |
| factor runs | via navigation | `open_factor_workbench` `:326-334` just navigates to the existing preparation page; `factor_qc` / `compare_factor_versions` profile actions are declared but unimplemented |

**Phase 3 — INTEGRATED_COMPILATION**

| Target item | Status | Where |
|---|---|---|
| evidence version selection | **exists** | `select_evidence` `:439-487` — builds `compilation_input_set` entries `draft:<layer_id>` / `factor:<task_id>:<version>` / `constraints:current` |
| integrated interpretation layer + boundaries | **exists / partial** | `create_integrated_draft` `:489-518` clones Phase-1 draft geometry into role `INTEGRATED_FACIES` (Phase-1 evidence untouched); `INTEGRATED_BOUNDARY` role exists but no creation action |
| overlays | via group visibility | union tree shows `phase2.factors` / `phase1.interpretation` locked in P3 (`layer_groups.py:119-131`) |
| stale propagation | **exists** | `MappingDependencyService._evaluate_integrated` `dependencies.py:257-341` (draft/factor upstream propagation, factor-version pin check, honest UNKNOWN for `constraints:current`); headline via `StaleSummary` |
| QA | **exists (minimal)** | `run_qa` `:520-551` — topology validation of integrated layers + staleness entries → `QualityReport(rules=["topology","staleness"])`; extended rule set `map_qa_rules.py:37-48` exists but is **not invoked** from this action |
| MapProduct assembly | **exists but broken as wired** | `assemble_map_product` `:553-596` collects factor ids from evidence set and calls `workflow.map_product.assemble_map_product`, **but passes `payload_path=<project_root>/.artifacts` (a directory)** — `assemble_map_product` requires a staged payload *file* (`map_product.py:119-121`), so the action always fails into its except-branch (“MapProduct 组装失败”) |
| publish gate without modifying Phase-1 evidence | **exists** (gate itself) | `publish_map_product` — see §4.4; not directly exposed as a stage action (harness `map.publish` only) |

**Cross-cutting defects found**

* **Status-vocabulary bug:** `FactorMapTask.status` is set to `"complete"` (`factor_interpolation.py:299`; also `map_qa_rules.py:268` checks `"complete"`), but `stage_actions.py:331, :462` and `readiness.py:247, :282` filter `"completed"` — Phase-2 factor overlay, Phase-3 evidence listing, and the readiness checks never match any real task.
* Declared-but-unimplemented stage context actions: `toggle_prediction_confidence`, `factor_qc`, `compare_factor_versions`, `map_components` (`stage_profiles.py:100, 137-138, 165`).

### 4.3 Drafts, staleness, evidence version, QC

* Draft lifecycle: `ContourDraft.status` draft→editing→final (`models.py:343`); workspace `ArtifactMaturity` draft/reviewed/frozen/published (`stage_state.py:29`).
* Version snapshots of expert-approved maps: `VersionSnapshot`/`VersionSet` (`models.py:388-422`) — legacy finalize path parallel to MapProductRecord.
* Derived-data freshness (catalog-graph based): `workflow/freshness.py` — `FreshnessState` `:80`, `evaluate_run` `:379`, downstream impact `:795`; cached DependencyGraph `:39`.
* Catalog-side QC: `QualityReport` (`models.py:375-385`), `workflow/qc.py BASIC_QC_RULES` `:17-24` (document content), `map_qa_rules.EXTENDED_QC_RULES` `:37-48` (crs_undeclared, crs_mismatch, class_renderer_mismatch, out_of_bound_feature, well_table_empty, stale_inputs, broken_external_reference, low_confidence, export_fallback, composition_incomplete), `collect_extended_qc_issues` `:348`, `composition_qa_issues` `:369`.

### 4.4 MapProductRecord & publish gate (exact)

`MapProductRecord` — `project/models.py:512-539`:
`id, product_name, factor_task_ids[], interpretation_refs[], composition_ref, notes, output_version_id, run_id, scientific_fingerprint, created_at, status ("final"|"superseded"), frozen, superseded_by, cloned_from, manual_adjustments[]`.

Assembly `assemble_map_product` (`map_product.py:82-208`): refuses mock/mixed factor sources (`:104-108`), refuses tasks without persisted grid version (`:109-114`), refuses without catalog (`:117`) or staged payload file (`:119-121`); books run RUNNING → OUTPUT version → complete (#1219 ghost-run fix); embeds `factor_snapshot` (assembly-time per-factor truth) in run parameters `:139-153`; appends `MapProductRecord`.

Lifecycle: `clone_map_product` `:360`, `rerun_map_product` `:395` (supersedes), `compare_map_products` `:442` (run-snapshot vs live-fallback diff), `product_staleness` `:551-576` (fingerprint vs current inputs, manual adjustments included), `freeze_map_product` `:579`, `supersede_map_product` `:584`, `promote_map_product` `:604`.

Publish gate `publish_map_product` `:622-713`:
* **Fail-closed problems:** superseded (`:643`), stale inputs (`:645-647`), active `QualityReport.status == "error"` (`:650-659`), and — only when `accept_warnings=False` — every warning.
* **Warnings (recorded, published-with-honesty):** map CRS not verifiable from composition ref (`:661-677`, documented limitation 13), no factor tasks (`:681`), per-factor unit undeclared (`:682-689`), constraint diagnostics with `unsupported_constraints` (`:690-697`), no uncertainty surface (`:698-699`).
* Returns `{ok, problems, warnings, staleness, export_path}`; raises `ValueError` on problems.

### 4.5 Gap summary vs stated target

1. **Stage 1:** confidence/probability prediction overlays missing (roles + profile action exist, no implementation); well/seismic overlays are polygon-only.
2. **Stage 2:** factor groups only ever contain input points + contours. No grid raster layer (scalar or QGIS raster), no classification polygons, no uncertainty layer, no QC layer per factor. Constraints are canvas layers but their geometry never flows back into `ConstraintLine.coordinates` consumed by interpolation.
3. **Stage 3:** integrated-boundary creation missing; `assemble_map_product` stage action passes a directory as payload (always fails); extended QA rule set not wired into the stage QA action; publish gate reachable only via harness.
4. **Status-string mismatch** (`"complete"` vs `"completed"`) silently disables factor evidence flows in stage actions + readiness (§4.2 defects).
5. Scalar factor grids never reach QGIS as scalar rasters (see §2.2) — the "per-factor layer group with a grid layer" target cannot be met on QGIS-native rendering today without the RGBA mirror being replaced/augmented by a single-band float GeoTIFF + pseudocolor renderer.

---

## 5. Fusion V2 (`workflow/factor_fusion.py`)

| Piece | Location | Detail |
|---|---|---|
| `Normalization` | `:68-103` | `minmax`/`ramp` membership → [0,1], clamped; `high > low` enforced |
| `FactorEvidence` | `:106-128` | `factor_name, grid: FactorGridResult, weight>0, normalization`; serialises without the grid |
| `FusionRule` | `:131-177` | ordered `(factor, op, threshold)` conditions on **raw** unit-bearing values; ops `>=,<=,>,<,==` (`:59-65`) |
| `FusionModel` | `:180-263` | `kind ∈ {weighted_evidence, rule_based}`, evidences, rules, `default_class`, `class_thresholds` (len = names−1), `class_names`; `fingerprint()` `:259`; rebuild-from-provenance `from_dict(..., grids=)` `:221` |
| `fuse` | `:337-341` | dispatch |
| `_fuse_weighted` | `:344-444` | membership stack → weight-renormalised mean (`nan_policy="renormalize"`, no-evidence cells stay NaN `:386`); **confidence = coverage × agreement** (`:388-396`); **variance propagation** Σ(w/W)²·var on common support (`:399-411`); threshold classification, highest-match-wins (`:415-420`); QC incl. class_counts + `unit_warnings` |
| `_fuse_rule_based` | `:447-505` | first-match-wins class grid (NaN nodata / 0 default / 1..n rule idx), rule hit counts; confidence 1.0 matched, 0.0 default |
| Unit checks | `:350-372` + `factor_units.validate_factor_unit_against_values` `:148-183` | percent-vs-fraction magnitude cross-checks + percent-grid-with-0..1-bounds warning; `_aligned_or_raise` `:287-307` also **refuses to fuse same-shape grids in different CRSs** (P1-11) |
| `sensitivity_report` | `:508-559` | deterministic leave-one-factor-out: fraction of classified cells changing class per factor |
| `register_output` | `:574-637` | writes likelihood **and** best-effort confidence `.factor_grid.npz` artifacts via `catalog.grid_artifact.write_grid_artifact`, registers DERIVED versions + DataRun (parents = evidence source versions), **persists sensitivity into provenance** (`:594-599`, P1-11) |
| `FusionResult` | `:266-284` | `model, model_dict, likelihood, confidence, variance(=None for rule_based), class_names, qc` |

**Wiring status: `factor_fusion` is referenced only by its own module and `tests/test_factor_fusion*.py`.** No service, harness action, UI page, or stage action constructs a `FusionModel` or calls `fuse`/`register_output`. Fusion V2 is a complete, tested library with **zero production entry points** — Stage-3 "integrated interpretation" is currently manual digitizing only.

---

## 6. Harness Actions (factor/map/scientific)

Registry: `harness/actions/scientific.py`, `harness/actions/mapping.py` (specs in `harness/spec.py:ActionSpec`).

| action_id | Location | Risk / category | Side effects | Output schema (essentials) |
|---|---|---|---|---|
| `factor.evaluate_methods` | `scientific.py:60-91, 209-264` | COMPUTE / background.compute | none (read + CV compute) | `factor, scheme, k, methods[], recommended_method, fold_engine, error, detail` — honest demotion: idw-proxy fold engine cannot discriminate methods (`:251-263`) |
| `map.describe_product` | `scientific.py:94-108, 267-277` | READ | none | `product` = full `describe_map_product` payload (wells, factor snapshot, interpretations, run, output, staleness) |
| `map.publish` | `scientific.py:111-134, 280-298` | WRITE / background.io | publish gate only; refuses or records; file export is caller's step | `published, ok, problems[], warnings[], error, detail` |
| `map.create_factor_map` | `mapping.py:22-50, 324-462` | WRITE / background.compute | publishes in-session MapDocument; writes `intermediate/<doc>.npz`; catalog DataRun + INTERMEDIATE version (`factor_map.interpolate`); ScientificValidator grid gate before commit (`:347-355`) | `document_id, task_id, name, version_id, run_id` (+layers/extent/values/verification) |
| `map.create_well_location_map` | `mapping.py:54-71, 465-505` | COMPUTE | in-session document | `document_id, well_count, extent` |
| `map.add_layer` | `mapping.py:74-93, 508-531` | WRITE | document layer list (annotation/polygon only) | `added, document_id, layer_count` |
| `map.set_style` | `mapping.py:97-117, 534-556` | WRITE | style + style-revision bump | `layer, style` |
| `map.apply_template` | `mapping.py:120-137, 559-610` | WRITE | composer composition in-session | `document_id, template, components` |
| `map.add_component` | `mapping.py:140-160, 613-674` | WRITE | composer composition | `added, document_id, components` |
| `map.validate` | `mapping.py:163-177, 677-685` | READ | none | `verification/report/passed` (PASS/WARNING/FAIL) |
| `map.export` | `mapping.py:180-204, 727-765` | WRITE / export | workspace-contained file (overwrite refused) + catalog OUTPUT version via `export.map_product` provider | `exported, artifacts[], provenance, metrics` |
| `map.describe` | `mapping.py:208-219, 767-776` | READ | none | `document_id, title, crs, extent, layers, layer_count` |
| `map.qc` | `mapping.py:221-238, 779-794` | READ | none | `verdict, passed, reasons, document_id` |
| `map.contour` | `mapping.py:240-263, 797-829` | WRITE / background.compute | upserts `ContourDraft` into project (engine isolines preferred) | `draft_id, name, levels[], segment_count, linked_task_id` |
| `layer.describe` | `mapping.py:264-280, 832-853` | READ | none | `name, layer_type, visible, feature_count, style` |
| (supporting) `well.describe_units`, `seismic.describe_calibration` | `scientific.py:22-57` | READ | none | depth-unit truth / time-depth calibration status (unknown-never-guessed policy) |

Related but out of primary scope: `geology.*` (horizon/fault interpretation), `workflow.*`/`recipe.*` (generic run engine), `workspace.get_lineage/get_versions` (catalog lineage queries).

---

## 7. Consolidated Findings (for the v7 refactor)

1. **RGBA mirror is the only QGIS raster path.** `ScalarRasterMirrorCache` (`mapping/scalar_raster_mirror.py:18`) → 4-band Byte RGBA GeoTIFF in `/vsimem`, opened by the C++ bridge as `QgsRasterLayer` (`qgis_render_bridge.cpp:383`) with the **default** renderer. No `QgsRasterLayer`/pseudocolor usage anywhere in the Python package; scalar values never reach QGIS. Any "render scalar grids in QGIS with real classification/stretch" goal requires a new single-band float mirror (the `.factor_grid.npz` artifact already holds the scalar data).
2. **Two contour implementations and two rasterisation stacks** coexist: `geological_pipeline/contouring.py` (pure-Python marching squares → `ContourMapLayer`) vs `workflow/contour_draft.py` (geoviz engine isolines + #928 stored refined contours → `ContourDraft`); `viz/native_factor_map.py` C++ ScalarGridLayer vs `mapping/layers.GridMapLayer.rasterize_rgba`. Layer-construction authority is nominally `GeologicalMappingPipeline`, but the unified canvas bypasses it.
3. **Uncertainty is computed but never displayed** (`variance_grid`, fusion `confidence`/`variance`); it only appears as publish-gate warnings and the `low_confidence` QA rule.
4. **Fusion V2 is dead code in production** (tests only) — Stage-3 has no computational fusion path.
5. **Constraint plumbing is split**: geological `ConstraintKind` (V5 §22) → `ConstraintLine.role` mapping exists, but digitized vector geometry is not synced back to `ConstraintLine.coordinates`, and constraint content is unversioned (`constraints:current`).
6. **Stage action defects**: `"completed"` vs `"complete"` filter mismatch (stage_actions/readiness); `assemble_map_product` stage action passes a directory as the payload file; four declared profile context actions unimplemented; factor overlay covers only 2 of the 6 intended factor-group child layer types.
7. **FactorMapSpec/FactorMapOutput/MapProductRecord** are complete, fingerprinted, fail-closed contracts — the refactoring can build the QGIS GeoLayer work on top of them without redesigning the scientific core.
