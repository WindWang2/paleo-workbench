# Data Page UI and Performance Optimization Design

> **Date:** 2026-07-10  
> **Status:** Approved for planning  
> **Approach:** Balanced surgical performance core (Approach A)  
> **Related:**  
> - `docs/superpowers/specs/2026-07-09-data-management-page-redesign.md` (workspace / floating panels / multi-format reader)  
> - `docs/superpowers/specs/2026-07-07-datapage-ui-management-performance-design.md` (earlier reader + bounds)

## Goal

Make the data management page feel smooth under **2000+ assets** and large directory imports, while keeping the current workspace layout.

Success means **perceived responsiveness**, not hard SLOs:

- Opening/refreshing the asset list does not freeze the UI
- Scrolling and filtering a large table stays interactive
- Changing selection shows a loading state and does not block the main thread on heavy preview work
- Large imports keep the existing background import path and apply results in a single batch refresh
- UI density and toolbar reachability improve only in small, surgical steps

## Constraints

### In scope

- Responsiveness (open page, selection preview, import refresh, search/filter)
- Scale (2000+ rows, large recursive imports)
- Light layout/density polish without changing the primary layout
- Preview pipeline improvements (async, cache, cancel-by-generation) on top of existing formats

### Architecture constraint (surgical)

Keep and extend:

- `DataPage`
- `DataToolbar`
- `DataWorkspace` (table | reader + floating catalog/actions)
- `FloatingPanel`
- `DataReaderPanel`
- `PreviewProvider` (structured preview states, not widgets)

Do **not** redesign the page as static cards again. Do **not** introduce a separate disk-backed project index service in this pass.

### Out of scope

- Persisted floating panel positions / drag-resize of overlays
- Drag-and-drop import
- Deleting files from disk
- Full SEG-Y trace visualization inside the data page
- Full LAS curve plotting
- Saving reader zoom/page state per file
- Hard latency SLOs enforced in CI
- Full visual redesign of chrome or brand

## Current Context

The 2026-07-09 redesign already delivered:

- Summary + toolbar + workspace splitter (table | reader)
- Floating catalog and floating operations overlays
- Multi-format reader path with library-backed widgets where available
- Async import via `QThread` / `_ImportWorker`

Remaining problems for large projects:

1. Table path is still oriented around full widget population patterns that do not scale to 2000+ rows
2. Search/filter can re-walk large lists without a dedicated in-memory index and input debounce
3. Preview work can still contend with the UI thread when selection changes rapidly
4. Import completion can refresh too much UI work in one main-thread burst
5. Reader empty/loading transitions and minor density issues still feel unfinished

## Target Architecture

```
DataPage
├── ResourceSummaryBar
├── DataToolbar          # search debounce, toggles
└── DataWorkspace
    ├── content_splitter
    │   ├── DataAssetTable (QTableView + AssetTableModel)
    │   └── DataReaderPanel (loading / ready / error / missing)
    ├── FloatingPanel[catalog]
    └── FloatingPanel[actions]

Helpers (no new page shell):
├── AssetTableModel      # full list + filtered row index map
├── FilterIndex          # in-memory category + text search
├── PreviewCache         # LRU by stable asset revision key
└── PreviewWorker        # QThread + generation token
```

### Data flow

1. Import/scan finishes on the existing background import thread.
2. `DataPage` applies `ImportReport` once: update project lists → `AssetTableModel.set_assets` → `FilterIndex.rebuild` → summary/catalog counts.
3. Catalog category or toolbar search changes → debounce → `FilterIndex.filter` → model updates visible row map only (no file IO, no preview load).
4. User selects a row → debounce selection slightly if needed → build cache key.
5. Cache hit → reader shows state immediately.
6. Cache miss → reader enters `loading` → `PreviewWorker` runs `PreviewProvider` → if generation still current, cache store + reader `ready`/`error`/`missing`.

## Component Design

### `AssetTableModel`

- Owns the full asset sequence (resources + export artifacts) and a `filtered_rows: list[int]` mapping view rows → source indices.
- Implements `QAbstractTableModel` for use with `QTableView`.
- `data()` returns only lightweight display fields (name, type, format, status, source, path, and existing custom columns). It must never read file bodies.
- Batch updates use model reset or ranged change notifications instead of per-cell `setItem` loops.
- Selection mapping: view index → asset object; `DataAssetTable` continues to emit `selected_asset_changed`.

### `DataAssetTable`

- Rehosts existing column definitions, column visibility menu, and reset-columns behavior on top of the model/view pair.
- Keeps public behaviors expected by `DataPage` and tests: category filter entry point, search entry point, selection signal, column settings button ownership.
- Renders only what Qt’s view virtualizes; no manual creation of thousands of `QTableWidgetItem`s.

### `FilterIndex`

- Rebuild inputs: current asset list after import/rescan/remove/`update_state`.
- Indexed fields (normalized lowercase strings): name, type, format, status, source, path.
- API:
  - `rebuild(assets) -> None`
  - `filter(category: str, search_text: str) -> list[int]`
- Category semantics remain those of `DataCatalogPanel`.
- Search applies after category filter. Empty search means category-only.
- Toolbar search is debounced (~150–200ms) before calling `filter`.
- Filtering never invokes preview loading or file reads.

### `PreviewCache`

- Key components (tuple or equivalent):
  - asset kind (`resource` | `artifact`)
  - asset `id`
  - path (`ResourceItem.path` or `ExportArtifact.output_path`)
  - `checksum` when present on `ResourceItem` (else empty)
  - optional filesystem revision: `(size, mtime_ns)` from a cheap `Path.stat()` when the path exists; omitted when the file is missing
- Value: structured preview state produced by `PreviewProvider`.
- Policy: LRU with a small fixed capacity (default 32 entries) to bound memory.
- On key mismatch after rescan/import or file rewrite on disk, treat as miss.
- Do not add `size`/`mtime` fields to the Pydantic models in this pass; stat is only for cache keys.

### `PreviewWorker`

- Runs preview preparation off the UI thread.
- `DataPage` / `DataReaderPanel` coordination uses a monotonically increasing `generation` integer per selection request.
- Completion handler ignores results whose generation is stale.
- Does not require hard thread abort; stale work is discarded on finish.
- Existing bounded preview limits remain authoritative:
  - text: bounded byte/line chunk
  - tables: bounded rows/columns
  - PDF: current page only
  - images: single scaled view, no hidden multi-variant generation

### `DataReaderPanel`

- Explicit UI states: `empty`, `loading`, `ready`, `error`, `missing`.
- `loading` uses a stable placeholder so the panel does not flash empty on every row change.
- Continues to consume preview states and delegate format widgets; this design does not replace format readers.
- Emits existing reader-mode / context updates after a current generation result is applied.

### Import refresh path

- Keep `_ImportWorker` / `QThread` import execution.
- While import runs: show existing in-progress status; block re-entrant import; allow browsing the previous table snapshot.
- On success: single batch model + index + summary/catalog refresh.
- On failure: existing failed status path; leave previous assets intact.

### Light UI polish (S6)

Allowed, low-risk adjustments only:

- Clearer checked/active feedback for catalog and reader toggles
- Reader loading placeholder
- At most one or two density tweaks on the data page (for example slightly tighter page margins) if they free meaningful table/reader space
- No new permanent side columns; floating overlays remain overlays

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Preview parse/render failure | Reader `error` with path + short reason; no modal |
| Missing optional dependency (e.g. QtPdf widgets) | Degrade to message/summary; page stays up |
| Missing file | Reader `missing`; rescan may flip status |
| Rapid multi-row selection | Only last generation is shown |
| Preview in flight when selection changes | Stale result discarded |
| Import already running | Keep “正在导入” behavior; no second job |
| Filter matches nothing | Empty table state; reader empty |
| Truncated large text/table preview | Keep truncation notices from provider |
| Cache entry obsolete after rescan | Miss and reload |

## Testing

Prefer behavior tests with many lightweight mock `ResourceItem`s rather than huge real binaries.

Required coverage:

1. **Model/filter scale:** ~2000 mock assets; category/search change visible row counts without calling preview.
2. **Selection generation:** rapid selection of A then B ends with B’s preview/result.
3. **Cache hit:** re-selecting an unchanged asset does not re-invoke provider (spy/mock).
4. **Async preview states:** loading then ready; failure maps to error message state.
5. **Import batch refresh:** after import finish, model row count and summary update once with expected totals.
6. **Regression:** import/remove/rescan/open-folder, column settings, floating panel toggles, reader mode signals, `data_context_changed`.
7. **Assembly smoke:** `DataPage` still owns toolbar + workspace + floating panels.

Non-goals for tests: asserting wall-clock latency thresholds in CI.

## Delivery Slices

Balanced incremental delivery (each slice improves scale/responsiveness and keeps the surgical boundary):

| Slice | Work | Main win |
|-------|------|----------|
| S1 | `AssetTableModel` + virtual `QTableView`; migrate column settings | Open/scroll large lists |
| S2 | `FilterIndex` + debounced search; catalog via index | Search/filter |
| S3 | `PreviewWorker` + generation + loading state | Selection does not block UI |
| S4 | `PreviewCache` LRU + key invalidation | Re-select / back-and-forth |
| S5 | Import completion batch model refresh + status copy | Large folder import aftermath |
| S6 | Light UI polish (loading placeholder, toggle feedback, minor density) | Layout feel |

Recommended order: S1 → S2 → S3 → S4 → S5 → S6.  
S5/S6 must not block S1–S4 correctness.

## Compatibility

Public/page-level contracts to preserve:

- `DataPage.update_state(state, resources, artifacts=None)`
- Import / rescan / remove / open-folder behaviors
- `data_context_changed` payload role (counts + selection context)
- Toolbar search, catalog category, column settings semantics
- Floating panels as overlays (not permanent splitter children)

Internal table implementation may change from `QTableWidget` to `QTableView`+model; tests that hardcode widget types should be updated to behavior assertions.

## Success Criteria

- 2000+ mock or real assets: list remains scrollable and filterable without UI freeze
- Selecting different rows shows loading (on miss) and settles on the latest selection
- Re-selecting an unchanged asset is instant via cache when preview was already computed
- Import of a large folder does not require a second architecture; completion refresh is batched
- No regression in existing data-page management actions covered by the suite
- Layout still reads as table + reader with floating catalog/actions

## Open Implementation Notes

These are implementation choices, not open product questions:

- Exact debounce intervals may be tuned (search ~150–200ms; optional short selection debounce)
- Preview cache capacity default 32; adjustable constant
- Whether `FilterIndex` lives as a standalone module or a helper next to `data_asset_table.py` is an implementation detail
- Generation token can live on `DataPage` or a small coordinator used by the reader panel
