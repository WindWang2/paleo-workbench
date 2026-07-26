# well_head asset preview & XY data paths

**Issue:** [#126](https://github.com/WindWang2/paleo-workbench/issues/126) (wayfinder research; map [#125](https://github.com/WindWang2/paleo-workbench/issues/125))  
**Scope:** Facts only — how the data page previews `well_head`, whether geoviz/dat draws well points, where name + X/Y are parsed, and which seam can host an interactive XY map (pan/zoom to well).  
**Status:** Research complete (read-only)  
**Date:** 2026-07-26  

No product UI is implemented here. Citations are repo paths + symbols.

---

## Executive summary

| Question | Answer (facts) |
|----------|----------------|
| How is `well_head` previewed on the data page? | Classified → `LocalVisualizationProvider` → `GeoVizEngine.prepare` → `PreviewKind.XY_SCATTER` → `GeoVizPreviewHost` / `PlotWidget` scatter. |
| Does geoviz/dat already draw well points? | **Yes.** `XYScatterBackend.render` adds one `ScatterSeries(x, y)` and draws circle markers. **Well names are parsed into the payload but not drawn as labels.** |
| Where are name + X/Y columns parsed? | **Data-page path:** `geoviz/previews/dat.py` `_well_head_payload` (header-driven column map). **Joint 3D path (separate):** `paleo_workbench/viz/joint_well_parsers.parse_well_heads` (fixed whitespace columns). |
| Seam for interactive scatter + pan/zoom to well? | **Primary:** extend `XYScatterBackend` + `PlotWidget` (or a drop-in widget for `PreviewKind.XY_SCATTER`) under the existing `GeoVizPreviewHost` / data-reader visualization tab. Payload already carries `names`/`x`/`y`; `PlotWidget` already has pan/zoom/autofit + index-based hover. |

---

## 1. Data-page preview routing for type `well_head`

### 1.1 Classification

**File:** `paleo_workbench/resources/classifier.py`  
**Symbol:** path parts containing `井位`, or name containing `wellhead` / `well_head` → type `"well_head"`.

**Display label / IO:** `paleo_workbench/resources/io_registry.py` — `"well_head": "井位"`, role `"input"`.

Representative sample on disk:

- `data/井位/ExportWellHead.dat` (UTF-8 BOM, SMI header `#WellHead File From SMI`, columns `#Name X Y KB TotalDepth BottomX BottomY WellType`).

Smoke expectation: `tests/test_geoviz_real_data_smoke.py` maps  
`("井位/ExportWellHead.dat", "well_head", PreviewKind.XY_SCATTER)`.

### 1.2 Provider path (Data page)

```
ResourceItem(type=well_head, format=dat)
  → LocalVisualizationProvider (DataReaderPanel default)
  → request_from_resource → PreviewRequest(semantic_type=resource.type, …)
  → GeoVizEngine.supports / prepare
  → PreviewResult(mode="geoviz", engine_preview=PreparedPreview)
  → DataReaderPanel.render → LazyVisualizationTabs.show_preview
  → GeoVizPreviewHost.render → engine.create_widget(kind) + engine.render
```

| Layer | Path | Symbol / role |
|-------|------|----------------|
| Default provider | `paleo_workbench/ui/pages/data_reader_panel.py` | Constructs `LocalVisualizationProvider` when no provider injected |
| Engine request | `paleo_workbench/ui/pages/geoviz_preview_provider.py` | `request_from_resource`, `LocalVisualizationProvider._build_preview` / `preview_visualization` → `_engine_result` (`mode="geoviz"`, `engine_preview=prepared`) |
| Async worker | `paleo_workbench/ui/pages/preview_worker.py` | Builds result on worker thread; disk cache eligible for `well_head` DAT |
| Disk cache | `paleo_workbench/ui/pages/preview_disk_cache.py` | `CACHEABLE_RESOURCE_TYPES` includes `"well_head"`; DAT only |
| Viz tab host | `paleo_workbench/ui/pages/lazy_visualization_tabs.py` | Lazy `GeoVizPreviewHost`; `show_preview(prepared)` |
| Host | `paleo_workbench/viz/hosts/geoviz_preview_host.py` | `GeoVizPreviewHost.render` — create widget per `PreviewKind`, `engine.render` |
| Engine registry | `geo-viz-engine/geoviz/engine.py` | `GeoVizEngine.default()` registers `XYScatterBackend` from `geoviz.previews.dat` |

### 1.3 Visualization adapter path (non–data-page, same engine)

**File:** `paleo_workbench/viz/adapter.py`  

- `_ENGINE_PREVIEW_TYPES["well_head"] = "engine_preview"`
- `_resolve_engine_preview` builds `PreviewRequest` and calls `GeoVizEngine.default().prepare`
- Returns `VizPayload(kind="engine_preview", prepared=…)`
- Hosted by `paleo_workbench/viz/hosts/engine_preview_host.py` → same `GeoVizPreviewHost`

Same prepare/render stack as the data page; different entry (project viz shell vs data reader).

### 1.4 Summary tab vs visualization tab

`LazyVisualizationTabs` has two tabs:

1. **数据列表** — summary table from `PreviewResult` (`summary_rows` for geoviz is e.g. `("井数", str(len(names)))` from `XYScatterBackend.prepare`).
2. **可视化预览** — user activates; host renders `PreparedPreview`.

`XYScatterBackend.capabilities` advertises interactions `("zoom", "pan")` only (no `"hover"` / pick in the capability tuple, though `PlotWidget` implements hover internally).

---

## 2. geoviz/dat well_head prepare & render

### 2.1 Backend

**File:** `geo-viz-engine/geoviz/previews/dat.py`  
**Class:** `XYScatterBackend`  
**Kind:** `PreviewKind.XY_SCATTER` (`geo-viz-engine/geoviz/contracts.py`)

| Method | Behavior |
|--------|----------|
| `supports` | `supports_well_head`: format `dat`, semantic `well_head`, header contains `_WELL_HEAD_MARKER` (`"WellHead File From SMI"`) |
| `prepare` | `_well_head_payload` → `PreparedPreview(kind=XY_SCATTER, payload=XYPreviewPayload, summary_rows=(("井数", N),))` |
| `create_widget` | `PlotWidget(parent)` from `geoviz_plots` |
| `render` | `widget.clear()`; `widget.add_series(ScatterSeries(x, y, name=preview.title))`; `widget.autofit()` |
| `release` | `widget.clear()` |

**Registered in:** `GeoVizEngine.default()` (`geoviz/engine.py` L49–L58).

### 2.2 Payload

```python
@dataclass(frozen=True)
class XYPreviewPayload:
    names: tuple[str, ...]
    x: np.ndarray
    y: np.ndarray
```

Constraints:

- Sampled with `representative_indices(row_count, min(options.max_points, _MAX_POINTS))` (`_MAX_POINTS = 50_000`).
- Default `PreviewOptions.max_points = 50_000` (`contracts.py`); workbench maps `PreviewSettings.geoviz_max_points` via `to_geoviz_options()`.
- Names + finite X/Y only; **KB / TD / BottomX / BottomY are not carried in the preview payload.**

### 2.3 Does it draw well points?

**Yes — scatter markers only.**

- `ScatterSeries` default: `size=6.0`, `marker_style="circle"` (`geoviz_plots/chart/series.py`).
- `PlotWidget.render_plot` draws markers for `ScatterSeries` via `draw_markers` (`geoviz_plots/chart/plot_widget.py`).
- Tests pin this: `test_well_head_render_adds_one_scatter_series_and_release_clears` (`geo-viz-engine/tests/test_geoviz_dat_preview.py`) — one `ScatterSeries`, viewport contains data extent, KD-tree metadata length == point count.

**What is not drawn today:**

| Feature | Status |
|---------|--------|
| Well name labels on map | **No** — `names` stored in payload, never passed to `ScatterSeries` / paint |
| Per-well color / type | **No** |
| Click → center & zoom to well | **No dedicated API** (manual pan/zoom exist; no “focus well” helper) |
| Hover shows well name | **No** — hover crosshair shows data X/Y; `point_selected` emits **series_name** (= file title, not well name), **index**, x, y |
| Bottom hole / trajectory | **No** in dat preview (joint 3D uses full `WellHead`) |

So: **points are already drawn**; interactive “pick well by name / list-link / zoom-to” is **partial infrastructure** (index-level hit + pan/zoom) without name wiring.

---

## 3. Where well name + X/Y columns are parsed

### 3.1 Data-page / engine path (canonical for asset preview)

**File:** `geo-viz-engine/geoviz/previews/dat.py`  
**Symbols:** `_well_head_payload`, `_WELL_HEAD_COLUMNS`, `_column_mapping`, `supports_well_head`

Requirements:

1. Header marker: `#…WellHead File From SMI…`
2. Column declaration line among headers, width-matched to data rows, mapping aliases:

| Logical field | Accepted header tokens (normalized alnum) |
|---------------|-------------------------------------------|
| `name` | `name`, `well`, `wellname` |
| `x` | `x` |
| `y` | `y` |

Allowed extras (ignored for payload): `bottomx`, `bottomy`, `datum`, `elevation`, `gl`, `kb`, `td`, `totaldepth`, `uwi`, `welltype`.

Data rows: `shlex.split` → name string + finite floats at mapped indices.

Fixture shape (`test_geoviz_dat_preview.well_head_dat`):

```text
#WellHead File From SMI
#Name X Y KB TotalDepth BottomX BottomY WellType
Alpha 100.0 500.0 …
```

Real file `data/井位/ExportWellHead.dat` matches this schema.

### 3.2 Joint scene path (separate parser)

**File:** `paleo_workbench/viz/joint_well_parsers.py`  
**Symbol:** `parse_well_heads(path) -> list[WellHead]`

- Whitespace-split lines; skip empty / `#` comments.
- Requires **≥ 7 columns**: `name, x, y, kb, td, bottom_x, bottom_y` by **position**, not header map.
- Does **not** require the SMI marker or named header columns.
- Domain model: `geoviz_well_seismic_3d.models.WellHead` (also re-exported via `geoviz`).

**Consumer:** `paleo_workbench/viz/joint_host.py` loads `paths.well_head` via `parse_well_heads` for the well–seismic joint 3D scene — **out of scope for map #125 destination**, listed only as a second parse site.

**Resolver:** `paleo_workbench/viz/joint_asset_resolver.py` finds `well_head` resources by type / name / `井位` path.

### 3.3 Parser comparison (facts)

| Aspect | `dat._well_head_payload` (preview) | `parse_well_heads` (joint) |
|--------|------------------------------------|----------------------------|
| Header-driven columns | Yes | No (fixed order) |
| SMI marker required | Yes (for supports + prepare) | No |
| Fields kept | name, x, y only | name, x, y, kb, td, bottom_x, bottom_y |
| Sampling / max_points | Yes | All rows |
| Used by data page | Yes | No |

Duplication risk if product wants one canonical well_head reader for both preview and joint; today they are independent.

---

## 4. Comparison only: `geoviz_map` WellsLayer hit_test

**File:** `geo-viz-engine/packages/geoviz_map/geoviz_map/layers/wells.py`  
**Class:** `WellsLayer`

| Topic | WellsLayer (map) | XYScatter / PlotWidget (well_head preview) |
|-------|------------------|--------------------------------------------|
| Coordinates | lng/lat → world (`WellMarker`) | Local rectangular X/Y metres |
| Paint | Dot + halo’d **name label** + collision | Scatter markers only |
| Hit test | `hit_test(screen_pt, viewport) -> well name \| None` (KDTree / O(N), `HIT_RADIUS=10`) | `check_nearest_point` → index in series; signal `point_selected(series_name, index, x, y)` |
| Hover scale | Yes (`HOVER_SCALE`) | Selection ring on selected index |
| Product context | Paleo map page / map canvas | Data asset DAT preview |

**Not a drop-in** for well_head DAT preview: different CRS model, layer stack, and page host. Useful reference for label + name-returning hit_test UX, not the recommended mount point for data-page well_head.

---

## 5. Recommended seam for interactive scatter + pan/zoom to well

### 5.1 Product-aligned host (data page)

Destination (map #125): **data asset preview**, full-well XY scatter, click well (plot or list) → center/zoom + highlight — **not** joint 3D.

Recommended stack (least new surface area):

```
DataReaderPanel
  └─ LazyVisualizationTabs  ("可视化预览")
       └─ GeoVizPreviewHost
            └─ widget for PreviewKind.XY_SCATTER
                 (today: PlotWidget via XYScatterBackend)
```

**Why this seam:**

1. Already the live path for `well_head` DAT (`mode="geoviz"`).
2. `PreparedPreview.payload` already has parallel arrays `names`, `x`, `y`.
3. `PlotWidget` already implements:
   - pan (drag), zoom (wheel at cursor), autofit (double-click)
   - spatial index + `point_selected` / `selected_point` / `highlight_point`
   - `view_xmin/xmax/ymin/ymax`, `data_to_pixel` / `pixel_to_data`, `view_changed`
4. No need to pull in `WellsLayer` or map projection for this ticket.

### 5.2 Concrete extension points (implementation candidates — not decisions)

Ordered by locality to existing code:

| Priority | Seam | What it enables |
|----------|------|-----------------|
| **A** | `XYScatterBackend.render` (`dat.py`) | Pass names into series or side-channel; optional label series; wire name lookup by index on hover/click |
| **B** | `PlotWidget` (`plot_widget.py`) | `focus_point(x, y, margin=…)` / set view bounds; name-aware hit (map index → `payload.names[i]`); emit well name; optional label paint |
| **C** | `GeoVizPreviewHost` or thin wrapper in workbench | Optional well-name list sibling widget + signal bridge list ↔ plot (if product wants dual UI); still renders engine widget |
| **D** | Custom `PreviewBackend` / alternate `create_widget` for `XY_SCATTER` | Full custom interactive map if PlotWidget constraints are too tight; still registered under same engine kind |

**Avoid as primary seam for this map:**

- `WellsLayer` / map page (wrong CRS, wrong product surface).
- `joint_well_parsers` / joint 3D host (out of scope for #125 destination).
- Replacing classification / disk cache contracts unless sampling policy for “all wells” changes (`max_points`).

### 5.3 Gaps to close for “click → center & zoom + highlight”

Facts from current code:

1. **Names not in widget** — render discards `payload.names` for drawing/hit identity.
2. **`point_selected` series_name** is the **file title**, not well name; well identity is only recoverable as **index** into the (possibly sampled) payload arrays.
3. **No public `set_viewport` / `center_on`** — zoom/pan exist; centering on a well is a small helper (set `view_*` around point with padding, or `zoom` + pan).
4. **Sampling** — if `len(rows) > max_points`, not all wells appear; list↔plot linkage must use the prepared payload’s names, not the full file, unless prepare policy changes.
5. **Capabilities** string currently `("zoom", "pan")` only — extend if product/tests assert interaction contracts.

### 5.4 Secondary path (same backend)

Visualization shell (`VizAdapter` → `EnginePreviewHost`) reuses the same `PreparedPreview` + host. Any `XYScatterBackend` / `PlotWidget` improvement automatically applies there without a second widget implementation.

---

## 6. End-to-end call graph (well_head DAT)

```
classifier → type well_head
DataReaderPanel.provider = LocalVisualizationProvider
  request_from_resource(ResourceItem)
  GeoVizEngine.prepare(PreviewRequest, PreviewOptions)
    → PreviewRegistry → XYScatterBackend.prepare
      → _well_head_payload → XYPreviewPayload(names, x, y)
  PreviewResult(mode=geoviz, engine_preview=PreparedPreview)
DataReaderPanel.render
  → LazyVisualizationTabs.load_summary + show_preview
    → GeoVizPreviewHost.render
      → XYScatterBackend.create_widget → PlotWidget
      → XYScatterBackend.render → ScatterSeries(x,y) + autofit
```

---

## 7. Primary source index

| Topic | Path | Symbols |
|-------|------|---------|
| DAT well_head backend | `geo-viz-engine/geoviz/previews/dat.py` | `XYScatterBackend`, `_well_head_payload`, `XYPreviewPayload`, `supports_well_head`, `_WELL_HEAD_COLUMNS` |
| Engine registration | `geo-viz-engine/geoviz/engine.py` | `GeoVizEngine.default` |
| Contracts | `geo-viz-engine/geoviz/contracts.py` | `PreviewKind.XY_SCATTER`, `PreparedPreview`, `PreviewOptions` |
| Plot canvas | `geo-viz-engine/packages/geoviz_plots/geoviz_plots/chart/plot_widget.py` | `PlotWidget`, `pan`, `zoom`, `autofit`, `point_selected`, `check_nearest_point` |
| Scatter series | `…/chart/series.py` | `ScatterSeries` |
| Data provider | `paleo_workbench/ui/pages/geoviz_preview_provider.py` | `LocalVisualizationProvider`, `request_from_resource` |
| Data UI host | `paleo_workbench/ui/pages/data_reader_panel.py`, `lazy_visualization_tabs.py` | `render`, `show_preview` |
| Engine preview host | `paleo_workbench/viz/hosts/geoviz_preview_host.py`, `engine_preview_host.py` | `GeoVizPreviewHost`, `EnginePreviewHost` |
| Viz adapter | `paleo_workbench/viz/adapter.py` | `_ENGINE_PREVIEW_TYPES`, `_resolve_engine_preview` |
| Joint parser | `paleo_workbench/viz/joint_well_parsers.py` | `parse_well_heads` |
| Map wells (comparison) | `geo-viz-engine/packages/geoviz_map/geoviz_map/layers/wells.py` | `WellsLayer.hit_test`, `paint` |
| Disk cache | `paleo_workbench/ui/pages/preview_disk_cache.py` | `CACHEABLE_RESOURCE_TYPES` |
| Tests | `geo-viz-engine/tests/test_geoviz_dat_preview.py`, `tests/test_geoviz_real_data_smoke.py` | prepare/render + real ExportWellHead |
| Sample data | `data/井位/ExportWellHead.dat` | SMI WellHead DAT |

---

## 8. One-line gist (for map Decisions)

Data-page `well_head` already routes to geoviz `XY_SCATTER` and draws XY scatter points via `PlotWidget`; names+X/Y come from `dat._well_head_payload`; interactive name labels / zoom-to-well should extend that backend+widget under `GeoVizPreviewHost` (not map `WellsLayer` or joint 3D).
