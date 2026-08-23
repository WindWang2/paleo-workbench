# 编图工作台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a project-CRS-normalized, GDAL-backed mapping workbench with reference layers, synchronized single-factor views, actionable topology feedback, and responsive editing for complex geometries.

**Architecture:** Preserve `MapEditView`/`MapEditScene` as the editable source of truth. Add a GDAL reference-layer service and persist descriptors on `PaleoMapDocument`; compose reference and factor-map viewers around the same scene/view transform. Put expensive import, render-cache, and topology work behind generation-tagged background jobs; keep edit/save coordinates unmodified.

**Tech Stack:** CPython 3.12, PySide6, GDAL (`osgeo.gdal`, `osgeo.ogr`, `osgeo.osr`), rasterio, Shapely, optional `map_edit_core` pybind11 extension, pytest + pytest-qt.

## Global Constraints

- `ProjectDocument.coordinate.project_crs` is the only editing CRS; data without a usable CRS or transformation path must not enter the workbench.
- Raster references are display-only; vector references may opt into snap candidates but remain non-editable.
- Preserve original coordinates for edit commands and document saves. Level-of-detail is display-only.
- Retain Python fallback behavior when `map_edit_core` is not built.
- Use `QT_QPA_PLATFORM=offscreen` for every Qt test command.
- Keep all blocking GDAL I/O, overview building, and bulk topology validation off the Qt UI thread.

---

## File map

| File | Responsibility |
|---|---|
| Modify `pyproject.toml` | Declare GDAL as a required runtime dependency alongside rasterio. |
| Modify `paleo_workbench/project/models.py` | Add persisted `MapReferenceLayer` descriptors to `PaleoMapDocument`. |
| Create `paleo_workbench/mapping/reference_layers.py` | CRS validation, GDAL import, normalized metadata, display cache keys, vector snap coordinates. |
| Create `paleo_workbench/ui/pages/map_reference_panel.py` | Right dock: reference list, visibility, opacity, overlay selection. |
| Create `paleo_workbench/ui/pages/map_factor_shelf.py` | Bottom factor cards, active factor display, synchronized extent/cursor. |
| Create `paleo_workbench/ui/pages/map_topology_issue_panel.py` | Bottom topology issue table and location signal. |
| Create `paleo_workbench/ui/pages/map_workbench_bottom.py` | Collapsible `QTabWidget` combining attributes, issues, and factor shelf. |
| Modify `paleo_workbench/ui/pages/map_edit_view.py` | View-state signals, navigation-only LOD state, synchronized external view application. |
| Modify `paleo_workbench/ui/pages/map_edit_scene.py` | Reference snap candidates, indexed candidate façade, structured topology issue signal, generation-aware refresh. |
| Modify `paleo_workbench/ui/pages/map_layer_tree.py` | Show reference layers separately from editable layers. |
| Modify `paleo_workbench/ui/pages/mapping_page.py` | Assemble balanced splitter layout; bind documents, references, factors, topology, save validity, and canvas-priority mode. |
| Modify `paleo_workbench/mapping/document_io.py` | Round-trip reference layer descriptors without mixing them into editable features. |
| Modify `paleo_workbench/mapping/map_edit_api.py` and `native/map_edit_core/src/map_edit_core.cpp` | Add spatial-index-compatible snap query façade, preserving Python fallback. |
| Modify `paleo_workbench/ui/tokens.py` | Dock, factor-card, issue-severity, and coordinate-linked state QSS. |
| Create `tests/test_reference_layers.py` | CRS import/normalization/cache-key tests using local GDAL fixtures. |
| Create `tests/test_map_workbench_panels.py` | Dock, factor shelf, topology issue, and view-sync widget tests. |
| Modify `tests/test_mapping_page.py`, `tests/test_mapping_save_draft.py`, `tests/test_map_topology.py`, `tests/test_map_edit_scene.py` | Integration, persistence, invalid-save, and large-candidate regression coverage. |

## Task 1: Persisted reference-layer contract and GDAL adapter

**Files:**
- Modify: `pyproject.toml`, `paleo_workbench/project/models.py`, `paleo_workbench/mapping/document_io.py`, `paleo_workbench/mapping/__init__.py`
- Create: `paleo_workbench/mapping/reference_layers.py`
- Test: `tests/test_reference_layers.py`, `tests/test_mapping_save_draft.py`

**Interfaces:**

```python
class MapReferenceLayer(BaseModel):
    id: str
    name: str
    source_path: str
    source_kind: Literal["raster", "vector"]
    source_crs: str
    project_crs: str
    transform_wkt: str = ""
    visible: bool = True
    opacity: float = 0.65
    order: int = 0
    participates_in_snap: bool = False
    cache_key: str = ""
    status: Literal["ready", "offline", "failed"] = "ready"
    error_message: str = ""

class ReferenceLayerService:
    def import_layer(self, path: Path, project_crs: str) -> MapReferenceLayer: ...
    def vector_snap_points(self, layer: MapReferenceLayer) -> list[tuple[float, float]]: ...
    def raster_overview(self, layer: MapReferenceLayer, extent: tuple[float, float, float, float], size: QSize) -> QImage: ...
```

- [ ] **Step 1: Write failing tests** for a GeoJSON point/line fixture imported into `EPSG:3857`, a GeoTIFF fixture importing with its geotransform, rejection of missing CRS, and `PaleoMapDocument` JSON round-trip of `reference_layers`.

```python
def test_vector_layer_is_reprojected_to_project_crs(tmp_path):
    source = write_geojson(tmp_path / "faults.geojson", crs="EPSG:4326")
    layer = ReferenceLayerService().import_layer(source, "EPSG:3857")
    assert layer.source_kind == "vector"
    assert layer.project_crs == "EPSG:3857"
    assert layer.status == "ready"
    assert ReferenceLayerService().vector_snap_points(layer)[0][0] > 1_000_000

def test_missing_crs_is_rejected(tmp_path):
    with pytest.raises(ReferenceLayerError, match="坐标"):
        ReferenceLayerService().import_layer(write_unreferenced_geojson(tmp_path), "EPSG:3857")
```

- [ ] **Step 2: Run the focused tests and verify RED.**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_reference_layers.py tests/test_mapping_save_draft.py -v
```

- [ ] **Step 3: Implement the model and service.** Use `gdal.OpenEx` with `OF_RASTER | OF_VECTOR`, reject a missing `GetSpatialRef()`/layer SRS, use `osr.CoordinateTransformation` for vector coordinates, and compute `cache_key` from source path, source modification time, source CRS, project CRS, and display mode. Clamp `opacity` to `[0.0, 1.0]`; force `participates_in_snap=False` for rasters.

- [ ] **Step 4: Extend `PaleoMapDocument` with `reference_layers: list[MapReferenceLayer] = Field(default_factory=list)` and export it from `paleo_workbench.project`/`mapping` where current public model conventions require. Keep `document_io` feature-only.**

- [ ] **Step 5: Re-run focused tests and commit.**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_reference_layers.py tests/test_mapping_save_draft.py -v
git add pyproject.toml paleo_workbench/project/models.py paleo_workbench/mapping tests/test_reference_layers.py tests/test_mapping_save_draft.py
git commit -m "feat: add normalized map reference layers"
```

## Task 2: Reference-map dock and synchronized view state

**Files:**
- Create: `paleo_workbench/ui/pages/map_reference_panel.py`
- Modify: `paleo_workbench/ui/pages/map_edit_view.py`, `paleo_workbench/ui/pages/mapping_page.py`, `paleo_workbench/ui/tokens.py`
- Test: `tests/test_map_workbench_panels.py`, `tests/test_mapping_page.py`

**Interfaces:**

```python
class MapEditView(QGraphicsView):
    view_state_changed = Signal(dict)  # {"center": (x, y), "scale": float}
    cursor_position_changed = Signal(tuple)  # project CRS x, y
    def apply_view_state(self, state: dict, *, emit: bool = False) -> None: ...

class MapReferencePanel(QFrame):
    reference_visibility_changed = Signal(str, bool)
    reference_opacity_changed = Signal(str, float)
    overlay_requested = Signal(str)
    def set_layers(self, layers: list[MapReferenceLayer]) -> None: ...
    def set_view_state(self, state: dict) -> None: ...
```

- [ ] **Step 1: Write failing widget tests** asserting a ready layer appears with its CRS-aligned status, opacity changes emit `(id, value)`, and applying a main-view state updates the reference view without recursive signals.
- [ ] **Step 2: Run RED.**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_map_workbench_panels.py tests/test_mapping_page.py -v
```

- [ ] **Step 3: Implement `MapReferencePanel`** as a fixed-width right dock with a compact layer list, visible checkbox, opacity slider, “全图/当前视窗” actions, and a non-editable preview `MapEditView`. Do not duplicate editable scene items: the preview receives normalized reference display items only.
- [ ] **Step 4: Add guarded synchronization.** In `MapEditView`, emit state once after wheel/pan completion and expose `apply_view_state`; in `MappingPage`, use a `_syncing_views` boolean or monotonically increasing sync token so the main view cannot echo its own state back.
- [ ] **Step 5: Run GREEN and commit.**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_map_workbench_panels.py tests/test_mapping_page.py -v
git add paleo_workbench/ui/pages/map_reference_panel.py paleo_workbench/ui/pages/map_edit_view.py paleo_workbench/ui/pages/mapping_page.py paleo_workbench/ui/tokens.py tests/test_map_workbench_panels.py tests/test_mapping_page.py
git commit -m "feat: add synchronized map reference dock"
```

## Task 3: Collapsible bottom work area and factor-map comparison

**Files:**
- Create: `paleo_workbench/ui/pages/map_factor_shelf.py`, `paleo_workbench/ui/pages/map_topology_issue_panel.py`, `paleo_workbench/ui/pages/map_workbench_bottom.py`
- Modify: `paleo_workbench/ui/pages/mapping_page.py`, `paleo_workbench/ui/pages/map_attribute_table.py`, `paleo_workbench/ui/tokens.py`
- Test: `tests/test_map_workbench_panels.py`, `tests/test_mapping_page.py`

**Interfaces:**

```python
class MapFactorShelf(QWidget):
    factor_overlay_requested = Signal(str)
    def update_state(self, tasks: list[FactorMapTask], project_crs: str) -> None: ...
    def set_view_state(self, state: dict) -> None: ...
    def set_cursor_position(self, xy: tuple[float, float]) -> None: ...

class MapTopologyIssuePanel(QWidget):
    locate_requested = Signal(str)
    def set_issues(self, issues: list[dict[str, object]]) -> None: ...

class MapWorkbenchBottom(QTabWidget):
    def set_feature(self, feature: dict | None) -> None: ...
    def set_collapsed(self, collapsed: bool) -> None: ...
```

- [ ] **Step 1: Write failing tests** that verify the three tabs, factor-card filtering to complete tasks, factor overlay signal, issue count/locate signal, and collapsed state preserving the active tab.
- [ ] **Step 2: Run RED.**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_map_workbench_panels.py tests/test_factor_preview_grid.py -v
```

- [ ] **Step 3: Implement bottom composition.** Reuse the card data conventions in `FactorPreviewGrid`, but create clickable cards with output-resource identity and CRS status. Embed the existing `MapAttributeTable` as the first tab, not a second property implementation. Use a vertical `QSplitter` in `MappingPage` so the bottom dock can resize and collapse while the main canvas remains dominant.
- [ ] **Step 4: Bind `MappingPage` selection to `MapWorkbenchBottom.set_feature`, load complete factor tasks from the page’s project-state input, and route `locate_requested` to selection plus `MapEditView.centerOn`.**
- [ ] **Step 5: Run GREEN and commit.**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_map_workbench_panels.py tests/test_mapping_page.py tests/test_factor_preview_grid.py -v
git add paleo_workbench/ui/pages/map_factor_shelf.py paleo_workbench/ui/pages/map_topology_issue_panel.py paleo_workbench/ui/pages/map_workbench_bottom.py paleo_workbench/ui/pages/mapping_page.py paleo_workbench/ui/pages/map_attribute_table.py paleo_workbench/ui/tokens.py tests/test_map_workbench_panels.py tests/test_mapping_page.py
git commit -m "feat: add map factor and topology work area"
```

## Task 4: Structured topology feedback and save gate

**Files:**
- Modify: `paleo_workbench/ui/pages/map_edit_scene.py`, `paleo_workbench/ui/pages/mapping_page.py`, `paleo_workbench/ui/pages/map_edit_items.py`
- Test: `tests/test_map_topology.py`, `tests/test_mapping_save_draft.py`, `tests/test_map_workbench_panels.py`

**Interfaces:**

```python
class MapEditScene(QGraphicsScene):
    topology_issues_changed = Signal(list)
    def topology_issues(self) -> list[dict[str, object]]: ...
    def validate_for_save(self) -> tuple[bool, list[dict[str, object]]]: ...
```

- [ ] **Step 1: Write failing tests** for self-intersection producing an issue with `feature_id`, `severity="error"`, and location; adjacency remaining `severity="warning"`; and `MappingPage.save_draft()` returning `False` without clearing dirty state when errors exist.
- [ ] **Step 2: Run RED.**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_map_topology.py tests/test_mapping_save_draft.py tests/test_map_workbench_panels.py -v
```

- [ ] **Step 3: Replace status-only refresh with a structured issue builder.** Preserve `topology_status` for current table compatibility, but retain an issue record `{id, feature_id, code, severity, message, location}`. Publish updates only for the current edit generation; debounce full adjacency validation after a completed gesture with a single-shot `QTimer`.
- [ ] **Step 4: Gate `save_draft`.** Call `validate_for_save`; if errors exist, select and center the first affected feature, keep the document dirty, update the issue tab, and return `False`. Warnings remain visible and save normally.
- [ ] **Step 5: Run GREEN and commit.**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_map_topology.py tests/test_mapping_save_draft.py tests/test_map_workbench_panels.py -v
git add paleo_workbench/ui/pages/map_edit_scene.py paleo_workbench/ui/pages/mapping_page.py paleo_workbench/ui/pages/map_edit_items.py tests/test_map_topology.py tests/test_mapping_save_draft.py tests/test_map_workbench_panels.py
git commit -m "feat: surface map topology issues before save"
```

## Task 5: Indexed snapping and display LOD

**Files:**
- Modify: `paleo_workbench/mapping/map_edit_api.py`, `native/map_edit_core/src/map_edit_core.cpp`, `paleo_workbench/ui/pages/map_edit_scene.py`, `paleo_workbench/ui/pages/map_edit_view.py`
- Test: `tests/test_map_edit_scene.py`, `tests/test_map_edit_core_cpp.py`, `tests/test_map_topology.py`

**Interfaces:**

```python
def snap_point_indexed(
    editable_records: list[dict[str, object]],
    reference_points: list[tuple[float, float]],
    x: float, y: float, tolerance: float,
) -> tuple[float, float]: ...

class MapEditScene(QGraphicsScene):
    def set_reference_snap_points(self, points: list[tuple[float, float]]) -> None: ...
```

- [ ] **Step 1: Write failing tests** proving a vector-reference point is used only when its layer opts into snapping, output matches current `snap_point` semantics, and a generated 200-feature/20,000-vertex fixture performs candidate preparation once per scene generation rather than once per mouse move.
- [ ] **Step 2: Run RED.**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_map_edit_scene.py tests/test_map_topology.py tests/test_map_edit_core_cpp.py -v
```

- [ ] **Step 3: Implement the Python façade first.** Cache compact candidate buffers by scene generation and query only the tolerance-expanded viewport cell. Let `map_edit_core` implement the identical function over compact coordinate buffers; if unavailable or it raises, use the cached Python grid. Invalidate only on geometry, reference-snap, or tolerance changes.
- [ ] **Step 4: Implement view LOD.** On wheel/pan start set `MapEditView` to low-detail mode; after a short single-shot timer, restore full paths. Do not modify stored coordinates or command objects. Use each item’s existing bounding rectangle for culling before painting simplified geometry.
- [ ] **Step 5: Run GREEN (native tests remain skipped when extension is absent) and commit.**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_map_edit_scene.py tests/test_map_topology.py tests/test_map_edit_core_cpp.py -v
git add paleo_workbench/mapping/map_edit_api.py native/map_edit_core/src/map_edit_core.cpp paleo_workbench/ui/pages/map_edit_scene.py paleo_workbench/ui/pages/map_edit_view.py tests/test_map_edit_scene.py tests/test_map_topology.py tests/test_map_edit_core_cpp.py
git commit -m "perf: index map snapping and simplify navigation rendering"
```

## Task 6: Workbench integration, visual QA, and full verification

**Files:**
- Modify: `paleo_workbench/ui/pages/mapping_page.py`, `paleo_workbench/ui/pages/map_layer_tree.py`, `paleo_workbench/ui/tokens.py`, `docs/paleo_workbench_screen_inventory.md`
- Test: all mapping-focused suites and full `tests/`

- [ ] **Step 1: Write failing integration tests** for project CRS propagation, right-dock reference assignment, bottom factor data, canvas-priority collapse/restore, and reference descriptors surviving `ProjectManager.save()`/`load()`.
- [ ] **Step 2: Run RED.**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_mapping_integration.py tests/test_mapping_page.py tests/test_reference_layers.py -v
```

- [ ] **Step 3: Wire the final composition.** Extend `MappingPage.update_state` with explicit optional `project_crs`, `factor_tasks`, and `reference_layers` keyword parameters, preserving its existing list-only call sites. Ensure map layer tree lists editable layers and references distinctly; canvas-priority mode collapses splitter panes but preserves view, selection, and active bottom tab.
- [ ] **Step 4: Add the screen-inventory entry and inspect a representative project manually:** import a raster and vector reference, verify reprojection, overlay and side-by-side sync, use a factor map, create both warning and invalid topology conditions, then save/reload.
- [ ] **Step 5: Run focused suite, full suite, and commit.**

```bash
QT_QPA_PLATFORM=offscreen pytest tests/test_reference_layers.py tests/test_map_workbench_panels.py tests/test_map_edit_scene.py tests/test_map_topology.py tests/test_mapping_page.py tests/test_mapping_save_draft.py tests/test_mapping_integration.py -v
QT_QPA_PLATFORM=offscreen pytest -v
git add paleo_workbench/ui/pages/mapping_page.py paleo_workbench/ui/pages/map_layer_tree.py paleo_workbench/ui/tokens.py docs/paleo_workbench_screen_inventory.md tests
git commit -m "feat: integrate coordinate-aware map composition workbench"
```

## Plan self-review

- **Spec coverage:** tasks 1–2 cover GDAL, CRS normalization, overlay and side-by-side references; task 3 covers the approved bottom factor workspace; task 4 covers topology feedback and save rules; task 5 covers hot-path performance; task 6 covers state integration and full verification.
- **Dependency and fallback coverage:** GDAL is explicit; Python geometry behavior remains usable if the optional native extension is unavailable.
- **Scope control:** the plan deliberately excludes a QGIS embedding, new freehand raster editing, collaborative editing, and replacement of the existing document model.
