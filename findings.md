# Findings — Scientific Interpretation & Algorithm V6

## Environment
- Repo root main checkout: C:\Users\wangj.KEVIN\projects\paleo-workbench (branch main @ 295fabc3)
- Worktree: .worktrees/scientific-interpretation-v6, branch feat/scientific-interpretation-v6
- Submodules pinned: geo-viz-engine 5e03beba, well-log-engine f845e7ab, gdal/proj NOT initialized (huge; vendored build only)
- pyproject: requires-python >=3.12,<3.13; deps pyside6/pydantic/numpy/pandas/lasio/rasterio/shapely/zarr
- geo-viz-engine subpackages installed editable (geoviz_common, geoviz_well_log, ..., geoviz_seismic, geoviz_paleo_map)
- GDAL NOT pip dep — vendored native build (ADR 0060); tests needing osgeo may skip if absent

## Architecture map (from CONTEXT.md/PROJECT.md)
- paleo_workbench/catalog = DataCatalogService (ADR 0056): DataAsset/DataVersion/DataRun/Tag; RAW immutable; catalog.json canonical + sqlite index
- paleo_workbench/harness = Harness 2.0 (ADR 0066): ActionSpec/ActionRegistry/HarnessExecutor
- paleo_workbench/providers = Provider SDK (ADR 0065)
- paleo_workbench/runtime/resource_governor.py = ADR 0064 admission authority
- paleo_workbench/mapping/geological_pipeline = factor extraction + kriging/IDW + marching squares + polygonization
- paleo_workbench/viz = SelectionContext, CoordinateTransformHub (TimeDepthCalibration fail-closed), picking_controller, correlation engines
- paleo_workbench/workflow = curve_interpretation (DERIVED + provenance), map_product (MapProductRecord)
- paleo_workbench/mapping_workspace = Mapping Workspace V5
- native/ = well_log_core, seismic_3d_core, grid_render_core, layer_model_core, qgis_render_bridge
- Well log units/null: CONTEXT has extensive well-log import semantics (ResForm v1, Inferred Null whitelist -999.25/-999/-9999/-99999, Source-Domain Null, LIS depth domain match, axis segmentation)
- ADRs 0056–0068 relevant; 33 ADRs total

## Audit findings (A–Q) — DONE, see docs/development/scientific-interpretation-v6/00-baseline.md

### P0 defect register (drive implementation order)
1. P0-1 Engine bridges NaN gaps (adapter filters nulls; payload has no nulls key; bridge sets nulls={})
2. P0-2 Display-name identity across correlation/tops/datum/multi-well
3. P0-3 Undeclared depth unit → "m" default chain-wide
4. P0-4 SEG-Y trace-scan ignores SourceGroupScalar (only loader.py:98 applies it, 1 call site)
5. P0-5 Fabricated 1.0m-bin survey from zero coords (survey.py:120)
6. P0-6 Constraints dropped for non-IDW backends, n_break_lines:0 reported
7. P0-7 create_factor_map dialog ignores ALL constraint layers
8. P0-8 Harness well.open/describe use decimated preview loader (no disclosure)
9. P0-9 One well's prediction attached to ALL correlation wells
10. P0-10 area/length in raw CRS units (square degrees under 4326)

### Key implementation anchors
- Unit authority: workflow/curve_operations.py unit_conversion whitelist is exemplary; build DepthUnit semantics around it
- Gap-aware engine: engine CAN split runs (curve_lod.cpp valid_sample); need nulls in payload schema → well-log-engine submodule change likely
- Constraint routing: workflow/factor_interpolation.py:409-417 computes for all, drops for non-IDW at geoviz factor/interpolation.py:317
- capability matrix must produce requested/applied/ignored/unsupported + diagnostics in FactorGridResult
- Kriging: engine kriging.py has variance + LOO already; needs anisotropy, fit diagnostics surfaced, nugget/range settable; unify numpy fallback fitter
- Harness: 15/17 scientific actions missing; ActionResult lacks provenance field
- Pre-existing main failure: test_integrity_guard tautological assertions (5 sites)
