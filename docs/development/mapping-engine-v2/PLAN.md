# Mapping Engine 2.0 & Geological Mapping Pipeline — Implementation Plan

## Phase 0 — Baseline & Environment Verification
- [x] Create worktree `../paleo-mapping-engine-v2` tracking `origin/main` on branch `feat/mapping-engine-v2-geological-pipeline`.
- [x] Verify Python 3.12 environment, submodules, dependencies, and test infrastructure.
- [x] Complete codebase audit and generate `codebase-analysis.md`.
- [x] Initialize tracking docs: `PLAN.md`, `PROGRESS.md`, `DECISIONS.md`, `TEST_RESULTS.md`.

## Phase 1 — Mapping Abstractions
- [ ] Define core layer data models in `paleo_workbench/mapping/layers/` (or structured submodule):
  - `MapLayer` base protocol/abstract class.
  - `VectorLayer`, `GridLayer` (wrapping `FactorGridResult` / scalar grid with explicit CRS, extent, resolution, nodata), `ContourLayer`, `WellPointLayer`, `AnnotationLayer`.
- [ ] Maintain backward compatibility with existing `VectorLayer` and `MapLayerSnapshot`.
- [ ] Ensure layer data structures are UI-independent and thread-safe.

## Phase 2 — Renderer Registry & Layer Renderers
- [ ] Define `LayerRenderer` protocol/ABC (`render`, `legend_items`, `render_svg`, etc.).
- [ ] Implement concrete renderers:
  - `SingleSymbolRenderer`
  - `CategorizedRenderer`
  - `GraduatedRenderer`
  - `GridRenderer` (colormap, range, opacity, nodata handling)
  - `ContourRenderer` (line weight, color, isoline labels)
  - `WellSymbolRenderer` (geological well point symbols, well names, attribute labels)
- [ ] Implement `RendererRegistry` with `register()`, `unregister()`, `resolve()`, `create()`.

## Phase 3 — Style / Symbol System Refinement
- [ ] Enhance `paleo_workbench/mapping/map_styles.py`:
  - Unified `Symbol` models (`FillSymbol`, `LineSymbol`, `MarkerSymbol`, `TextSymbol`).
  - Unified `ColorRamp` / Color palettes (geological standards: porosity, permeability, thickness, TOC).
  - Clean legend style model (`LegendItem`, `LegendStyle`).
  - Compatibility adapter for existing `VectorStyle` and `qgis_style.py`.

## Phase 4 — Backend Abstraction & Isolation
- [ ] Formalize `RenderBackend` protocol/ABC.
- [ ] Keep `FallbackMapRenderBackend` as internal high-performance software renderer with thread safety.
- [ ] Keep `QgisMapRenderBackend` as optional native acceleration backend.
- [ ] Ensure renderer dispatch leverages `RendererRegistry` instead of hardcoded `if/elif` branches.

## Phase 5 — Canvas / Composer Unification
- [ ] Create shared `RenderPlan` model extracted from `MapDocument` / `MapRenderSnapshot`.
- [ ] Refactor `MapComposerRenderer` (`composer/renderer.py`) to use `LayerRenderer` & `RenderBackend` abstractions for `MAIN_MAP` rendering.
- [ ] Ensure Canvas (screen RGBA) and Composer (SVG vector output) share identical styling, symbology, and layer ordering.

## Phase 6 — Geological Factor Data Model
- [ ] Define `GeologicalFactor` and `GeologicalFactorPoint` models in `paleo_workbench/workflow/factors.py` / `paleo_workbench/mapping/geological_pipeline/`:
  - `name`, `value`, `unit`, `well_id`, `x`, `y`, `crs`, `formation`, `interval`, `quality`, `metadata`.
- [ ] Implement factor extraction from `WellTable`, `ProjectDocument`, and well logs.
- [ ] Support standard properties: 砂岩厚度, 地层厚度, 孔隙度, 渗透率, TOC, 古水深.

## Phase 7 — Interpolation Engine Integration & Grid Model
- [ ] Integrate interpolation engines under a unified `Interpolator` interface:
  - `KrigingInterpolator` (variogram, nugget, sill, range, error handling, variance grid).
  - `IDWInterpolator` (power, search radius, anisotropy).
- [ ] Ensure numerical safety (handling NaN, inf, collocated points, singular matrices, minimum point counts).
- [ ] Produce structured `InterpolationResult` / `FactorGridResult` with explicit CRS, extent, resolution, and statistics.

## Phase 8 — Contour & Polygon Layers Generation
- [ ] Integrate Marching Squares contour generation into standard `ContourLayer`:
  - Auto/custom intervals, smoothing, labeling values.
- [ ] Integrate facies/zone polygonization into standard `PolygonLayer` with topology repair and hole preservation.

## Phase 9 — Standard Geological Factor Map Template
- [ ] Define standard `GeologicalFactorMapTemplate`:
  - Main map element containing GridLayer + ContourLayer + WellPointLayer + Boundary.
  - Cartographic elements: Title, Legend, Color Bar, Scale Bar, North Arrow, Attribution.
- [ ] Build factory `create_geological_factor_map_document(...)` returning a fully structured `MapDocument` / `MapCompositionDocument`.

## Phase 10 — UI Integration & Async Execution
- [ ] Add "Create Geological Factor Map" action/dialog in mapping/workflow UI.
- [ ] Flow: Select Data Source / Wells → Select Formation/Interval → Select Factor → Configure Interpolation & Grid → Generate GIS Layers & Map.
- [ ] Use background worker (`QThread` / `Worker`) to keep UI responsive.

## Phase 11 — Performance Profiling & Optimization
- [ ] Verify memory efficiency, avoid unnecessary ndarray copies.
- [ ] Ensure vector simplification and caching operate efficiently on large point/grid sets.

## Phase 12 — Automated Test Suite
- [ ] Unit tests for `Layer`, `RendererRegistry`, `Style`, `MapDocument`, `GridLayer`, `ContourLayer`, `KrigingInterpolator`.
- [ ] Integration test: Well points → Kriging → Grid → Contour → Layers → MapDocument → Composer SVG.
- [ ] Snapshot / regression tests for SVG composition and layer ordering.

## Phase 13 — Final Review & PR
- [ ] Run full project test suite.
- [ ] Perform codebase design, bug diagnostics, and clean git history check.
- [ ] Push branch and prepare Pull Request.
