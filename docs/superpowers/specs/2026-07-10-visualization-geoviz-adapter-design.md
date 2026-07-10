# Visualization ↔ geo-viz Adapter Design

> **Date:** 2026-07-10  
> **Status:** Approved for planning  
> **Page:** 可视化 (`VisualizationPage`, AppShell index 5)  
> **Related:**  
> - `docs/superpowers/specs/2026-07-05-visualizationpage-design.md` (MVP composite page)  
> - Data page preview pipeline (`PreviewProvider` / `PreviewRequestController`)  
> - Mapping preview helpers (`preview_payload_from_*`)  
> - geo-viz-engine: `geoviz_well_log`, `geoviz_seismic`, `geoviz_paleo_map`

## Goal

Align the workbench **visualization page** with **geo-viz-engine** through a shared, UI-agnostic adapter layer, and connect **partial visualization** to the **data page** via jump-to-visualization (not in-reader full canvases).

| Dimension | Decision |
|-----------|----------|
| Architecture | Shared `VizAdapter` (C) — both pages light-wire to the same resolve path |
| Asset types (V1) | Well log (LAS), seismic (SEGY), paleogeographic map |
| Cross-page link | Data page → emit `VizRef` → switch to visualization page and load |
| Engine | Existing geo-viz widgets only (no new rendering stack) |

## Non-Goals

- Embedding full geo-viz interpreters inside the data page reader
- Cross-well multi-well auto layout / linked cursors / composite export
- Replacing the mapping editor; map tab is **read-only** geo-viz preview
- Deep unbounded SEGY load on the UI thread
- Collaborative or server-side viz services

## Current Baseline

- `VisualizationPage`: three-column MVP — summary counts · tabbed `WellLogCanvas` / `SeismicView` / `CrossWellWidget` · trace panel with non-functional buttons.
- Data for canvases comes mainly from **PredictionTask mock converters** (`well_log_data_from_prediction`, `seismic_volume_from_prediction`), not from `ProjectDocument.resources`.
- Data page LAS/SEGY previews are **summary tables** (`PreviewResult` modes `well_log` / `seismic`); images/PDF already use async media preload.
- Mapping already converts documents to canvas payloads via `mapping_helpers.preview_payload_from_*`.

## Architecture

```
DataPage                              VisualizationPage
  「在可视化中打开」 ──signal──► AppShell / PaleoWorkbenchWindow
                                        │
                                        ▼
                                open_visualization(VizRef)
                                        │
                ┌───────────────────────┼───────────────────────┐
                ▼                       ▼                       ▼
          VizAdapter              VizAdapter              VizAdapter
       from_resource(LAS)      from_resource(SEGY)    from_map_document
                │                       │                       │
                ▼                       ▼                       ▼
           WellLogData             bounded volume          map payload
           (+ tracks)               (ndarray)            (GeoJSON+wells)
                │                       │                       │
                ▼                       ▼                       ▼
           WellLogCanvas            SeismicView          PaleoMapCanvas
```

### Package layout

```
paleo_workbench/viz/
  __init__.py
  models.py          # VizKind, VizRef, VizPayload
  adapter.py         # VizAdapter.supports / resolve / from_*
  well_log_load.py   # LAS → WellLogData (bounded)
  seismic_load.py    # SEGY → ndarray (bounded)
  map_load.py        # PaleoMapDocument → canvas payload (reuse mapping_helpers)
```

**Boundary rule:** `paleo_workbench/viz/` must not import AppShell pages or create Qt widgets. UI pages own canvases; adapter owns pure data conversion.

### Core types

**`VizKind`:** `"well_log" | "seismic" | "map" | "prediction" | "message"`

**`VizRef`** (lightweight, UI-safe):

| Field | Meaning |
|-------|---------|
| `kind` | Target viz kind |
| `id` | Resource id, map document id, or task id |
| `path` | Optional filesystem path (resources) |
| `label` | Display name |
| `source` | `"data_page" \| "visualization_page" \| "prediction"` |

**`VizPayload`** (resolve result):

| Field | Meaning |
|-------|---------|
| `kind` | Same as ref or `"message"` on failure |
| `label` | Title for tab/trace |
| `well_log` | Optional `WellLogData` |
| `seismic_volume` | Optional `np.ndarray` |
| `map_features` / `map_wells` / `period_name` | Optional map canvas inputs |
| `message` | Human-readable empty/error state |
| `warning` | Non-fatal note (e.g. truncated SEGY) |

### VizAdapter API (conceptual)

```text
supports(asset | document) -> bool
ref_from_resource(resource) -> VizRef | None
ref_from_map_document(doc) -> VizRef
resolve(ref, project) -> VizPayload
from_prediction(task) -> VizPayload   # keep mock path for regression
```

## Page responsibilities

### Data page

- When the selected asset is `supports()`-true, show **「在可视化中打开」** (reader area or action panel).
- Click emits `open_in_visualization(VizRef)`; does **not** embed WellLogCanvas/SeismicView/PaleoMapCanvas in the reader.
- Existing preview modes (summary / image / PDF / text) remain the default reading experience.

### AppShell / Window

- Connect data page signal → `page_stack` index `PAGE_INDEX_VISUALIZATION` (5) → `VisualizationPage.open_ref(ref)`.
- Visualization page may also open refs from its own left list without involving the data page.

### Visualization page

| Zone | Behavior |
|------|----------|
| Left (`VisualizationSummaryPanel` → list-capable) | Counts plus selectable LAS / SEGY resources and map documents; selection calls `open_ref` |
| Center (`CompositeVisualizationPanel`) | Tabs: **测井** · **地震** · **连井** (unchanged shell) · **古地理** (`PaleoMapCanvas`). Load from current `VizPayload`; switch tab by kind |
| Right (`VisualizationTracePanel`) | Show current ref label, kind, path/status, source; **刷新视图** re-resolves and reloads |

**Load priority for 测井/地震 tabs:**

1. Current `VizRef` of matching kind (from data page or list).  
2. Else optional prediction-task mock (`from_prediction`) if a task exists.  
3. Else empty state with clear message.

**古地理 tab:** always from map document ref or active/last map document; reuse mapping preview payload conversion.

## Data flow

1. User selects asset on data page → preview as today.  
2. If supported → button visible.  
3. Click → `VizRef` → window switches page → `open_ref`.  
4. `payload = VizAdapter.resolve(ref, project)`.  
5. Composite panel loads the matching tab widget.  
6. Trace panel updates from ref + payload.

### Resolve rules

| Kind | Input | Success | Failure |
|------|-------|---------|---------|
| `well_log` | `ResourceItem` LAS path | Bounded `WellLogData` + tracks build on UI | Missing/parse error → `message` |
| `seismic` | `ResourceItem` SEGY path | Bounded volume for `SeismicView.load_demo` (or equivalent) | No segyio / read error → `message` |
| `map` | `PaleoMapDocument` (by id) | Facies GeoJSON + wells lng/lat + period | No geometry → empty canvas + message |
| `prediction` | `PredictionTask` | Existing mock converters | No task → empty |

### Bounds and performance

- LAS: limit number of curves and samples if needed for interactivity; prefer depth window or downsample rather than full multi-million-point tracks by default.
- SEGY: **bounded** load (max dimension / sample budget); set `payload.warning` when truncated.
- Map: in-memory document fields only (no heavy raster).
- V1 may resolve **synchronously** on the UI path for small fixtures; if real LAS/SEGY stalls the UI, follow-up reuses the data-page serial worker pattern. Spec does not require async for the first plan unless implementers hit proven freezes in tests.

### Error handling

| Case | Behavior |
|------|----------|
| Missing file | Payload `message`; no exception to event loop |
| Unsupported type | No button on data page; list excludes or disables |
| Partial parse | Best-effort payload + `warning` |
| Jump with deleted asset | Resolve fails → message empty state; stay on visualization page |

## Testing

| Level | Coverage |
|-------|----------|
| Unit | `VizAdapter.supports` / `resolve` with temp LAS, optional SEGY mock, map document fixtures |
| Widget | Data page button visibility + signal payload |
| Widget | `VisualizationPage.open_ref` selects tab and loads canvas / empty message |
| Integration | AppShell/window: data page action switches to index 5 and shows content |
| Regression | Prediction-driven mock path still works when no resource ref is set |

Use `QT_QPA_PLATFORM=offscreen`.

## Delivery slices (PR order)

1. `paleo_workbench/viz/` models + adapter + loaders + unit tests  
2. Visualization page: open_ref, list selection, 古地理 tab, refresh wired  
3. Data page button + signal; AppShell/window navigation  
4. Trace polish, planning file updates, full suite green  

## Success criteria

1. Fixture project with LAS + SEGY + `PaleoMapDocument` each renders on the correct visualization tab.  
2. Data page **「在可视化中打开」** switches to visualization with matching content.  
3. Missing/corrupt files yield message empty states without crash.  
4. Unsupported assets do not show the jump button.  
5. Existing prediction mock visualization path remains available.  
6. Tests cover adapter, jump, and page assembly.

## Open follow-ups (explicitly later)

- Async resolve for large LAS/SEGY via preview worker pattern  
- Cross-well assembly from multiple well_log resources  
- Linked cursor / multi-view sync  
- Data-page embedded thumbnail canvases (rejected for V1; option B earlier)
