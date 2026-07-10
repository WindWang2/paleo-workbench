# Mapping Editor V1 Design

> **Date:** 2026-07-10  
> **Status:** Approved for planning  
> **Page:** 编图 (`MappingPage`, AppShell index 7)  
> **Related:**  
> - `docs/superpowers/specs/2026-07-05-mappingpage-design.md` (MVP display-only page)  
> - `geo-viz-engine/packages/geoviz_paleo_map` (`PaleoMapCanvas` QPainter viewer)

## Goal

Upgrade the paleogeographic mapping page from a display-only three-panel view into a **saveable vector map editor V1** with:

| Dimension | Decision |
|-----------|----------|
| Layout | Professional GIS shell: top toolbar · left layer tree · center canvas · bottom attribute table (collapsible) |
| Features | Full draft set: facies polygons, wells, lines, annotation boxes |
| Edit depth | Topology-aware: select / move / vertex edit + snap + adjacency / self-intersection warnings |
| Persistence | Write back into `PaleoMapDocument` (including **保存编图草稿**) |
| Engine | `QGraphicsView` / `QGraphicsScene` edit scene — not QGIS, not hard-coded QPainter editing |
| Performance | Hot paths in **C++**, cold paths in Python; no per-vertex Python hot loops |

## Non-Goals (V1)

- QGIS embed or a separate QGIS runtime package
- Full print cartography / multi-page export layout
- Freehand draw of new facies polygons (facies still come from preparation/prediction; V1 edits existing polygons)
- Forced topology rebuild (merge/split/shared-node editing)
- Collaborative editing or network services
- Replacing the data page; mapping only consumes/writes project map documents

## Current Baseline

- `MappingPage`: fixed three columns — `MapDocumentPanel` | `MapCanvasPanel` (`PaleoMapCanvas`) | `MapChromePanel`
- Display-first: `load_features(facies_polygons, wells=…)` only
- `PaleoMapDocument` already has `facies_polygons`, `well_overlays`, `map_chrome`, `view_state`, `edit_history`
- Out of scope in the 2026-07-05 design: polygon tools, topology, undo/redo

## Architecture

```
MappingPage (Python / PySide6)
├── MapEditToolbar
├── content (horizontal)
│   ├── MapLayerTree          # documents + layers, visibility/lock
│   └── MapEditView           # QGraphicsView
│         └── MapEditScene    # items + tool routing
└── MapAttributeTable         # collapsible bottom property grid

map_edit_core (C++ extension, pybind11 preferred)
  hit_test · snap · vertex ops · validate (self-intersection / simple adjacency)

PaleoMapDocument  ←→  load/save adapters (Python)
```

### Role of existing `PaleoMapCanvas`

Keep the QPainter canvas package. V1 editing path is the new scene. Optional later mode: chrome/print preview using `PaleoMapCanvas` on the same document. Editing must not depend on painter hit-testing.

### C++ / Python split

| C++ (`map_edit_core`) | Python |
|------------------------|--------|
| Hit-test / box-select candidates | GIS shell widgets, tool exclusivity |
| Vertex drag geometry, snap candidates | Cursor, status bar, dirty flag UI |
| Self-intersection / simple adjacency (GEOS or equivalent) | `PaleoMapDocument` mapping, project dirty |
| Spatial index (grid or R-tree) | Command orchestration for undo (or thin wrap over C++ stack) |
| Batch translate | AppShell sidebar context, save entry points |

**Boundary rule:** Cross the language bridge with **feature id + compact coordinate buffers**, not per-vertex Python callbacks.

**Progressive strategy:** Python can implement the same façade first for correctness; C++ drops in behind identical APIs without rewriting UI tests’ behavioral intent.

## Layout

```
┌─ MapEditToolbar ──────────────────────────────────────────────────┐
│ Select | Move | Vertex | Line | Label | Snap | Undo/Redo | 保存草稿 │
├────────────┬──────────────────────────────────────────────────────┤
│ MapLayer   │  MapEditView + MapEditScene                          │
│ Tree       │  (primary work surface)                              │
│ ~240px     │                                                      │
│ collapsible│                                                      │
├────────────┴──────────────────────────────────────────────────────┤
│ MapAttributeTable (~160px default, collapsible)                   │
│ id · type · name/text · geometry summary · topology status        │
└───────────────────────────────────────────────────────────────────┘
```

### Component responsibilities

| Component | Responsibility |
|-----------|----------------|
| `MapEditToolbar` | Exclusive tools; snap toggle; save draft; undo/redo |
| `MapLayerTree` | Map document switch; layer visibility/lock; absorbs list role of `MapDocumentPanel` |
| `MapEditView` / `MapEditScene` | Vector edit surface; selection; item z-order |
| `MapAttributeTable` | Selected feature properties; editable text fields (facies name, label text, …) |
| `MapChromePanel` | Not a permanent right column in V1; chrome toggles may live under layers or a later preview mode |

### Interaction rules

- Left and bottom panes collapse so the canvas can dominate.
- Layer checkbox ↔ item `setVisible`; lock ↔ not selectable/movable.
- Scene selection ↔ attribute table row (bidirectional; use signal blockers / generation to avoid loops).
- AppShell sidebar shows active map name, horizon, and dirty state.

## Document and geometry model

`PaleoMapDocument` remains the project source of truth.

| Field | V1 use |
|-------|--------|
| `facies_polygons[]` | Polygons: `id`, facies/name, ring coordinates, style |
| `well_overlays[]` | Wells: `id`, name, point coordinates |
| `line_features[]` | **New convention**: faults/boundaries LineString |
| `label_features[]` | **New convention**: annotation boxes with text + anchor/bbox |
| `map_chrome` | Chrome flags (read-only or light toggle in V1) |
| `view_state` | Zoom/center restore |
| `edit_history` | Optional summaries; runtime undo stack may be separate |

Feature ids: stable `feat_*` or existing ids; shared between Python scene and C++ core.

**Load:** document → normalize planar geometry (same CRS assumptions as current canvas) → scene items.  
**Save draft:** scene → lists on the active `PaleoMapDocument` in `project.paleomap_documents` → clear dirty. Whether that immediately writes `.paleo.json` follows the window-level project save policy; mapping page at least updates the in-memory project document.

## Editing tools

| Tool | Behavior |
|------|----------|
| Select | Click / rubber-band; Shift multi-select |
| Move | Translate selection |
| Vertex | Handles; drag vertex; double-click edge to insert; Delete vertex (min 3 poly / 2 line) |
| Draw line | Click to add vertices; double-click/Enter finish → `line_features` |
| Label | Click to place annotation; edit text in attribute table |
| Pan/zoom canvas | Middle button or space+drag; wheel zoom — no geometry change |
| Snap | Toggle: vertices/endpoints; tolerance in screen pixels → map units |

- New facies polygons by freehand drawing are **out of scope** for V1.
- Delete key removes selection (undoable).

## Topology

| Check | When | UX |
|-------|------|-----|
| Self-intersection | After vertex edit commit / before save | Mark feature; attribute “拓扑: 警告” |
| Simple adjacency gap/overlap | Before save (optional debounced after edit) | Issue list in status or table |
| Degenerate geometry | Live | Block invalid end state or revert last vertex |

V1 does **not** force topology rebuild. Warnings **do not block save by default** (optional strict mode later).

## Dirty state and undo

- Any successful edit marks the active document dirty; toolbar reflects unsaved state.
- Command pattern: Move, VertexEdit, Create, Delete, PropertyChange; stack depth capped (e.g. 50).
- Topology warnings do not auto-rollback unless the user cancels the gesture.

## Error handling

| Case | Behavior |
|------|----------|
| No active map document | Empty canvas; edit tools disabled |
| Bad geometry on load | Skip feature; status count of load failures |
| Save failure | Keep dirty; surface error; do not drop edits |
| C++ extension missing | Fall back to Python façade; log once (CI may require C++ later) |

## Testing

| Level | Coverage |
|-------|----------|
| Unit | Geometry commands; validate fixtures; load/save round-trip |
| Widget | Tool switching; layer visibility/lock; attribute sync; dirty flag |
| Integration | GIS shell assembly; `update_state`; save into `paleomap_documents` |
| Perf (optional) | Large vertex hit-test stays off Python loops on C++ path |

Use `QT_QPA_PLATFORM=offscreen`. Scene tests need not load map textures.

## Delivery slices (PR order)

1. GIS shell (toolbar, layer tree, attribute table, empty view)  
2. Read-only scene load (facies + wells)  
3. Select + move + undo  
4. Vertex edit  
5. Lines + labels  
6. Snap + topology warnings  
7. Save draft → `PaleoMapDocument`  
8. C++ sink for hit-test / snap / validate (API-aligned with earlier slices)

## Success criteria

- GIS layout usable with collapsible side/bottom panes and canvas as the primary surface  
- All four feature kinds selectable and editable at topology-warning depth  
- Save + reload preserves geometry in the project document  
- Hot interaction paths do not depend on Python per-vertex loops once C++ is enabled  

## Open implementation notes (not product questions)

- Extension home: prefer a small package under `geo-viz-engine` or `paleo_workbench` with pybind11  
- Whether undo stack lives in C++ or Python is an implementation choice if command semantics match tests  
- Exact GeoJSON-like dict keys for new line/label lists should be fixed in the implementation plan with fixtures  
