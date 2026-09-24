# 05 — science kernel inventory (migration candidates)

All kernels Qt-free (STL + pwb::domain::Json). No QgsRasterLayer in/out anywhere today; raster = in-memory float grid (NaN=nodata), vector = GeoJSON Json.

## Priority list → paleo algorithm ids

| Kernel | Entry (file:line) | paleo id (new) | Notes |
|---|---|---|---|
| IDW/kriging interpolation | `mapping::interpolate_factor` interpolator.hpp:133 | `paleo:interpolation_idw`, `paleo:interpolation_kriging` | SamplePoint vec → FactorGrid + variance |
| Constrained IDW (Haiyou) | `generate_constrained_idw` constrained_idw.hpp:175 | `paleo:interpolation_constrained` | wells/boundaries/barriers/directions; contours included |
| Spline/RBF/nearest/linear | `interpolate_scipy_grid` scipy_grid.hpp | `paleo:interpolation_scipy` | method param |
| Directional trend | `directional_trend_grid` directional_trend.hpp | `paleo:interpolation_directional` | |
| Contours | `marching_squares_contours` contouring.hpp:57 (+ nice/quantile levels) | `paleo:grid_contours` | Grid → polylines |
| Contour layer product | `generate_contour_layer_product` layer_products.hpp | `paleo:contour_layer_product` | GeoJSON features |
| Clip/mask/repair rings | ring_ops.hpp (CONV-04; no production callers) | `paleo:clip_to_ring`, `paleo:repair_ring` | activate sunk kernel |
| Grid statistics | `grid_statistics` interpolator.hpp:94 | `paleo:grid_statistics` | |
| Extract factors | `mapping::extract_factors` | `paleo:extract_factors` | well table → per-factor points |
| Factor fusion | `factor_fusion::fuse` fusion.hpp:682 | `paleo:factor_fusion` | |
| Facies class grid | `nearest_neighbor_class_grid` class_grid.hpp:52 | `paleo:facies_class_grid` | |
| Representative facies | `representative_facies` representative_facies.hpp | `paleo:representative_facies` | |
| Seismic attributes ×10 + c3 | IAlgorithm factories attributes.hpp:75, coherence_c3.cpp:283 | `paleo:seismic_<name>` ×11 | volume path in → volume out |
| Well curve ops | `curve_operations` well_science/curve_ops.hpp | `paleo:well_curve_operation` | |
| Well DTW match | `match_curves` well_science/dtw.hpp | `paleo:well_log_match` | |
| Scalar classification | cartography classify_breaks scalar_style.hpp | `paleo:scalar_classification` | equal/quantile/natural breaks |
| Project source validation | `find_missing_sources` catalog/sources.hpp:45 | `paleo:project_validate_sources` | |
| Relink | `relink_external_source` catalog/sources.hpp:56 | — | not implemented as a paleo algorithm (no `paleo:project_relink`); relink stays on the catalog service path |
| Batch conversion | `BatchConversionService::convert` interchange/batch.hpp:83 | `paleo:batch_convert` | cancel+progress vocab exists |
| Well head scatter | `build_well_head_scatter` ui_pages_preview | `paleo:well_head_scatter` | |

## Cross-cutting facts

- CRS handling today: string + token heuristic (`crs_policy.cpp:98`), unknown → nullopt. Provider side uses `QgsCoordinateReferenceSystem` where a CRS parameter exists.
- No GeoTIFF writer in-tree → raster outputs published via `QgsRasterFileWriter`/`QgsProcessingParameterRasterDestination`; vector outputs via feature sinks (GeoJSON → QgsFeature).
- Kernels have no progress callbacks → wrappers use stage-based `QgsProcessingMultiStepFeedback` (mirrors science_service stage_guard pattern).
