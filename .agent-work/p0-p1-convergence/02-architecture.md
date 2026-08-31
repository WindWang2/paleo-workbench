# 02 — Architecture (as landed)

## What this convergence changed (and deliberately did not)

Every slice EXTENDED a stable seam; no second Catalog / LayerRegistry /
Scheduler / Selection bus / volume IO was created.

| Slice | Seam extended | New modules |
|---|---|---|
| S1 P0-C | `SelectionContext` (one bus, additive slots), `CoordinateTransformHub` (calibration), `ViewCoordinationController` (sinks + scenarios) | — |
| S2 P0-B | `CatalogIndex` (paged/aggregate queries), `AssetTableModel` (subclass), `DataAssetTable` (mode switch) | `ui/pages/paged_asset_model.py` |
| S3/S4 P0-D | `mapping/composer/models.py` (additive types + from_dict), `renderer.py` (component renderers) | `composer/components.py`, `composer/templates.py`, `composer/export.py`, `ui/pages/composition_panel.py` |
| S5 P1-B | `interpretation_draft` (set_picks), engine pick bridge, `KERNELS` registry | `viz/picking_controller.py` |
| S6 P1-C | `main()` boot (VRAM), `highlight_well`, `StratalWorker`, `stratal_adapter` | — |
| S7 P1-A | catalog `create_derived` (single write path) | `workflow/curve_interpretation.py` |
| S8 P1-D | `register_result_asset` (atomic OUTPUT), `FactorMapTask` honesty | `workflow/map_product.py`, `MapProductRecord` |
| S9 P0-A | `GEOLOGICAL_TYPE_MAP` | — |

## Key decisions (recorded rationale)

1. **Typed-id value classes NOT introduced.** String-prefixed ids are the
   established contract across catalog/project/engine; new abstractions
   would add seams without removing ambiguity (rule: fewer new abstractions).
2. **FFT attributes are trace-global and refuse cropped-time ROIs.** Numeric
   proof: a 20-sample window's envelope differs from the full-trace value by
   up to 0.67 on representative noise. Pretending halo parity would be a lie;
   refusing keeps the honest contract (band job = exact, ROI = full-time only).
3. **Paged-mode threshold 25k with honest degradation.** Integrity/entity
   smart views need fs probes / in-memory joins → materialized fallback
   rather than a half-correct SQL emulation.
4. **Curvature halo = ±(1 + win + 2).** Operator reach analysis: slope
   gradient ±1, slope smoothing ±win, double second derivative ±2. The
   band-parity test pins it.
5. **Fault interpretation enters through the map plane.** Break polylines
   are the scientific authority (project CRS); lifting copies them into the
   lifecycle rather than mutating constraints.
6. **MapProduct is an assembler, not AI.** It composes validated artifacts
   and refuses mock inputs; no auto-paleogeography claims.
7. **Composition serialization: live objects → reference stubs.** MapDocument
   /layers serialize as `__ref__` stubs; the host re-binds through declarative
   data bindings instead of silently losing or duplicating data.

## Submodules

Unchanged (main pins honored: geo-viz-engine 26777722, well-log-engine
fd3bc5a8). All engine capabilities consumed through existing public APIs.
