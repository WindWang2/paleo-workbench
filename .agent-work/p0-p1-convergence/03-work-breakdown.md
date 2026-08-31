# 03 — Work Breakdown (tickets)

## S1 — P0-C Geological Context completion
- [ ] SelectionState += active_horizon_id / active_fault_id / active_interpretation_id /
      spatial_cursor(x,y) / active_layer_id / map_extent; backward-compatible partial update
- [ ] CoordinateTransformHub += TimeDepthCalibration (piecewise-linear, monotone check,
      explicit provenance); seismic_to_well / well MD→TWT go through calibration and
      FAIL CLOSED (None + reason) when absent — removes the silent 2000 m/s assumption
- [ ] Controller: horizon selection routing (scenario D) across seismic/map/3D/inspector
- [ ] Seismic cursor → map cursor marker + 3D slice focus (scenario B)
- [ ] Map well click → seismic locates well via hub (scenario A completion)
- [ ] Well depth cursor → seismic time cursor ONLY under valid calibration (scenario C),
      honest refusal otherwise
- [ ] Tests: all four scenarios incl. refusal path, echo, cross-project reset

## S2 — P0-B Explorer virtualization
- [ ] Paged SQL-backed row provider (CatalogIndex.search_assets + LIMIT/OFFSET + count)
- [ ] AssetTableModel canFetchMore/fetchMore; page size; stable selection
- [ ] update_state stops materializing enriched views for all rows on GUI thread
- [ ] Benchmark: 100k open/query/search/page-fetch budgets recorded in 05

## S3 — P0-D Composition core
- [ ] Component contract: create/delete/move/scale/configure/serialize/copy/z-order
- [ ] New elements: TEXT, IMAGE, INSET_MAP, STAT_CHART, METADATA, COLORBAR (first-class)
- [ ] GRID + ANNOTATION leave placeholder-rect status (real rendering)
- [ ] MapCompositionDocument from_dict/to_dict roundtrip (versioned schema)
- [ ] CompositionEditSession: undo/redo command stack for composition edits
- [ ] CompositionTemplate: layout + component defs + style bindings + data bindings
- [ ] Template library: 9 categories (single-factor/contour/heatmap/well-location/
      seismic-interpretation/isopach/lithofacies/paleogeographic/comprehensive)
- [ ] Render paths honor RenderContext units + DPI contract

## S4 — P0-D Composition UI
- [ ] Composition editor panel (element tree, properties, add/delete/move/scale)
- [ ] Undo/redo actions; template apply; save/load into project
- [ ] Export composition page PNG/SVG/PDF at physical size + DPI
- [ ] UI state: empty/loading/error/disable states

## S5 — P1-B Seismic interpretation closure
- [ ] Draft.set_picks (write z at grid nodes w/ undoable patch; auto-seed from volume seed)
- [ ] Picking controller: engine horizon_picked → draft → overlay → save version →
      project ref → reopen; staleness surfacing
- [ ] Fault interpretation UI on map page (fault_lifecycle wiring)
- [ ] Attribute kernels: wire engine envelope/rms/sweetness/inst-phase/inst-freq/
      rel-impedance/dip/azimuth/curvature with halos; panel honest labels
- [ ] ROI/full parity + seam tests for every new kernel

## S6 — P1-C Unified scene completion
- [ ] apply_vram_budget at app boot (ResourceBudget defaults)
- [ ] highlight_well geometry highlight in 3D
- [ ] Versioned horizon artifacts loadable into joint 3D scene (not just .dat)
- [ ] Scene tree entries with stable DomainEntity ids; selection → context slots

## S7 — P1-A Derived-curve loop
- [ ] WellCurveInterpretationService: explicit ops (depth shift, despike, splice,
      baseline) on cataloged curve datasets → create_derived version with
      operation/parameters/input+output version ids; RAW untouched
- [ ] UI hook (data page well context menu); provenance visible in inspector
- [ ] Tests: RAW immutability, lineage chain, idempotent re-run produces new version

## S8 — P1-D MapProduct
- [ ] MapProduct domain: multiple factor tasks + interpretation refs + adjustments +
      composition reference → OUTPUT version with full lineage
- [ ] Production assembler (fail-closed like compile_map_production; no demo laundering)
- [ ] GeologicalMappingService: fill source_refs/run_ref; fix source_kind honesty
- [ ] Factor maps bind into composition templates (colorbar/legend binding)

## S9 — P0-A fault binding + docs
- [ ] Fault resources auto-bound as DomainEntities (GEOLOGICAL_TYPE_MAP)
- [ ] CONTEXT.md vocabulary updates for everything landed

## S10 — Verification
- [ ] Benchmarks (02/05 budgets), regression suites, /code-review, fixes to BLOCKER/HIGH=0
- [ ] 07-final-verification.md; PR
