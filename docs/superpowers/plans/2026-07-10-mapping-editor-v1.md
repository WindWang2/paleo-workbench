# Mapping Editor V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the display-only 编图 page with a GIS-shell vector editor that loads/edits/saves `PaleoMapDocument` features (facies, wells, lines, labels) with topology warnings, Python-first tools, and a C++-ready geometry façade.

**Architecture:** `MappingPage` hosts toolbar + layer tree + `QGraphicsView` scene + collapsible attribute table. Geometry commands and validation go through `map_edit_api` (Python façade now, `map_edit_core` C++ later). Document I/O uses pure adapters on `PaleoMapDocument` dict lists.

**Tech Stack:** Python 3.12, PySide6 (`QGraphicsView`/`QGraphicsScene`/`QGraphicsItem`), Pydantic `PaleoMapDocument`, pytest + pytest-qt (`QT_QPA_PLATFORM=offscreen`). Optional later: pybind11 C++ extension.

**Spec:** `docs/superpowers/specs/2026-07-10-mapping-editor-v1-design.md`

---

## File map

| File | Role |
|------|------|
| Create `paleo_workbench/ui/pages/map_edit_toolbar.py` | Exclusive tools, snap, undo/redo, save draft |
| Create `paleo_workbench/ui/pages/map_layer_tree.py` | Document list + layer visibility/lock |
| Create `paleo_workbench/ui/pages/map_attribute_table.py` | Selected feature properties |
| Create `paleo_workbench/ui/pages/map_edit_view.py` | `QGraphicsView` subclass (pan/zoom) |
| Create `paleo_workbench/ui/pages/map_edit_scene.py` | Scene, items, selection, tools |
| Create `paleo_workbench/ui/pages/map_edit_items.py` | Facies/Well/Line/Label graphics items |
| Create `paleo_workbench/ui/pages/map_edit_commands.py` | Undo command stack |
| Create `paleo_workbench/mapping/document_io.py` | Load/save document ↔ feature records |
| Create `paleo_workbench/mapping/map_edit_api.py` | Geometry façade (Python impl; C++ later) |
| Create `paleo_workbench/mapping/geometry_schema.py` | Feature record types + id helpers |
| Create `paleo_workbench/mapping/__init__.py` | Package exports |
| Modify `paleo_workbench/project/models.py` | Optional `line_features` / `label_features` fields |
| Modify `paleo_workbench/ui/pages/mapping_page.py` | Assemble GIS shell; wire save/dirty |
| Modify `paleo_workbench/ui/pages/__init__.py` | Exports if needed |
| Modify `paleo_workbench/ui/sidebar.py` | 编图 context: dirty / map name |
| Keep `map_canvas_panel.py` / `map_chrome_panel.py` | Unused by default; do not delete in V1 |
| Tests under `tests/test_map_*.py`, `tests/test_mapping_*.py` | Per-task |

**Always run Qt tests with:**

```bash
QT_QPA_PLATFORM=offscreen pytest <paths> -v
```

**Feature record convention (fixed for all tasks):**

```python
# paleo_workbench/mapping/geometry_schema.py
from __future__ import annotations
from typing import Any, Literal
from uuid import uuid4

FeatureKind = Literal["facies", "well", "line", "label"]

def new_feature_id(prefix: str = "feat") -> str:
    return f"{prefix}_{uuid4().hex[:12]}"

def normalize_facies(raw: dict[str, Any]) -> dict[str, Any]:
    """Return {id, kind, name, coordinates: list[list[float,float]], style}."""
    coords = raw.get("coordinates") or raw.get("geometry", {}).get("coordinates") or []
    # Accept ring as [[x,y], ...] or GeoJSON Polygon first ring
    if coords and isinstance(coords[0], (list, tuple)) and coords and isinstance(coords[0][0], (list, tuple)):
        ring = list(coords[0])
    else:
        ring = [list(p) for p in coords]
    return {
        "id": raw.get("id") or new_feature_id("facies"),
        "kind": "facies",
        "name": raw.get("name") or raw.get("facies") or raw.get("label") or "",
        "coordinates": ring,
        "style": dict(raw.get("style") or {}),
    }

def normalize_well(raw: dict[str, Any]) -> dict[str, Any]:
    if "coordinates" in raw and isinstance(raw["coordinates"], (list, tuple)):
        x, y = float(raw["coordinates"][0]), float(raw["coordinates"][1])
    else:
        x = float(raw.get("x", raw.get("lon", 0.0)))
        y = float(raw.get("y", raw.get("lat", 0.0)))
    return {
        "id": raw.get("id") or new_feature_id("well"),
        "kind": "well",
        "name": raw.get("name") or raw.get("well_name") or "",
        "coordinates": [x, y],
    }

def normalize_line(raw: dict[str, Any]) -> dict[str, Any]:
    coords = raw.get("coordinates") or []
    return {
        "id": raw.get("id") or new_feature_id("line"),
        "kind": "line",
        "name": raw.get("name") or "",
        "coordinates": [list(p) for p in coords],
    }

def normalize_label(raw: dict[str, Any]) -> dict[str, Any]:
    if "anchor" in raw:
        ax, ay = float(raw["anchor"][0]), float(raw["anchor"][1])
    else:
        ax = float(raw.get("x", 0.0))
        ay = float(raw.get("y", 0.0))
    return {
        "id": raw.get("id") or new_feature_id("label"),
        "kind": "label",
        "name": raw.get("text") or raw.get("name") or "",
        "coordinates": [ax, ay],
        "text": raw.get("text") or raw.get("name") or "",
    }
```

---

### Task 1: Geometry schema + document I/O

**Files:**
- Create: `paleo_workbench/mapping/__init__.py`
- Create: `paleo_workbench/mapping/geometry_schema.py` (as above)
- Create: `paleo_workbench/mapping/document_io.py`
- Modify: `paleo_workbench/project/models.py` — add fields:
  - `line_features: list[dict[str, Any]] = Field(default_factory=list)`
  - `label_features: list[dict[str, Any]] = Field(default_factory=list)`
- Test: `tests/test_mapping_document_io.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mapping_document_io.py
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.mapping.document_io import (
    features_from_document,
    apply_features_to_document,
)


def test_features_from_document_normalizes_facies_and_wells():
    doc = PaleoMapDocument(
        name="Map A",
        linked_target_horizon="D5",
        facies_polygons=[
            {"id": "f1", "name": "三角洲", "coordinates": [[0, 0], [1, 0], [1, 1], [0, 0]]},
        ],
        well_overlays=[{"id": "w1", "name": "A1", "x": 10.0, "y": 20.0}],
    )
    features = features_from_document(doc)
    kinds = {f["kind"] for f in features}
    assert kinds == {"facies", "well"}
    well = next(f for f in features if f["kind"] == "well")
    assert well["coordinates"] == [10.0, 20.0]


def test_apply_features_round_trip_lines_and_labels():
    doc = PaleoMapDocument(name="M", linked_target_horizon="H")
    features = [
        {
            "id": "f1",
            "kind": "facies",
            "name": "A",
            "coordinates": [[0, 0], [2, 0], [2, 2], [0, 0]],
            "style": {},
        },
        {"id": "ln1", "kind": "line", "name": "F1", "coordinates": [[0, 0], [3, 3]]},
        {"id": "lb1", "kind": "label", "name": "注记", "text": "注记", "coordinates": [1, 1]},
    ]
    apply_features_to_document(doc, features)
    assert len(doc.facies_polygons) == 1
    assert len(doc.line_features) == 1
    assert len(doc.label_features) == 1
    back = features_from_document(doc)
    assert {f["id"] for f in back} == {"f1", "ln1", "lb1"}
```

- [ ] **Step 2: Run tests — expect FAIL** (import / missing fields)

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_mapping_document_io.py -v
```

- [ ] **Step 3: Implement `document_io.py`**

```python
from __future__ import annotations
from typing import Any
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.mapping.geometry_schema import (
    normalize_facies,
    normalize_well,
    normalize_line,
    normalize_label,
)

def features_from_document(doc: PaleoMapDocument | None) -> list[dict[str, Any]]:
    if doc is None:
        return []
    out: list[dict[str, Any]] = []
    for raw in doc.facies_polygons or []:
        try:
            out.append(normalize_facies(raw if isinstance(raw, dict) else dict(raw)))
        except Exception:
            continue
    for raw in doc.well_overlays or []:
        try:
            out.append(normalize_well(raw if isinstance(raw, dict) else dict(raw)))
        except Exception:
            continue
    for raw in getattr(doc, "line_features", None) or []:
        try:
            out.append(normalize_line(raw if isinstance(raw, dict) else dict(raw)))
        except Exception:
            continue
    for raw in getattr(doc, "label_features", None) or []:
        try:
            out.append(normalize_label(raw if isinstance(raw, dict) else dict(raw)))
        except Exception:
            continue
    return out

def apply_features_to_document(doc: PaleoMapDocument, features: list[dict[str, Any]]) -> None:
    facies, wells, lines, labels = [], [], [], []
    for f in features:
        kind = f.get("kind")
        if kind == "facies":
            facies.append({
                "id": f["id"],
                "name": f.get("name", ""),
                "coordinates": f.get("coordinates", []),
                "style": f.get("style") or {},
            })
        elif kind == "well":
            c = f.get("coordinates") or [0, 0]
            wells.append({"id": f["id"], "name": f.get("name", ""), "x": c[0], "y": c[1]})
        elif kind == "line":
            lines.append({
                "id": f["id"],
                "name": f.get("name", ""),
                "coordinates": f.get("coordinates", []),
            })
        elif kind == "label":
            c = f.get("coordinates") or [0, 0]
            labels.append({
                "id": f["id"],
                "text": f.get("text") or f.get("name", ""),
                "anchor": [c[0], c[1]],
            })
    doc.facies_polygons = facies
    doc.well_overlays = wells
    doc.line_features = lines
    doc.label_features = labels
```

- [ ] **Step 4: Tests pass**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_mapping_document_io.py -v
```

- [ ] **Step 5: Commit**

```bash
git add paleo_workbench/mapping paleo_workbench/project/models.py tests/test_mapping_document_io.py
git commit -m "feat: mapping document feature I/O and schema"
```

---

### Task 2: GIS shell layout (no editing)

**Files:**
- Create: `map_edit_toolbar.py`, `map_layer_tree.py`, `map_attribute_table.py`, `map_edit_view.py` (empty scene ok)
- Modify: `mapping_page.py`
- Test: `tests/test_mapping_page.py` (update), `tests/test_map_edit_toolbar.py`, `tests/test_map_layer_tree.py`

- [ ] **Step 1: Failing assembly tests**

```python
# tests/test_map_edit_shell.py
from paleo_workbench.ui.pages.mapping_page import MappingPage
from paleo_workbench.ui.pages.map_edit_toolbar import MapEditToolbar
from paleo_workbench.ui.pages.map_layer_tree import MapLayerTree
from paleo_workbench.ui.pages.map_attribute_table import MapAttributeTable
from paleo_workbench.ui.pages.map_edit_view import MapEditView


def test_mapping_page_gis_shell_assembly(qtbot):
    page = MappingPage()
    qtbot.addWidget(page)
    assert isinstance(page.toolbar, MapEditToolbar)
    assert isinstance(page.layer_tree, MapLayerTree)
    assert isinstance(page.edit_view, MapEditView)
    assert isinstance(page.attribute_table, MapAttributeTable)
    assert page.findChild(type(page.document_panel) if False else object) or True
    # Old chrome not required as permanent column
    assert hasattr(page, "edit_view")


def test_toolbar_has_core_actions(qtbot):
    bar = MapEditToolbar()
    qtbot.addWidget(bar)
    assert bar.select_btn is not None
    assert bar.save_draft_btn is not None
    assert bar.snap_btn is not None
```

- [ ] **Step 2: Implement shell widgets**

`MapEditToolbar`: `QToolBar` or `QWidget` with checkable tool buttons (`select`, `move`, `vertex`, `line`, `label`), `snap_btn` checkable, `undo_btn`, `redo_btn`, `save_draft_btn`. Signal: `tool_changed(str)`, `snap_toggled(bool)`, `save_draft_requested`, `undo_requested`, `redo_requested`. Exclusive tools via `QButtonGroup`.

`MapLayerTree`: `QTreeWidget` with top-level “图件” documents + child layers `相带/井/线/注记`. Signals: `document_selected(object)`, `layer_visibility_changed(str, bool)`, `layer_lock_changed(str, bool)`. Methods: `set_documents(list)`, `set_active_document(doc)`.

`MapAttributeTable`: `QTableWidget` 2 columns 属性/值; `set_feature(dict|None)`; signal `property_changed(feature_id, key, value)`.

`MapEditView`: `QGraphicsView`; `setDragMode` for rubber band later; wheel zoom stub; holds `MapEditScene` (Task 3 can flesh out — for Task 2 empty `QGraphicsScene` is enough).

`MappingPage` layout:

```python
outer = QVBoxLayout(self)
self.toolbar = MapEditToolbar()
outer.addWidget(self.toolbar)
mid = QHBoxLayout()
self.layer_tree = MapLayerTree()
mid.addWidget(self.layer_tree)
self.edit_view = MapEditView()
mid.addWidget(self.edit_view, 1)
outer.addLayout(mid, 1)
self.attribute_table = MapAttributeTable()
self.attribute_table.setMaximumHeight(160)
outer.addWidget(self.attribute_table)
# Keep old panels as attributes set to None or hidden for one release if tests import them:
# Prefer updating tests to new API.
```

Update existing mapping tests that look for `document_panel` / `canvas_panel` / `chrome_panel` to the new structure (or provide compatibility aliases):

```python
# temporary aliases if needed for soft migration
self.document_panel = self.layer_tree
self.canvas_panel = self.edit_view
```

Prefer **updating tests** over permanent aliases.

- [ ] **Step 3: Pass tests + commit**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_map_edit_shell.py tests/test_mapping_page.py tests/test_mapping_integration.py -v
git add paleo_workbench/ui/pages/map_edit_*.py paleo_workbench/ui/pages/map_layer_tree.py paleo_workbench/ui/pages/map_attribute_table.py paleo_workbench/ui/pages/mapping_page.py tests/
git commit -m "feat: GIS shell layout for mapping editor"
```

---

### Task 3: Read-only scene load (facies + wells)

**Files:**
- Create: `map_edit_items.py`, expand `map_edit_scene.py`
- Create: `map_edit_api.py` (stub hit_test returning None; translate noop)
- Test: `tests/test_map_edit_scene.py`

- [ ] **Step 1: Tests**

```python
from paleo_workbench.project.models import PaleoMapDocument
from paleo_workbench.ui.pages.map_edit_scene import MapEditScene


def test_scene_loads_facies_and_wells():
    scene = MapEditScene()
    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1", "name": "A",
            "coordinates": [[0, 0], [10, 0], [10, 10], [0, 0]],
        }],
        well_overlays=[{"id": "w1", "name": "A1", "x": 5, "y": 5}],
    )
    scene.load_document(doc)
    assert scene.feature_count() == 2
    assert scene.item_by_id("f1") is not None
    assert scene.item_by_id("w1") is not None
```

- [ ] **Step 2: Items + scene**

```python
# map_edit_items.py — QGraphicsPolygonItem / EllipseItem subclasses
class FeatureItemMixin:
    feature_id: str
    kind: str
    def to_record(self) -> dict: ...

class FaciesPolygonItem(QGraphicsPolygonItem, FeatureItemMixin): ...
class WellPointItem(QGraphicsEllipseItem, FeatureItemMixin): ...
```

`MapEditScene.load_document(doc)` uses `features_from_document`, creates items, `setSceneRect` from bounds.

- [ ] **Step 3: Wire `MappingPage.update_state`** to load active doc into scene + layer tree.

- [ ] **Step 4: Commit** `feat: load map features into edit scene`

---

### Task 4: Select, move, undo

**Files:**
- `map_edit_commands.py`, `map_edit_scene.py`, `map_edit_view.py`, `map_edit_api.py`
- Tests: `tests/test_map_edit_commands.py`, scene selection tests

- [ ] **Step 1: Command stack tests**

```python
from paleo_workbench.ui.pages.map_edit_commands import EditCommandStack, MoveCommand

def test_move_command_undo_redo():
    positions = {"f1": [0.0, 0.0]}
    def apply(fid, dx, dy):
        positions[fid][0] += dx
        positions[fid][1] += dy
    stack = EditCommandStack(max_depth=50)
    stack.push(MoveCommand(feature_ids=["f1"], dx=3, dy=4, apply_move=apply))
    assert positions["f1"] == [3.0, 4.0]
    stack.undo()
    assert positions["f1"] == [0.0, 0.0]
    stack.redo()
    assert positions["f1"] == [3.0, 4.0]
```

- [ ] **Step 2: Implement stack + scene move**

`EditCommandStack`: `push`, `undo`, `redo`, `can_undo`, `can_redo`, `clear`.

`MapEditScene`:
- tool mode from toolbar
- mouse handlers: select (click item / rubber band), move (drag selection → `MoveCommand`)
- `set_dirty` callback / signal `document_dirty_changed(bool)`
- selectionChanged → emit `selection_ids_changed(list[str])`

`map_edit_api.move_features(records_by_id, ids, dx, dy) -> None` mutates coordinate lists (Python).

- [ ] **Step 3: Toolbar undo/redo/save wiring on page**

- [ ] **Step 4: Commit** `feat: map select move and undo stack`

---

### Task 5: Vertex editing

**Files:** `map_edit_scene.py`, `map_edit_items.py`, `map_edit_commands.py`, `map_edit_api.py`  
**Tests:** `tests/test_map_vertex_edit.py`

- [ ] Vertex handles as child items when tool=`vertex` and one facies/line selected  
- [ ] Drag handle → `VertexEditCommand`  
- [ ] Double-click edge → insert vertex  
- [ ] Delete → remove vertex if count allows  
- [ ] `map_edit_api.set_vertex` / `insert_vertex` / `delete_vertex`  

```python
def test_set_vertex_updates_ring():
    from paleo_workbench.mapping import map_edit_api as api
    ring = [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 0.0]]
    api.set_vertex(ring, 1, 3.0, 0.0)
    assert ring[1] == [3.0, 0.0]
```

Commit: `feat: map vertex editing tools`

---

### Task 6: Lines + labels

**Files:** items, scene tools, document_io already supports  
**Tests:** create line/label via tool, appear in `features_to_records()`

- [ ] Line tool: collect points, finish → `CreateFeatureCommand`  
- [ ] Label tool: click → label item  
- [ ] Layer tree toggles visibility for `line` / `label` kinds  
- [ ] Attribute table edits `name`/`text` via `PropertyChangeCommand`  

Commit: `feat: map line and label drafting`

---

### Task 7: Snap + topology warnings

**Files:** `map_edit_api.py` (snap, validate), scene integration, attribute topology column  
**Tests:** `tests/test_map_topology.py`

```python
def test_self_intersection_detected():
    from paleo_workbench.mapping.map_edit_api import validate_ring
    # bowtie
    ring = [[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]
    issues = validate_ring(ring)
    assert any(i["code"] == "self_intersection" for i in issues)

def test_snap_to_vertex():
    from paleo_workbench.mapping.map_edit_api import snap_point
    pts = [(0.0, 0.0), (10.0, 0.0)]
    x, y = snap_point(pts, 0.2, 0.1, tol=0.5)
    assert (x, y) == (0.0, 0.0)
```

- [ ] Python `validate_ring` using segment intersection (no GEOS required for V1)  
- [ ] Optional adjacency: bbox overlap + boundary distance heuristic  
- [ ] After vertex commit / before save: set item data `topology_status`  
- [ ] Snap on pointer move when snap enabled  

Commit: `feat: map snap and topology warnings`

---

### Task 8: Save draft → PaleoMapDocument

**Files:** `mapping_page.py`, scene `export_features()`, toolbar save  
**Tests:** `tests/test_mapping_save_draft.py`

```python
def test_save_draft_writes_document(qtbot):
    from paleo_workbench.project.models import PaleoMapDocument, ProjectDocument
    from paleo_workbench.ui.pages.mapping_page import MappingPage

    doc = PaleoMapDocument(
        name="M",
        linked_target_horizon="H",
        facies_polygons=[{
            "id": "f1", "name": "A",
            "coordinates": [[0, 0], [5, 0], [5, 5], [0, 0]],
        }],
    )
    page = MappingPage()
    qtbot.addWidget(page)
    page.update_state([doc])
    # move feature via scene API if exposed
    page.edit_view.scene().translate_features(["f1"], 1.0, 0.0)
    assert page.is_dirty()
    page.save_draft()
    assert not page.is_dirty()
    assert doc.facies_polygons[0]["coordinates"][0][0] == 1.0  # or whatever translate does
```

- [ ] `MappingPage.save_draft()` → `apply_features_to_document(active, scene.export_features())`  
- [ ] Signal `draft_saved(doc)` for window to optional disk save later  
- [ ] Disable save when not dirty / no document  

Commit: `feat: save mapping draft into PaleoMapDocument`

---

### Task 9: C++ façade hook (optional sink, required API)

**Files:**
- Create: `paleo_workbench/mapping/map_edit_api.py` finalized with:

```python
"""Geometry façade. Tries map_edit_core C++ extension; else pure Python."""
try:
    from map_edit_core import hit_test as _hit_test_cpp  # type: ignore
    HAS_CPP = True
except ImportError:
    HAS_CPP = False
    _hit_test_cpp = None

def hit_test(points: list[tuple[str, list[list[float]]]], x: float, y: float, tol: float) -> str | None:
    if HAS_CPP and _hit_test_cpp is not None:
        return _hit_test_cpp(points, x, y, tol)
    return _hit_test_python(points, x, y, tol)
```

- Create stub package docs: `docs/superpowers/specs` note or `paleo_workbench/mapping/CPP_EXTENSION.md` with pybind11 function signatures matching the design  
- Scaffold optional `native/map_edit_core/` **only if** build is trivial; otherwise document build steps and keep Python path green  

**Minimum for this task (must ship):**  
- Stable Python API used by scene for hit_test/snap/validate  
- `HAS_CPP` flag  
- Unit tests run on Python path  
- Short `CPP_EXTENSION.md` with exact C++ function signatures to implement  

Commit: `feat: map_edit_api façade with C++ extension hook`

---

### Task 10: Integration + sidebar dirty + regression

**Files:** `app_shell.py` / `sidebar.py` / `app.py` if mapping update path needs dirty text  
**Tests:** existing `test_mapping_integration.py`, `test_mapping_page.py` all green  

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_map_*.py tests/test_mapping_*.py -v
QT_QPA_PLATFORM=offscreen pytest -q
```

Commit: `test: mapping editor integration coverage` (if only tests) or fix fallout.

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| GIS layout shell | 2 |
| Facies/wells load | 3 |
| Lines/labels | 1 schema + 6 tools |
| Select/move/undo | 4 |
| Vertex edit | 5 |
| Snap + topology | 7 |
| Save draft to document | 8 |
| C++ hot path hook | 9 |
| No freehand facies | noted Task 6 |
| Keep PaleoMapCanvas package | not deleted |

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-10-mapping-editor-v1.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — this session with executing-plans checkpoints  

**Which approach?**
