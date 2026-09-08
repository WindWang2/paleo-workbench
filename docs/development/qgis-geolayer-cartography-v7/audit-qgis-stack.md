# QGIS Integration Stack — Deep Audit (qgis-geolayer-cartography-v7)

Audit scope: `native/qgis_render_bridge/**` (all src), `paleo_workbench/ui/qgis_stack/**` (all files), `paleo_workbench/mapping/{qgis_mirror,qgis_style,scalar_raster_mirror,map_render_backend,layout_export}.py`, `paleo_workbench/mapping_workspace/layer_group_controller.py`, bridge-consuming tests, `qt_platform.py` / `env_bootstrap.py`.
All refs are `file:line` against this worktree. No file was modified except this audit.

---

## 1. BRIDGE API SURFACE

Single pybind11 module `qgis_render_bridge`, defined in `native/qgis_render_bridge/src/bindings.cpp` (PYBIND11_MODULE at bindings.cpp:351). Submodules: `geometry` (bindings.cpp:459) and `mapstack` (bindings.cpp:543). Build: opt-in via `PALEO_WITH_QGIS_RENDERER=1` (setup.py:23-29, CMakeLists.txt:4), links a vendored QGIS source snapshot (`third_party/qgis`) built as ExternalProject with `WITH_GUI=ON WITH_ANALYSIS=ON WITH_PYTHON=OFF` (CMakeLists.txt:34-66, setup.py:172-227). Module metadata: `__version__ = "0.2.17a0"`, `__build_commit__ = "unknown"` (bindings.cpp:355-356). Exception `QgisGeometryError` registered at bindings.cpp:357.

### 1.1 Top-level class `QgisRenderBridge` (bindings.cpp:359-423; impl `qgis_render_bridge.cpp:564-797`)

Offscreen render service; owns its own mirror layers (never in a QgsProject). Wraps QgsApplication, QgsVectorLayer/QgsRasterLayer (memory/gdal), QgsMapRendererParallelJob, QgsMapRendererCustomPainterJob, QSvgGenerator/QPdfWriter.

| Member | Signature | Notes |
|---|---|---|
| `__init__` | `()` | |
| `initialize` | `(prefix_path="")` | Only accepts the compile-time vendored prefix (`qgis_render_bridge.cpp:574-595`); process-global initQgis guard shared with mapstack (`g_qgis_initialized`, qgis_render_bridge.cpp:74, #1155). |
| `set_layer_snapshot` | `(layers: iterable[dict], project_crs: str)` | Wire dicts parsed by `parse_layers` (bindings.cpp:47-214): id/name/crs, `kind:"raster"`+`source_path` (bindings.cpp:55-58), style{fill,stroke,stroke_width,marker_size,marker,line_pattern,renderer,field,renderer_xml,labeling_xml,rules[],categories{},ranges[],labels{field,visible,font_family,size,bold,color,buffer,buffer_color,rotation_field,size_field,color_field}}, data_revision, style_revision, visible, opacity, scale_range[2], features[{id,wkt,attributes}] or `delta{base_revision,changed_features[],removed_ids[]}` (#932). |
| `request_render` | `(extent[4], width:int, height:int, dpi:float, generation:uint64)` | Async, coalescing; requires event-loop pumping (threading contract #938-5, bindings.cpp:366-379, hpp:139-156). |
| `take_completed_frame` | `() -> dict\|None` | `{generation,width,height,stride,render_ms,rgba:bytes}` (bindings.cpp:224-235). |
| `cancel_render` | `()` | |
| `render_sync` | `(extent, width, height, dpi) -> dict` | GIL released around render (#1031, bindings.cpp:380-392). |
| `export_vector` | `(path, format:"svg"\|"pdf", extent, width, height, dpi) -> int bytes` | GIL released (#1031, bindings.cpp:393-404; impl qgis_render_bridge.cpp:730-789). |
| `shutdown` | `()` | Releases mirrors; QGIS runtime stays process-global (qgis_render_bridge.cpp:707-728). |
| `diagnostics` | `() -> dict` | mirror_builds/mirror_reuses/style_reapplies/feature_deltas/delta_changed_features/delta_removed_features (bindings.cpp:406-416). |
| `initialized` / `render_active` / `version` | readonly props | `version` returns `_QGIS_VERSION`. |

Snapshot apply semantics (`apply_snapshot`, qgis_render_bridge.cpp:291-469): reuse mirror when data_revision unchanged; **feature delta** applied in place when `delta.base_revision == mirror.data_revision` (delete+re-add, `__pwb_id` host-keyed fid index, apply_feature_delta qgis_render_bridge.cpp:192-289); style-only change reapplies renderer/labeling without rebuild; raster layers always **fully rebuilt** on any style_revision change (qgis_render_bridge.cpp:343-346). Pre-validates style XML and delta base revisions so failures leave live mirrors untouched (#519/#932). `lifecycle_mutex` serializes mirror mutation vs sync renders (#1133, qgis_render_bridge.cpp:174, 326, 689, 746).

### 1.2 Top-level functions

- `legacy_style_to_renderer_xml(style: dict, geometry_type: str) -> str|None` (bindings.cpp:270-335, 425-427) — migration entry `migrate_legacy_style` (mapping/qgis_style.py:148-157).
- `renderer_info(renderer_xml) -> {type, symbol_count}|None` (bindings.cpp:339-347, 429-430).
- `run_renderer_properties_dialog(request: dict) -> {ok, renderer_xml, opacity}` (bindings.cpp:432-440; gui_service.cpp:137-148) — wraps `QgsRendererPropertiesDialog`.
- `run_symbol_selector_dialog(request: dict, symbol_index: int)` (bindings.cpp:442-450; gui_service.cpp:150-188) — wraps `QgsSymbolSelectorDialog` on a cloned renderer.
- `run_style_manager_dialog(style_db_path: str) -> bool` (bindings.cpp:452-457; gui_service.cpp:190-209) — wraps `QgsStyleManagerDialog` on a `QgsStyle` sqlite db.

`GuiDialogRequest` fields (gui_service.hpp:18-33): title, geometry_type, crs, field_names, renderer_xml, fill/stroke/stroke_width/marker_size (legacy fallback), style_db_path. Dialogs need QApplication on the GUI thread (gui_service.cpp:36-47) and build a throwaway memory layer (`make_dialog_layer`, style_codec.cpp:241-265) plus temp QgsStyle db.

### 1.3 Submodule `geometry` (bindings.cpp:459-541; geometry_service.cpp)

Stateless QgsGeometry/QgsGeometryEngine ops. Inputs: GeoJSON dict or JSON/WKT string; outputs: GeoJSON JSON string (precision 17). All raise `QgisGeometryError`.

`union(geometries)`, `split_by_line(geometry, cutter)`, `intersection(a,b)`, `difference(a,b)`, `symdifference(a,b)`, `buffer(geometry, distance, segments=8)`, `offset_curve(line, distance)` (line-only), `simplify(geometry, tolerance)`, `smooth(geometry, iterations=1, offset=0.25)`, `densify(geometry, interval)`, `make_valid(geometry)`, `is_valid(geometry) -> bool`, `multipart_to_singlepart(geometry) -> list`, `singlepart_to_multipart(parts)`, `clip(geometry, extent[4])`. (geometry_service.hpp:23-40, geometry_service.cpp:53-182.)

### 1.4 Submodule `mapstack.QgisMapStack` (bindings.cpp:544-799; impl `map_stack_service.cpp`)

Interactive canvas/layer-tree/edit host. Two modes: `initialize(display: bool=False)` — display=True creates an **owned QgsProject** (map_stack_service.cpp:884-887); non-display uses process-global `QgsProject::instance()` (map_stack_service.cpp:856-859). All Qt objects cross the boundary as raw `uintptr_t` addresses; no QWidget crosses (widgets.py:8-16).

Groups (V5, custom property `pwb/group_id`, map_stack_service.cpp:396): `group_exists`, `upsert_group(group_id, name, parent_group_id="")`, `remove_groups_except(group_ids)` (children promoted, never deleted), `rename_group`, `set_group_visibility`, `move_layer_to_group(doc_id, group_id, index)`, `move_group(group_id, parent_group_id, index)` (descendant check), `tree_snapshot_json()`, `apply_tree_placements(placements_json) -> {"applied","skipped"}` (single-sync batch), `set_group_expanded(tree, node_id, expanded)`. map_stack_service.hpp:94-118, cpp:1747-2068.

Canvas: `create_canvas() -> addr`, `destroy_canvas(addr)`, `set_canvas_white_background`, `set_destination_crs`, `set_canvas_extent` (finite+ordered guard #1165, cpp:1235-1246), `canvas_extent`, `zoom_to_full/previous/next_extent`, `refresh_canvas` (async #1156), `is_canvas_rendering`, `screen_to_map`/`map_to_screen` (double precision, #1165), `set_canvas_white_background`. Pan/zoom tools: `set_map_tool(canvas, kind)` with kinds pan|zoomIn|zoomOut|addPoint|addLine|addPolygon|vertex|move|select|identify (cpp:2346-2433). Callbacks: `set_extent_callback`, `set_xy_callback`, `set_digitize_callback(status, geojson)`, `set_edit_pick_callback(action, payload)`, `set_selection_callback(action, payload)` — all GIL-acquiring std::function (bindings.cpp:650-712).

Layers/mirrors: `add_vector_layer_geojson(name, geometry_type, crs_auth_id, geojson, renderer_xml="", labeling_xml="", legacy_style=None)`, `set_layer_style(layer_id, renderer_xml, labeling_xml, legacy_style)`, `remove_layer`, `set_layer_visibility`, `set_layer_opacity`, `clear_project_layers`, and the **doc-keyed mirror API**: `upsert_mirror_layer(doc_id, name, geometry_type, crs_auth_id, geojson, renderer_xml, labeling_xml, legacy_style, visible, opacity, is_reference=False, is_editable=False, reference_snap=False) -> qgis_id`, `remove_mirror_layers_except(doc_ids)`, `set_mirror_layer_order(doc_ids_top_first)`, `set_mirror_layer_visibility(doc_id, visible)`, `set_mirror_layer_opacity(doc_id, opacity)`, `mirror_order_top_first()`, `mirror_layer_visibility(doc_id)`, `tree_echo_suppressed()`. Mirror layers are `QgsVectorLayer` memory providers (`"<geom>?crs=<id>"` URI, cpp:1523-1526) tagged with custom properties `pwb/doc_id`, `pwb/style_sig`, `pwb/reference`, `pwb/editable`, `pwb/reference_snap` (cpp:1546-1554). Geometry-kind drift forces mirror rebuild (#1153, cpp:1460-1471).

Edit/digitize (M3): `set_snapping_config(canvas, config_json)` (AdvancedConfiguration w/ per-layer settings + `reference_enabled` auto-adds pwb/reference layers; cpp:2239-2301), `snap_to_map(canvas, x, y) -> dict`, `native_tool_busy(canvas)`, `set_current_layer(canvas, doc_id)`, `highlight_features(canvas, doc_id, feature_ids_json)` / `clear_highlights` / `highlight_count` (QgsHighlight projection; Python selection authoritative, cpp:2572-2620), `set_edit_indicator(tree, doc_id, on)` / `edit_indicator_count` (✏ QgsLayerTreeViewIndicator, cpp:3155-3204). Custom C++ tools in edit_tools.cpp: `PwbVertexTool`, `PwbMoveTool`, `PwbSelectTool` (app-layer QgsVertexTool/QgsMapToolMoveFeature are un-linkable APP_EXPORT; edit_tools.hpp:3-6) plus `QgsMapToolDigitizeFeature` capture kits with hidden `QgsAdvancedDigitizingDockWidget` and scratch memory layers (cpp:2435-2495). fid mapping `__pwb_fid` ↔ QgsFeatureId rebuilt per upsert (recordMirrorFeatureFids cpp:123-151, count-mismatch discards the table).

Tree view: `create_layer_tree_view(canvas) -> addr` (QgsLayerTreeView + QgsLayerTreeModel with ShowLegend/AllowNodeReorder/AllowNodeRename/AllowNodeChangeVisibility, cpp:2700-2772), `set_tree_selection_callback`, `set_tree_change_callback` (batched JSON, schema 2 w/ typed events + full tree snapshot, flushTreeChange cpp:3009-3050), `set_tree_menu_callback` (PwbLayerTreeMenuProvider, cpp:728-837), `set_tree_expand_callback`, drive/inspection API `tree_view_row_count/layer_name/set_current_row/set_row_checked/rename_row/move_row`, `tree_view_select_doc`.

Dialog: `exec_layer_properties(canvas, doc_id) -> {ok, renderer_xml?, labeling_xml?, opacity?, name?}` — native `QgsVectorLayerProperties` modal (bindings.cpp:780-793, cpp:3234-3269).

Persistence: `write_project_xml() -> str` (QgsProject::write into temp, cpp:2070-2086) and `apply_project_xml(xml) -> int applied` (donor QgsProject read; re-applies renderer/labeling/opacity/name/visibility to live mirrors by `pwb/doc_id`, restores group tree + placements; features stay in Python, cpp:2088-2199).

Layout (M7): `layout_export(spec_json, output_path, format="pdf", dpi=300.0) -> report_json` (see §4).

### 1.5 Wrapped Qgs* classes (summary)

- Render bridge: QgsApplication, QgsVectorLayer, QgsRasterLayer, QgsMapSettings, QgsMapRendererParallelJob, QgsMapRendererCustomPainterJob, QSvgGenerator, QPdfWriter, QgsCoordinateReferenceSystem.
- style_codec: QgsFeatureRenderer (+QgsSingleSymbolRenderer/QgsCategorizedSymbolRenderer/QgsGraduatedSymbolRenderer/QgsRuleBasedRenderer), QgsSymbol/QgsFillSymbol/QgsLineSymbol/QgsMarkerSymbol/QgsSimpleMarkerSymbolLayer, QgsPalLayerSettings/QgsTextFormat/QgsTextBufferSettings/QgsVectorLayerSimpleLabeling, QgsAbstractVectorLayerLabeling (style_codec.cpp:11-33).
- gui_service: QgsRendererPropertiesDialog, QgsSymbolSelectorDialog, QgsStyleManagerDialog, QgsStyle, QgsGui (gui_service.cpp:14-28).
- mapstack: QgsMapCanvas, QgsProject, QgsLayerTree{,Group,Layer,Model,View}, QgsLayerTreeMapCanvasBridge, QgsLayerTreeRegistryBridge, QgsLayerTreeViewDefaultActions/Indicator, QgsMapTool{,Pan,Zoom,Capture,DigitizeFeature,IdentifyFeature}, QgsAdvancedDigitizingDockWidget, QgsSnappingConfig/Utils, QgsPointLocator, QgsHighlight, QgsRubberBand, QgsVectorLayerProperties, QgsPrintLayout + layout items, QgsJsonUtils.
- edit_tools: QgsMapTool, QgsMapToolSelectionHandler, QgsRubberBand, QgsPointLocator, QgsVertexId.
- geometry_service: QgsGeometry, QgsGeometryEngine, QgsJsonUtils, QgsRectangle.

---

## 2. PYTHON WRAPPERS (`paleo_workbench/ui/qgis_stack/`)

- `__init__.py` — exports QgisCanvasHost, QgisDisplayCanvas, create_display_canvas.
- `canvas_shim.py` — **QgisCanvasShim(QWidget)** (canvas_shim.py:122): interactive authoring canvas. Loads `qgis_render_bridge.mapstack.QgisMapStack` via `_load_mapstack` (canvas_shim.py:54-64) which raises RuntimeError with rebuild instructions on ImportError (no silent fallback — its only caller catches everything, see §2.6). Owns QgisCanvasHost (address-wrapped real QgsMapCanvas, canvas_shim.py:148-153), StackEvents (extent/xy callbacks re-queued via QTimer.singleShot(0), events.py:12-24). Signals: extent_changed(tuple), map_position_changed(tuple), backend_status_changed(str), tool_operation(bool), native_identified(dict), measure_segment/measure_preview(float) (canvas_shim.py:127-137). Extent history (100 entries) with programmatic-vs-user dedup (F2/F4, canvas_shim.py:200-294). Tool mapping via monkey-patched `set_active_tool` (canvas_shim.py:599-675): zoom_in→zoomIn, add_point→addPoint, add_line→addLine, add_polygon→addPolygon, vertex→vertex, move_feature→move, select/select_rectangle→select, identify→identify, pan→pan; measure_distance has **no native tool** — `_CanvasMouseRouter` event-filters the canvas viewport and feeds mouse events to the Python tool (canvas_shim.py:67-119, 520-568). Digitize/edit-pick/selection callbacks forward to `tool.commit_geometry/commit_vertex_move/commit_move/commit_selection` (canvas_shim.py:680-802). Exports: PNG via canvas.grab() with render-wait pump (canvas_shim.py:854-899); SVG/PDF via a fresh offscreen `QgisMapRenderBackend` fed the retained `_last_snapshot` (canvas_shim.py:908-943). Snapping push `set_snapping_config` (canvas_shim.py:429-443), `set_current_layer`, `native_tool_busy`, `cancel_native_tool` (Esc postEvent). `set_layer_snapshot` delegates to `mirror_snapshot_to_stack` and retains `_last_snapshot` (canvas_shim.py:805-835). Lifetime: `_LIVE_SHIMS` WeakSet + `shutdown_live_shims()` for host teardown (canvas_shim.py:36-49); `_mark_disposed` never re-enters the bridge during Qt destruction (canvas_shim.py:989-998).
- `widgets.py` — `cpp_pointer`/`wrap_widget` (shiboken6) address↔QWidget boundary; `QgisCanvasHost` (creates canvas via `stack.create_canvas()`, embeds into layout) and `QgisLayerTreeHost` (creates tree view) (widgets.py:8-45).
- `mirror.py` — compat re-export of `paleo_workbench.mapping.qgis_mirror.mirror_snapshot_to_stack` (mirror.py:6-8; M7 layering).
- `mapping/qgis_mirror.py` — **layer creation path**: for each snapshot layer with `layer_type == "vector"` (raster types skipped, qgis_mirror.py:41-42), builds a GeoJSON FeatureCollection with `__pwb_fid` injected (qgis_mirror.py:44-53), infers memory-provider geometry name from first feature geometry or `metadata.geometry_kind` (qgis_mirror.py:57-64), then `stack.upsert_mirror_layer(doc_id, ...)` with **QGIS-authoritative styles**: `style["qgis_style"]["renderer_xml"/"labeling_xml"]` if present, else the flat legacy VectorStyle dict as `legacy_style` (qgis_mirror.py:65-103). Tail: `remove_mirror_layers_except(seen)`, then `set_mirror_layer_order(seen)` unless `groups=True`, then `refresh_canvas` (qgis_mirror.py:114-129). Failures collected and surfaced via `backend_status` ("qgis: degraded (N mirror failures)", canvas_shim.py:300-305, #1164).
- `layer_tree_panel.py` — **QgisLayerTreePanel** (layer_tree_panel.py:57): drop-in replacement for the QTreeWidget LayerManagerPanel. Binds `QgisLayerTreeHost` + tree callbacks (selection/change/menu) (layer_tree_panel.py:160-170). `_publish` pushes a `MapRenderSnapshot` through `canvas.set_layer_snapshot` (layer_tree_panel.py:210-218). User tree ops echo back through `_on_tree_change` → `tree_sync.parse_tree_events` (schema 2) writing visibility/renames/order into `_layers`, group events into `LayerGroupController`, then `display_state_changed` persists (layer_tree_panel.py:352-394). Menu action keys → 17 request signals (`_MENU_SIGNALS`, layer_tree_panel.py:36-54). Edit indicator via `set_edit_indicator` (layer_tree_panel.py:241-260). Opacity slider → `set_mirror_layer_opacity` (direct doc-keyed write, no reconcile) (layer_tree_panel.py:276-287).
- `tree_sync.py` — parsers for the tree-change JSON: `parse_tree_change` (legacy flat), `parse_tree_events` (schema 2 typed events + structure snapshot) (tree_sync.py:91-137).
- `display_canvas.py` — **QgisDisplayCanvas** (read-only preview: own QgsProject via `initialize(display=True)`, pan-only), `create_display_canvas()` factory which **falls back to UnifiedMapCanvas** when the bridge is missing (display_canvas.py:24-30). Overlay paints selection rings + decorations; click filter emits map_clicked. Mirrors snapshots via the same `mirror_snapshot_to_stack` (display_canvas.py:197-206).
- `mapping/map_render_backend.py` — `QgisMapRenderBackend` (offscreen QgisRenderBridge adapter, map_render_backend.py:1719-2021) + `_qgis_snapshot` wire encoder (map_render_backend.py:2024-2194) with feature-encoding cache, per-feature payload reuse, and the #932 **delta channel** (delta shipped when the bridge provably holds the previous revision and delta < full list, map_render_backend.py:2139-2156; stale-delta recovery `_reship_full_snapshot` map_render_backend.py:1865-1886). `qgis_backend_probe()` one-shot usability probe (import ≠ usable; ABI/prefix failures degrade, map_render_backend.py:2299-2329). `create_map_render_backend(prefer_qgis=True)` (map_render_backend.py:2332-2350). `_flatten_qgis_style` promotes `qgis_style.renderer_xml/labeling_xml` onto wire keys and fixes unit parity (px→pt label size, halo mm, buffer_color, map_render_backend.py:2197-2229).
- `mapping/qgis_style.py` — `QgisStylePayload` (schema_version 1: renderer_xml, labeling_xml, name, tags, revision) persisted next to legacy VectorStyle; `qgis_bridge_available()`; `qgis_scalar_pipeline_ready()` (bridge **and** osgeo.gdal, #925); `migrate_legacy_style` via `legacy_style_to_renderer_xml` (qgis_style.py:42-157).
- `mapping_workspace/layer_group_controller.py` — **LayerGroupController** (layer_group_controller.py:49): domain-authoritative group tree (system groups `phase*`/`factor.*`/`base.*`/`legacy.*` are non-deletable — see menu provider map_stack_service.cpp:747-751) reconciled into the native tree via group API: `reconcile`/`_apply_tree` diffs `build_desired_tree` against last snapshot and applies **delta placements** (`_place_delta`, layer_group_controller.py:428-450) or `_place_all`; `observe_tree_nodes` ingests user-structure echoes from the tree callback (layer_group_controller.py:543-604); degraded mode when no native stack (`mark_fallback`).

### 2.1 Save/reopen flow (map_qgis_project_xml envelope)

- Model field: `ProjectModel.map_qgis_project_xml: str` (project/models.py:618); dirty-domain mapping (project/manager.py:88).
- On load (`CompositeDocument.set_project`): applies envelope first (`stack.apply_project_xml(xml)`), then `_sync_composition_now()` so domain reconcile overrides legacy flat order (composite_document.py:2116-2120).
- On save/display change: `_write_map_project_xml` → `stack.write_project_xml()` stores the full QgsProject presentation XML (renderer/labeling/opacity/visibility/order/groups) (composite_document.py:2132-2136). Features never live in the envelope — they stay in Python documents; envelope reapplies onto live mirrors matched by `pwb/doc_id` (map_stack_service.cpp:2088-2199).

### 2.2 How edits flow back

Python `VectorEditSession` is the sole authority. Native callbacks deliver (doc feature ids via the `__pwb_fid` map):
- digitize complete → `tool.commit_geometry(geojson)` → `session.add_feature` (canvas_shim.py:680-698; map_tools.py:309-328).
- vertex drag → `commit_vertex_move(feature_id, path, (x,y))` → `session.set_vertex` + `on_vertex_committed` hook (canvas_shim.py:706-743; map_tools.py:440-470).
- move drag → `commit_move(feature_id, dx, dy)` (map_tools.py:379).
- select box/click → `commit_selection(feature_ids, modifiers)` (map_tools.py:178); identify → `native_identified` signal only (canvas_shim.py:759-765).
- Snapping: `SnappingService` (Python authority) pushed via `shim.set_snapping_config` (canvas_shim.py:429-443); grid snapping is Python-only and not pushed. Reference layers join snapping via `reference_enabled` (map_stack_service.cpp:2285-2298).

### 2.3 Capability probe / fallback semantics (exact paths)

1. **Interactive canvas**: `CompositeDocument._create_canvas` (composite_document.py:860-872) — `try: QgisCanvasShim(...)`; ANY exception (including the RuntimeError from `_load_mapstack`) logs and returns `UnifiedMapCanvas(parent), uses_native_stack=False`; layer panel then falls back to `LayerManagerPanel` (composite_document.py:874-878); group controller `mark_fallback` (composite_document.py:833).
2. **Display canvas**: `create_display_canvas` (display_canvas.py:24-30) — ImportError → `UnifiedMapCanvas`.
3. **Offscreen backend**: `create_map_render_backend` (map_render_backend.py:2332-2350) — QGIS only if module imports AND `qgis_backend_probe()` (real `initialize()`) succeeds; otherwise `FallbackMapRenderBackend(threaded=True)` (pure-QPainter pipeline, raster+vector in Python).
4. **Scalar raster QGIS pipeline**: requires bridge + osgeo.gdal; honest RuntimeError otherwise (qgis_style.py:51-69; map_render_backend.py:1793-1805).
5. **Legacy style migration / symbology dialogs**: no-ops / unavailable without the bridge (qgis_style.py:138-145 returns None → legacy dict kept).
6. `qt_platform.py` and `env_bootstrap.py` contain **no QGIS logic** (verified by grep) — availability is decided solely by the import/probe chain above.

---

## 3. LIFECYCLE / PUBLISH

Two distinct publish pipelines:

**A. Native canvas (QgisMapStack mirror)** — `set_layer_snapshot` (canvas_shim.py:805) → `mirror_snapshot_to_stack` (qgis_mirror.py:11):
- **Incremental by layer**: `upsert_mirror_layer` reuses the existing QgsVectorLayer per `doc_id`; unchanged layers keep object identity, tree node, and renderer. Data update = provider truncate + addFeatures (full-feature re-add per layer, map_stack_service.cpp:1473-1487); style reapplied only when the style signature (`renderer_xml \x1e labeling_xml \x1e legacy_json`) changes (makeStyleSig, map_stack_service.cpp:366-377, 1488-1504); geometry-kind drift rebuilds the layer (#1153).
- Removals batched in `remove_mirror_layers_except`; order pushed once (`set_mirror_layer_order`) in flat mode; one `refresh_canvas` at the end (qgis_mirror.py:114-129).
- **No per-feature delta channel on this path**: every snapshot re-ships the full GeoJSON FeatureCollection per layer (the #932 delta channel exists only on the offscreen QgisRenderBridge path). An O(changed) hook would naturally live in `mirror_snapshot_to_stack`/`upsert_mirror_layer` (accept a delta dict mirroring the `VectorLayerSpec::FeatureDelta` wire) and in C++ `upsertMirrorLayer` (apply delete/add by `__pwb_fid` instead of truncate+add).
- Hotspots (full-rectification per publish): per-layer `truncate + addFeatures` of ALL features (map_stack_service.cpp:1476-1485) and `recordMirrorFeatureFids` re-parsing the whole GeoJSON (map_stack_service.cpp:123-151); `syncCanvasLayers` runs over every live canvas after every mutation (cpp:1518-1520 etc.); `applyProjectXml` re-applies styles/placements wholesale on load.

**B. Offscreen render (QgisRenderBridge)** — `QgisMapRenderBackend.set_layer_snapshot` → `_set_native_snapshot` (map_render_backend.py:1841-1863): mirror reuse by data_revision, style-only reapply, and true **incremental feature deltas** (#932) with stale-delta detection + full reship recovery. This is the O(changed) reference implementation.

**C. Layer tree/group reconcile** — `LayerGroupController._apply_tree` computes placement deltas (`_place_delta`) and batches them through `apply_tree_placements` (one canvas sync for N placements, explicitly avoiding the O(N²) of per-node `move_layer_to_group`; map_stack_service.hpp:114-118).

---

## 4. LAYOUT

Present and complete for one-shot export only:

- C++ `QgisMapStack::layoutExport` (map_stack_service.cpp:3306-3566, bound bindings.cpp:796-799): builds a transient `QgsPrintLayout` from the stack's mirrored layers, exports via `QgsLayoutExporter` to **pdf (incl. opt-in GeoPDF, spec `geo_pdf:true`, cpp:3536-3539)**, **svg**, or **png**, then discards the layout ("never a second writable map document"). Page: width_mm/height_mm/background. Item kinds supported today (map_stack_service.cpp:3351-3524):
  - `map` (QgsLayoutItemMap; crs, extent, frame, layers = mirror order reversed, key-addressable `key` for linking; optional `grid` {enabled, interval_x, interval_y, annotation, crs} via QgsLayoutItemMapGrid),
  - `legend` (QgsLayoutItemLegend; title, linked map, resize_to_contents, background),
  - `scalebar` (QgsLayoutItemScaleBar; segments, units_per_segment, unit_label, applyDefaultSettings/Meters),
  - `north_arrow` / `picture` (QgsLayoutItemPicture; svg_path — vendored QGIS ships no arrow SVGs so layout_export.py writes its own needle+N SVG to temp, layout_export.py:47-65),
  - `label` (QgsLayoutItemLabel; text, font_size, bold, color, halign),
  - `shape` (QgsLayoutItemShape rectangle; fill, frame).
  Unknown type → invalid_argument (cpp:3521-3523). Requires an initialized QGIS application (cpp:3310-3314).
- Python connector (Paleo Map Component Graph → layout): `mapping/layout_export.py` — `build_layout_spec` maps composer `ElementType`s onto the spec (MAIN_MAP→map, LEGEND, NORTH_ARROW, SCALE_BAR, TITLE/TEXT/ANNOTATION/DATASOURCE/TIME_CREDITS/STRAT_LABELS/METADATA/SUBTITLE→label, IMAGE→picture, NEATLINE→shape, GRID folded into the map item's grid after paper-mm→map-unit conversion, layout_export.py:74-90, 246-317). `export_composition_reported` (layout_export.py:323-397): **all-or-nothing** — any visible element without a native counterpart (timescale, stat chart, facies/lithology legend tables, colorbar, inset map) raises and the whole page falls back to the existing composer SVG renderer (`engine="composer_fallback"` in the `LayoutExportReport`); pixel budget guard MAX_EXPORT_PIXELS=2e8 (layout_export.py:145-157).
- No interactive QgsLayoutDesigner / no persisted .qgs composition; layout is export-time only.

---

## 5. RASTER

- **Offscreen bridge: YES, but RGBA-only.** `VectorLayerSpec::Kind::Raster` with `source_path` (bindings.cpp:55-58, hpp:47-53) creates `QgsRasterLayer(path, name, "gdal")` (qgis_render_bridge.cpp:382-390). Python ships raster layers in `_qgis_snapshot`: `scalar_grid` layers are pre-colorized by `ScalarRasterMirrorCache` into a georeferenced **4-band RGBA GeoTIFF** (preferably GDAL `/vsimem`, scalar_raster_mirror.py:18-203) and `raster_source` layers pass their file path straight through (map_render_backend.py:2044-2080). Any raster style_revision change forces a full layer rebuild (qgis_render_bridge.cpp:343-346).
- **NO QGIS raster renderers**: no QgsSingleBandPseudoColorRenderer, no QgsColorRampShader, no QgsRasterShader, no colormap/contrast enhancement anywhere in the bridge (grep of all src confirms; the only raster code path is the plain gdal provider open). Pseudocoloring is done in Python before the GeoTIFF mirror; QGIS only composites pre-baked RGBA. To add true single-band pseudocolor: new `renderer` payload for raster in VectorLayerSpec (e.g. `raster_renderer_xml` from QgsRasterRenderer::save), plus QgsRasterLayer::setRenderer + XML round-trip analogous to style_codec, plus wire support in `_qgis_snapshot`/bindings parse_layers, plus (if desired) mapstack mirror support (see next).
- **Native canvas (QgisMapStack): NO raster at all.** `mirror_snapshot_to_stack` skips every non-`vector` layer (`if layer.layer_type != "vector": continue`, qgis_mirror.py:41-42); `upsert_mirror_layer` is vector-only (QgsVectorLayer memory provider; map_stack_service.cpp:1523-1526). Scalar grids / raster reference files therefore do not render on the interactive QGIS canvas (only on the fallback QPainter canvas or the offscreen render path). Adding raster to the interactive canvas would need an `upsert_raster_mirror_layer` (QgsRasterLayer + gdal URI + visibility/opacity/order participation) and qgis_mirror changes.

---

## 6. TESTS

Gating: `tests/qgis_support.py` (`require_qgis`/`require_mapstack` importorskip with actionable reason; `PALEO_REQUIRE_QGIS=1` fail-closed, qgis_support.py:35-58). `tests/conftest.py` auto-skips every `@pytest.mark.qgis` test when the bridge is not built (conftest.py:82-95) and fails closed under PALEO_REQUIRE_QGIS (conftest.py:69-79). Bridge-using files (46):

| File | Coverage (one line) |
|---|---|
| tests/test_qgis_render_bridge.py | Offscreen QgisRenderBridge contract: snapshot/render_sync/async frames, deltas, diagnostics (bridge). |
| tests/test_qgis_authoring_codec.py | renderer XML round-trip + legacy→renderer migration (`legacy_style_to_renderer_xml`, `renderer_info`). |
| tests/test_qgis_rule_renderer.py | Rule-based renderer contract (attribute-driven geological symbology). |
| tests/test_qgis_style_revision.py | Style revision bumping + mirror reuse through the host snapshot path. |
| tests/test_qgis_snapshot_encoding.py | Host-side geometry encoding caches; **runs without the bridge** (marked qgis but pure-Python path). |
| tests/test_qgis_bridge_gil_contract.py | GIL release around render_sync/export_vector (#1031). |
| tests/test_qgis_geometry_service.py | geometry submodule ops contract (union/split/buffer/validity/explode/clip…). |
| tests/test_qgis_geometry_edit_session.py | Geometry ops stay subordinate to VectorEditSession transactions. |
| tests/test_qgis_mapstack_env.py | Vendored QGIS bridge importable on current Python env (hard dependency baseline). |
| tests/test_qgis_mapstack_layers.py | GeoJSON layers mirrored into QgsProject; canvas renders feature pixels. |
| tests/test_qgis_mapstack_lifecycle.py | QgisMapStack init idempotence, QgsProject singleton reach, shutdown. |
| tests/test_qgis_mapstack_reconcile.py | Incremental mirror: unchanged layers keep QgsMapLayer object + tree node. |
| tests/test_qgis_mapstack_style.py | Style persistence across re-mirror (layer-click color change repro). |
| tests/test_qgis_mapstack_tools.py | set_map_tool kinds + extent/xy callback marshaling into Qt signals. |
| tests/test_qgis_canvas_embed.py | QgsMapCanvas address-boundary embedding, white background. |
| tests/test_qgis_layertree_embed.py | QgsLayerTreeView embed; mirrored layers visible in tree. |
| tests/test_qgis_layertree_writeback.py | Tree user ops (check/drag/rename) reach Python; programmatic reconcile does not echo. |
| tests/test_qgis_layer_panel.py | QgisLayerTreePanel drop-in replacement for LayerManagerPanel. |
| tests/test_qgis_layer_panel_menu.py | Tree context-menu custom actions → request signals. |
| tests/test_qgis_layer_properties.py | Native QgsVectorLayerProperties exec + result write-back. |
| tests/test_qgis_layer_groups.py | V5 groups: CRUD/nesting/placements/promotion/XML round-trip/event echo. |
| tests/test_qgis_project_xml.py | write/apply project XML by pwb/doc_id (presentation only, no features). |
| tests/test_qgis_project_xml_persist.py | map_qgis_project_xml persisted in project file; composite save/load wiring. |
| tests/test_qgis_layout_export.py | M7 layout export: component graph → spec → pdf/svg/png + report. |
| tests/test_qgis_digitize_tool.py | Native capture tools digitizingCompleted geometry callback. |
| tests/test_qgis_vertex_move_tools.py | Vertex/move tools: pick + rubber band preview + callback. |
| tests/test_qgis_select_identify.py | Native select/identify tools + selection highlights. |
| tests/test_qgis_snapping_config.py | Snapping config push into C++ snappingUtils and effectiveness. |
| tests/test_qgis_snapping_push.py | SnappingService → QGIS config projection (Python builder half). |
| tests/test_qgis_editing_keyboard.py | Esc semantics when native tool is busy (M3 Task 5). |
| tests/test_qgis_tool_wiring.py | Shim maps host tool activation to native QgsMapTool kinds. |
| tests/test_qgis_canvas_tool_wiring.py | B8 identify/measure/export wiring on-machine. |
| tests/test_qgis_display_canvas.py | QgisDisplayCanvas snapshot mirror, click, factory fallback to UnifiedMapCanvas. |
| tests/test_qgis_display_isolation.py | Display stack uses its own QgsProject (no leakage into authoring singleton). |
| tests/test_composite_qgis_canvas.py | Composite document area hosted by QgsMapCanvas (shim contract). |
| tests/test_qgis_symbology_dialog_bridge.py | Native symbology dialogs (renderer/symbol selector/style manager). |
| tests/test_qgis_visual_regression.py | Visual regression of the QGIS authoring path (small real cartography). |
| tests/test_qgis_screen_export_parity.py | Screen PNG vs vector export share one QGIS renderer config. |
| tests/test_qgis_vendor_source.py | Vendored QGIS source snapshot integrity (UPSTREAM.md pin). |
| tests/test_native_abi_gate.py | On-disk extension build vs sys.path ABI gate (#1181). |
| tests/test_issue_938_native_contract.py | #938 native contract batch regressions (9 sub-items). |
| tests/test_map_render_backend.py | Render-backend seam (fallback + QGIS when built). |
| tests/test_export_parity.py | M11 output engine parity, GeoPDF, metadata honesty. |
| tests/test_unified_map_export.py | Unified renderer export + OUTPUT lineage (QGIS path when built). |
| tests/test_map_layer_properties.py | Layer properties flow (native dialog path when built). |
| tests/test_mapping_page.py | Mapping page embedding (QGIS display path when built). |
| tests/test_home_map_well_click.py / test_home_workarea_map.py | Home work-area map: well click navigation + snapshot producer (display canvas path). |
| tests/test_audit_fix_regressions.py / test_audit_viz_mapping.py | Cross-cutting audit regressions touching the bridge paths. |

Which run without the bridge: all non-`qgis`-marked tests; among the above, `test_qgis_snapshot_encoding.py` is explicitly bridge-free, and `test_map_render_backend.py` / `test_export_parity.py` / `test_unified_map_export.py` etc. exercise the fallback halves — every `@pytest.mark.qgis` item self-skips via conftest.py:82-95 when `qgis_render_bridge` is not importable.

Build/packaging notes: root `pyproject.toml` defines the `qgis-renderer` extra and the `qgis` marker (pyproject.toml:58-66, 112); main CI gate is fallback-only, dedicated `qgis-renderer.yml` workflow builds the bridge. `setup.py` supports `PALEO_QGIS_BUILD_DIR` / `PALEO_QGIS_REUSE_VENDOR` cross-worktree vendor reuse (setup.py:60-113) and links Qt6PrintSupport for QgsLayoutExporter (setup.py:40-41, 270-271). `standalone_test.cpp` is a C++ selftest (QApplication + one polygon render).

---

## Biggest gaps (refactoring-relevant)

1. **Raster absent from the interactive canvas** (qgis_mirror.py:41) and pre-baked-RGBA-only on the offscreen path (no QgsRasterRenderer/QgsColorRampShader anywhere).
2. **No per-feature delta channel on the canvas mirror path** — every publish truncate+re-adds the full FeatureCollection per layer (map_stack_service.cpp:1476-1487); the #932 delta machinery exists only in QgisRenderBridge.
3. **Layout is export-only and all-or-nothing** — many composer elements (timescale, stat charts, legend tables, colorbar, inset map) force `composer_fallback`; no persistent/editable layout.
4. Two parallel mirror registries (QgisMapStack mirrors vs QgisRenderBridge mirrors) with different feature encodings (GeoJSON vs WKT) and different capabilities; export must rebuild through the offscreen bridge (canvas_shim.py:908-943).
5. Monkey-patched tool activation (`set_map_tool` wrapper, canvas_shim.py:619-673) and viewport event-filter routing for measure — brittle seams for any refactor.
