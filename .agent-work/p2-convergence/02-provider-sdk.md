# P2-B — Capability Provider SDK

## Design (ADR 0055 track P.REG, delivered)

```
ProviderDescriptor (frozen data: id/family/version, JSON-schema parameters,
                   typed input/output names, ResourceProfile, cancel/resume,
                   deterministic, threading_model)
        │ validate_descriptor (structural, testable — never inspect-signature guessing)
        ▼
ProviderRegistry (explicit register + duplicate/version detection + quarantine;
                  opt-in entry-point discovery PALEO_PROVIDER_ENTRY_POINTS=1;
                  no directory scanning, ever)
        │ get_provider_registry() → built-ins auto-registered, individually guarded
        ▼
execute_provider (resolve → schema-validate params → typed-input check →
                  governor admission lease → run with ProviderContext
                  (catalog/cancel/progress/work_dir) → DataRun provenance
                  (begin/complete/fail) → ProviderResult)
```

- **Errors**: `ProviderError` hierarchy (Invalid/Duplicate/Unknown/RejectedInput/InvalidParameters/Execution) — contract errors pass through the executor unwrapped; foreign exceptions are wrapped for isolation.
- **Typed refs** (`providers/refs.py`): WellRef, SeismicVolumeRef, MapDocumentRef, FactorDatasetRef, FactorGridRef, PathRef + catalog `DataVersionRef` (reused from `catalog.types` — provenance stays on the existing authority) + in-process domain objects (`GeologicalFactorDataset`, `MapDocument`) in the declared vocabulary. No anonymous dicts.
- **Provenance**: outputs enter the catalog via CatalogPort inside provider execute (`register_derived`/`register_output`); the executor wraps every catalog-bound execution in a DataRun with generator_version = provider version. Nothing lands in /tmp-only.
- **Admission**: ResourceProfile → governor lease per execution (pressure shedding surfaces as `ResourceExhausted`).

## Built-in providers (all wrap existing production seams)

| provider_id | family | wraps |
|---|---|---|
| interpolation.kriging | INTERPOLATION | `KrigingInterpolator` via `interpolate_factor` |
| interpolation.idw | INTERPOLATION | `IDWInterpolator` via `interpolate_factor` |
| seismic.attribute.c3 (+ per KERNELS entry) | SEISMIC_ATTRIBUTE | `VolumeAttributeJob`/`roi_attribute` (banded resumable zarr; ROI in-memory) |
| inference.tiled_onnx | INFERENCE | delegates to `prediction.providers.TiledOnnxProvider` (model registry/promote gates unchanged) |
| export.map_product | EXPORTER | `render_and_save_map_export` (canvas/export parity interpreter) |
| viz.map_render.qgis / .fallback | VISUALIZATION | `create_map_render_backend` probe (honest availability flags) |

Families DATA_FORMAT/PREVIEW/MAP_COMPONENT exist in the vocabulary (seams known:
FormatSpec/PreviewRegistry/composer) but ship no built-ins — no placeholder providers.

## Security boundaries honored

- No arbitrary Python/SQL/shell; providers receive refs, not raw paths from agents.
- Filesystem access only through PathRef/workspace; outputs go through the catalog.
- Bad provider (invalid descriptor, raising factory, duplicate id) → quarantined with reason; registry and app keep booting.

## Tests (`tests/test_provider_sdk.py`, 31 tests, ALL PASS)

descriptor validation matrix · duplicate/version-conflict quarantine · naked-object rejection ·
family/lookup/sort · built-ins registered · entry-points disabled by default ·
schema subset semantics (type/required/enum/min-max/minItems/additionalProperties/bool-as-number) ·
happy path with provenance begin/complete · invalid parameters · undeclared input type ·
exception wrapping + run failure marking · governor admission + lease release ·
CRITICAL pressure shedding · kriging real-engine execution + diagnostics (finite_ratio, algorithm_id) ·
empty-dataset rejection · determinism (bit-equal reruns) · bad-volume rejection ·
backend probe honesty.
