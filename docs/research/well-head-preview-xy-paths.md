# Research: well_head asset preview & XY data paths

**Ticket:** paleo-workbench #126 (wayfinder research)
**Map:** #125 数据井位平面预览（点井定位）
**Date:** 2026-07-26
**Scope:** Read-only inventory of how `well_head` is previewed today, where name/X/Y are parsed, and seams for interactive pan/zoom-to-well.
**Primary sources:** package source under `geo-viz-engine/` and workbench `paleo_workbench/`.

---

## 1. Executive summary

| Need | Exists today? | Where |
|------|---------------|--------|
| Classify asset as `well_head` | **Yes** | `paleo_workbench/resources/classifier.py` (path/name heuristics) |
| Data page routes well_head to engine preview | **Yes** | `viz/adapter.py` → `engine_preview`; `LocalVisualizationProvider` |
| Parse name + X + Y for preview | **Yes** | `geoviz/previews/dat.py` `_well_head_payload` → `XYPreviewPayload` |
| Draw all wells as XY scatter | **Partial** | `XYScatterBackend.render` → `PlotWidget` + `ScatterSeries`; **may subsample** via `representative_indices` / sample limit |
| Pan / zoom on preview | **Yes** | `PreviewCapabilities(..., ("zoom", "pan"))`; `PlotWidget` mouse pan/wheel |
| Click well → center/zoom + highlight by name | **Implemented** | `PlotWidget.point_clicked` identifies the point; `WellLocationPreview` maps its stable record identity, highlights it, and focuses the view |
| Full-file well list for joint 3D | **Yes (separate path)** | `joint_well_parsers.parse_well_heads` (all non-comment rows, 7+ columns) |
| Geographic map WellsLayer hit_test | **Yes (other surface)** | `geoviz_map` WellsLayer — lng/lat map canvas, not data DAT preview |

---

## 2. Classification & resource type

**File:** `paleo_workbench/resources/classifier.py`

- Path parts containing `井位`, or name containing `wellhead` / `well_head` → type `well_head`, format from extension (typically `dat`).

**File:** `paleo_workbench/resources/io_registry.py`

- Display label: `"well_head": "井位"`.

---

## 3. Data page → GeoViz engine path

```
Data page selection
    → PreviewProvider / LocalVisualizationProvider
    → PreviewRequest(path, semantic_type=well_head, format=dat, …)
    → GeoVizEngine.prepare / create_widget / render
    → data_reader_panel: mode=geoviz, engine_preview=PreparedPreview
    → lazy_visualization_tabs.show_preview / GeoVizPreviewHost.render
```

| Layer | File | Behavior |
|-------|------|----------|
| Adapter kind map | `paleo_workbench/viz/adapter.py` | `well_head` → `"engine_preview"` |
| Provider | `paleo_workbench/ui/pages/geoviz_preview_provider.py` | `request_from_resource` → `engine.prepare` → `PreviewResult(mode="geoviz", engine_preview=…)` |
| Panel | `paleo_workbench/ui/pages/data_reader_panel.py` | If `mode == "geoviz"`, render via engine preview host tabs |
| Host | `paleo_workbench/viz/hosts/geoviz_preview_host.py` | Stack of widgets per `PreviewKind`; `engine.create_widget` + `engine.render` |
| Composite viz | `paleo_workbench/viz/hosts/engine_preview_host.py` | Same `GeoVizPreviewHost` for Visualization tab |

Disk cache treats `well_head` DAT as cacheable (`preview_disk_cache.py` type set).

---

## 4. Engine: well_head prepare / render

**File:** `geo-viz-engine/geoviz/previews/dat.py`

### Support gate

- `supports_well_head`: format `dat`, semantic type `well_head`, header contains marker
  **`#WellHead File From SMI`** (`_WELL_HEAD_MARKER`).

### Columns

```text
_WELL_HEAD_COLUMNS:
  name → name | well | wellname
  x    → x
  y    → y
extras allowed: bottomx/bottomy, kb, td, uwi, …
```

### Payload

```python
@dataclass(frozen=True)
class XYPreviewPayload:
    names: tuple[str, ...]
    x: np.ndarray  # float64
    y: np.ndarray
    resource_id: str
    record_ids: tuple[int, ...]
    source_rows: tuple[int, ...]
    source_version: str
    source_crs: str
    coordinate_units: str
    diagnostics: XYPreviewDiagnostics
```

Built by `_well_head_payload`:

1. Scan header + column mapping and explicit SourceCRS/X/Y units.
2. Parse every row independently and retain structured diagnostics for bad rows.
3. Keep all valid wells up to the explicit 50,000-record resource limit.

### Backend `XYScatterBackend`

| Method | Behavior |
|--------|----------|
| `kind` | `PreviewKind.XY_SCATTER` |
| `capabilities` | `("zoom", "pan", "hover", "point_select")` |
| `create_widget` | `PlotWidget` (`geoviz_plots`) |
| `render` | `widget.clear()`; **one** `ScatterSeries(x, y, name=preview.title)`; `autofit()` |
| `release` | `widget.clear()` |

**Important:** `XYPreviewPayload.names` is **not** passed into `ScatterSeries` as per-point labels. Series name is the preview **title** (file stem / label). Point identity for UI is only recoverable as **index** into `payload.names` if the host keeps the prepared payload.

---

## 5. PlotWidget interaction (seams for “点井定位”)

**File:** `geo-viz-engine/packages/geoviz_plots/geoviz_plots/chart/plot_widget.py`

Already present:

- Pan (drag), wheel zoom at cursor, double-click autofit.
- `point_hovered` and `point_clicked` have distinct semantics and carry series
  name, **index**, x, and y. The old `point_selected` attribute is deprecated
  and no longer emits.
- `check_nearest_point` — KDTree / O(N) nearest within ~15 px.
- Viewport fields: `view_xmin/xmax/ymin/ymax`; `autofit()` uses ~5% margin.

**Gaps for map destination:**

1. **No public “center on (x,y) with scale”** helper documented in backend — would set view bounds around a point (or call into new API).
2. **Click vs pan** already competes (left drag pans); selection likely on hover/move path (`check_nearest_point`) — confirm call sites before relying on click-to-select.
3. **Labels:** scatter render does not draw well name strings (unlike `WellsLayer` map labels).

---

## 6. Parallel path: joint host full parse (not data preview)

**File:** `paleo_workbench/viz/joint_well_parsers.py` — `parse_well_heads`

- Reads **all** non-empty, non-`#` lines with ≥7 whitespace fields.
- Columns: `name, x, y, kb, td, bottom_x, bottom_y` → `geoviz.WellHead`.
- Used by `WellSeismicJointHost` / asset resolver (`data/井位/ExportWellHead.dat`), **not** by `XYScatterBackend`.

Differences vs preview:

| | Preview `_well_head_payload` | `parse_well_heads` |
|--|------------------------------|--------------------|
| Header schema | Marker + named columns | Implicit position columns |
| Sampling | Sample limit / representative indices | Full file |
| Extra fields | Optional mapped | Fixed 7 fields |

---

## 7. Comparison: `geoviz_map` WellsLayer

**File:** `geo-viz-engine/packages/geoviz_map/geoviz_map/layers/wells.py`

- Map canvas wells with **lng/lat**, labels, `hit_test(screen_pt, viewport)` → well **name**.
- Used for paleo map / mapping chrome (`map_canvas_panel`), **not** for data-page DAT well_head preview.

Useful as a **pattern** (name-returning hit-test + labels), not the current data preview seam.

---

## 8. Recommended seams for destination (facts → product)

Highest reuse for “data well_head preview + click to locate”:

1. **Keep** `LocalVisualizationProvider` + `XYScatterBackend.prepare` payload (`names`, `x`, `y`).
2. Render points by **index → `names[i]`** and use `PlotWidget.focus_point`
   plus the public viewport snapshot/restore API.
3. Let `WellLocationPreview` own list/search/selection behavior while
   `GeoVizPreviewHost` owns per-asset/version session state.
4. Keep the full valid well set through 50,000 records; reject larger assets
   with `ErrorCode.RESOURCE_LIMIT`.

Lower priority alternative: embed `WellsLayer` only if product moves to lng/lat map CRS (separate grilling #127).

Do **not** route data-page well map through joint 3D host for this map (out of scope per #125).

---

## 9. File index

| Symbol / area | Path |
|---------------|------|
| `XYPreviewPayload`, `XYScatterBackend`, `_well_head_payload` | `geo-viz-engine/geoviz/previews/dat.py` |
| `PlotWidget`, `point_hovered`, `point_clicked` | `geo-viz-engine/packages/geoviz_plots/.../plot_widget.py` |
| `LocalVisualizationProvider` | `paleo_workbench/ui/pages/geoviz_preview_provider.py` |
| `GeoVizPreviewHost` | `paleo_workbench/viz/hosts/geoviz_preview_host.py` |
| Data panel geoviz branch | `paleo_workbench/ui/pages/data_reader_panel.py` |
| `parse_well_heads` | `paleo_workbench/viz/joint_well_parsers.py` |
| `WellsLayer.hit_test` | `geo-viz-engine/packages/geoviz_map/.../wells.py` |
| Type → engine_preview | `paleo_workbench/viz/adapter.py` |

---

## 10. Implications for open map tickets

- **#127 CRS:** preview uses raw file X/Y as plot axes (no CRS transform in `XYScatterBackend`). Axis meaning is “file X/Y”, not auto-geodetic.
- **#128 interaction:** nearest-point + signal exist; need product policy + wire zoom-to + labels/list.
- **#129 prototype:** should show scatter + click zoom + optional name list matching this seam.
