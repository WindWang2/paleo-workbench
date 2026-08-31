# 01 — Domain Map & Dependency Graph

## Authoritative owners (never duplicated)

| Concept | Owner | Notes |
|---|---|---|
| Data lifecycle/version/provenance | `catalog/service.py` DataCatalogService | ADR 0056; only write path |
| Canonical metadata | `catalog.json` + rebuildable `catalog.sqlite` | ADR 0056 split |
| WorkArea domain entities | `project/domain.py` | reference catalog ids only |
| Project persistence | `project/manager.py` | atomic, stale-write guard |
| Cross-view state | `viz/selection_context.py` SelectionContext | ONE bus; extended in S1, never a second |
| Map↔well↔seismic transforms | `viz/coordinate_hub.py` | calibration-gated in S1 |
| Map document/layers/styles | `mapping/layers.py` + renderers | data/style separation |
| Composition model | `mapping/composer/models.py` | extended in S3 |
| DPI/unit contract | `renderers.py` RenderContext | #1103 named fold |
| Seismic out-of-core IO | engine `geoviz_seismic` (chunked/zarr/LOD) + host lifecycle | never re-implemented |
| Horizon interpretation lifecycle | `viz/interpretation_lifecycle.py` | UI wiring added in S5 |
| Well correlation lifecycle | `workflow/correlation_lifecycle.py` | complete |
| Factor interpolation + result | `workflow/factor_interpolation.py` FactorGridResult | provenance contract |
| Compile production map | `pipeline/compile_map_production.py` | fail-closed, anti-laundering |
| Task scheduling | `runtime/task_scheduler.py` | single scheduler |
| VRAM budget | `runtime/resource_budget.py` + engine VRAM ledger | wired in S6 |

## Slice dependency graph

```
S1 P0-C context slots + scenarios ──────┬──> S5 P1-B seismic interpretation UI
   (horizon/fault/interp slots,          └──> S6 P1-C scene identity/highlight
    calibration-gated depth↔time)
S2 P0-B table virtualization (independent)
S3 P0-D composition core ───> S4 P0-D composition UI ───> S8 P1-D MapProduct
S7 P1-A derived-curve loop (independent of S3/S4)
S9 P0-A fault binding (after S5 defines how faults surface)
S10 benchmarks/review  (after all)
```

Order of execution: S1 → S2 → S3 → S4 → S5 → S6 → S7 → S8 → S9 → S10.
Each slice = one or more commits, tests-first at the stable seams.
