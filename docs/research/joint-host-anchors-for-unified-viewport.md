# Joint host anchors for unified 3D viewport

**Issue:** #103 (wayfinder research)  
**Scope:** Facts inventory for unified 3D viewport work on `GeologicalModeling3DPage`  
**Status:** Research complete (read-only)  
**Date:** 2026-07-25  

This note inventories **construction**, **objectNames**, **panel toggles**, **tests that pin the layout**, **public APIs** on the joint host/widget, and **tree → visibility** mapping. Citations are repo paths + symbols.

---

## 1. GeologicalModeling3DPage construction

**File:** `paleo_workbench/ui/pages/geological_modeling_3d_page.py`  
**Class:** `GeologicalModeling3DPage`

### 1.1 Page objectName and non-UI joint host

| Symbol | Role |
|--------|------|
| `GeologicalModeling3DPage.setObjectName("GeologicalModeling3DPage")` | Page identity (shell navigation tests) |
| `self._joint_host = WellSeismicJointHost(self)` | Non-UI lifecycle owner (scene, reload, domain, fences) |
| `self._joint_widget` | Mounted `WellSeismicJointWidget` (lazy in `_ensure_joint_widget`) |
| `self._joint_profile` | Detached fence 2D profile (after `take_profile_widget`) |
| `self._joint_status` | Status `QLabel` living inside `joint_2d_host` |
| `self.gl_widget` | Modeling-only `pyqtgraph.opengl.GLViewWidget` (**no** `objectName`) |

Signals wired in `__init__`:

- `_joint_host.status_changed` → `_on_joint_status`
- `_joint_host.scene_updated` → `_on_joint_scene_updated`

### 1.2 Splitter / panel topology

```
GeologicalModeling3DPage
└── QHBoxLayout
    └── _main_splitter  (QSplitter Horizontal, 4 children)
        [0] left_widget          — model_tree
        [1] center_column
            └── _center_v_split  (QSplitter Vertical, 2 children)
                [0] view_container
                    ├── gl_widget          (GLViewWidget, modeling meshes)
                    └── floating_bar       (camera presets over modeling GL)
                [1] _joint_2d_panel        objectName "JointFence2DPanel"
                    ├── header + btn_toggle_joint_2d
                    └── joint_2d_host      objectName "Joint2DHost"
                        ├── (placeholder → fence profile after mount)
                        └── _joint_status
        [2] _joint_3d_panel                objectName "Joint3DPanel"
            ├── header + btn_toggle_joint_3d
            ├── joint tools (domain, wells, fence, align, refresh)
            └── joint_3d_host              objectName "Joint3DHost"
                └── (placeholder → WellSeismicJointWidget after mount)
        [3] right_scroll                   — params / clip / export / tie
```

**Main horizontal splitter** (`__init__` ~L89–L617):

- Created as local `splitter = QSplitter(Qt.Horizontal, self)`, then stored as `self._main_splitter`.
- Children order: left | center (GL+2D) | joint 3D | right params.
- Default sizes: `[240, 720, 280, 340]`.
- Stretch: center only (`setStretchFactor(1, 1)`); side panes `0`.
- Test pin: `_main_splitter.count() == 4` (`tests/test_geomodel_joint_layout.py`).

**Center vertical splitter** (`self._center_v_split`):

- Top: `view_container` (modeling GL).
- Bottom: `_joint_2d_panel`.
- Default sizes: `[700, 220]`; stretch factors `3` / `1`.
- Expanded sizes cached in `_joint_2d_expanded_sizes`.

### 1.3 Host shells: `joint_3d_host` / `joint_2d_host`

| Attribute | Type | objectName | Parent panel |
|-----------|------|------------|--------------|
| `joint_3d_host` | `QWidget` | `"Joint3DHost"` | `_joint_3d_panel` (`"Joint3DPanel"`) |
| `joint_2d_host` | `QWidget` | `"Joint2DHost"` | `_joint_2d_panel` (`"JointFence2DPanel"`) |

Construction details:

- **`joint_2d_host`** (~L224–L235): empty `QVBoxLayout`; initial `_joint_2d_placeholder` label + `_joint_status`.
- **`joint_3d_host`** (~L288–L297): empty `QVBoxLayout`; initial `_joint_3d_placeholder` label. Panel width clamps min 200 / max 480.

These are **layout mounts**, not `WellSeismicJointHost`. The lifecycle host is `self._joint_host` (`paleo_workbench.viz.joint_host.WellSeismicJointHost`).

### 1.4 Modeling `gl_widget`

- `self.gl_widget = gl.GLViewWidget()` inside `view_container` (~L133–L136).
- Camera defaults: `opts['distance'] = 250`; `setCameraPosition(**_CAMERA_PERSPECTIVE)` where `_CAMERA_PERSPECTIVE = dict(distance=250, elevation=30, azimuth=45)`.
- Top-down preset: `_CAMERA_TOP_DOWN = dict(distance=250, elevation=90, azimuth=0)`.
- Floating bar buttons call `gl_widget.setCameraPosition` directly (orbit / pan / reset).
- **No** `setObjectName` on `gl_widget` or `view_container`.
- Geomodel meshes, volumes, well-curve overlays, RGB slices, cross-well fences all go to **this** GL view — separate from geoviz joint `Renderer3D` inside `_joint_widget`.

### 1.5 Mounting joint widget + profile detach

**Method:** `_ensure_joint_widget` (~L859–L889)

1. No-op if `_joint_widget` already set.
2. If `_joint_host.scene is None`, update 3D placeholder with `engine_error`.
3. `from geoviz import WellSeismicJointWidget` → construct with parent `self.joint_3d_host`.
4. **Profile detach:** `take_profile_widget()` (preferred) or `profile_widget`; reparent into `joint_2d_host` at layout index 0 stretch 1; store as `_joint_profile`.
5. Remove placeholders; `joint_3d_host.layout().addWidget(self._joint_widget, 1)`.

**Trigger paths:**

- `showEvent` → first visible: `_joint_loaded_once`, then `_ensure_joint_widget` + host `reload(...)`.
- `_on_joint_scene_updated` → ensure widget, `set_scene`, re-`set_scene` on detached profile, fill combos, `_sync_joint_visibility_from_tree`.

### 1.6 Panel toggle behavior (chrome collapse)

| Control | Handler | Collapsed behavior | Expanded restore |
|---------|---------|--------------------|------------------|
| `btn_toggle_joint_2d` (checkable, default unchecked) | `_toggle_joint_2d_panel` | `joint_2d_host.setVisible(False)`; button text `"展开"`; vertical splitter sizes → `[total-36, 36]` | Restores `_joint_2d_expanded_sizes` or `[700, 220]`; text `"折叠"` |
| `btn_toggle_joint_3d` (checkable, default unchecked) | `_toggle_joint_3d_panel` | `joint_3d_host.setVisible(False)`; text `"展开"`; main splitter index 2 width → `40`; panel min/max → 40/48 | Restores `_joint_3d_expanded_width` (default 280); panel min/max → 200/480 |

**Important interaction with tree visibility:** collapse only hides the **host content** (and shrinks chrome). Tree sync (`_sync_joint_visibility_from_tree`) can hide **entire panels** (`_joint_3d_panel` / `_joint_2d_panel`) independently. Collapse does **not** clear tree checks; tree hide does **not** toggle the collapse buttons.

### 1.7 Joint toolbar on 3D panel

Inside `_joint_3d_panel` (~L265–L286):

| Widget | Action |
|--------|--------|
| `_joint_domain` (`Time`/`Depth`) | `_on_joint_domain_changed` → `_joint_host.set_vertical_domain` + `_update_domain_z_guard` |
| `_joint_well_a` / `_joint_well_b` | Fence endpoints |
| `_joint_fence_btn` | `_on_joint_fence` → `_joint_host.add_well_to_well_fence` |
| `_joint_align_btn` | `_align_joint_camera` — copies `gl_widget.opts` distance/elevation/azimuth → `_joint_widget.set_camera_pose` |
| `_joint_add_btn` | `_on_joint_add_from_project` — `reload(preferred_domain=..., auto_default_fence=False)` |

### 1.8 objectName inventory (page-local)

| objectName | Widget |
|------------|--------|
| `GeologicalModeling3DPage` | page root |
| `JointFence2DPanel` | `_joint_2d_panel` |
| `Joint2DHost` | `joint_2d_host` |
| `Joint3DPanel` | `_joint_3d_panel` |
| `Joint3DHost` | `joint_3d_host` |
| `PrimaryButton` / `SecondaryButton` | various right-panel actions (not joint-specific) |

**Not named:** `gl_widget`, `_main_splitter`, `_center_v_split`, `view_container`, `_joint_widget`, floating bar.

### 1.9 Shell wiring

**File:** `paleo_workbench/ui/app_shell.py`

- `self.geomodel_page = GeologicalModeling3DPage()` at stack index **10** (“三维建模”).
- Comment: `# index 10 = 三维建模 (+ 井震联合)`.
- Standalone `WellSeismicJointPage` still exists under `paleo_workbench/ui/pages/well_seismic_joint_page.py` but is **not** on the app rail (`tests/test_well_seismic_joint_page.py` asserts geomodel index 10 + no joint rail).

---

## 2. Tests that anchor these surfaces

Paths under `tests/` (repo root). PYTHONPATH includes `paleo_workbench/` and geoviz packages via env bootstrap / package installs.

### 2.1 Layout / chrome — `test_geomodel_joint_layout.py`

| Test | Anchors |
|------|---------|
| `test_geomodel_page_has_joint_host_regions` | `joint_3d_host.objectName == "Joint3DHost"`, `joint_2d_host == "Joint2DHost"`, `_joint_3d_panel`, `_joint_2d_panel`, `_main_splitter.count() == 4` |
| `test_geomodel_tree_has_geoviz_joint_group` | Tree groups `"井震联合 (geoviz)"` and `"井震标定与综合 (geomodel)"`; `_joint_host is not None` |
| `test_geomodel_joint_auto_reload_empty` | Empty data → status contains `"空状态"` / `"未找到"` after `_ensure_joint_widget` + host `reload` |
| `test_geomodel_joint_toolbar_domain_and_fence_api` | `_joint_domain`, `_joint_fence_btn`; domain/fence soft-fail status |
| `test_geomodel_joint_panels_collapse` | `btn_toggle_joint_3d/2d` toggles `joint_3d_host` / `joint_2d_host` visibility |

### 2.2 App shell — `test_app_shell.py`

| Test | Anchors |
|------|---------|
| `test_app_shell_geological_modeling_3d_page_navigation` | Nav button index 10 → `objectName == "GeologicalModeling3DPage"`; `model_tree`, **`gl_widget`**, `btn_run` present |
| `test_app_shell_has_eleven_pages` | Stack count 11 (joint not a separate page) |

### 2.3 Joint host lifecycle — `test_joint_host.py`

| Test | Anchors |
|------|---------|
| `test_host_empty_reload_status` | `WellSeismicJointHost.reload` empty → status signal |
| `test_host_has_scene_when_geoviz_available` | `host.scene` vs `engine_error` |
| `test_host_preferred_domain_not_forced_to_time` | `set_vertical_domain("Depth")` on scene |
| `test_joint_page_delegates_to_host` | Legacy `WellSeismicJointPage` still uses host |

### 2.4 Widget public API unit tests

| File | Tests | Anchors |
|------|-------|---------|
| `test_joint_slice_apply.py` | `test_set_slice_indices_uses_apply_slice_positions` | `WellSeismicJointWidget.set_slice_indices` → `Renderer3D.apply_slice_positions(..., rebuild=True)` |
| | `test_set_camera_pose_delegates_to_renderer` | `set_camera_pose` → `renderer.set_camera_pose` |
| `test_joint_layer_visibility.py` | `test_set_layer_visibility_keeps_renderer_visible_when_volume_off` | Volume off: `setVisible(True)` on renderer + `set_planes_visible(False)` |
| | `test_renderer_set_planes_visible_toggles_plane_attrs` | `Renderer3D.set_planes_visible` |
| `test_well_seismic_3d_scene.py` | `test_package_importable_and_joint_widget_facades_renderer` | Widget composes `Renderer3D`; `set_scene` |

### 2.5 Persistence — `test_joint_analysis_persistence.py`

| Test | Anchors |
|------|---------|
| `test_joint_analysis_state_roundtrip_in_project` | `JointAnalysisState` on `ProjectDocument` (tree_checks, domain, wells, path_hints; no voxels) |
| `test_geomodel_collect_joint_state` | `collect_joint_analysis_state` / `save_joint_analysis_to_project` from page domain combo |
| `test_fill_joint_combos_preserves_saved_fence_pair` | Saved fence pair beats list order |
| `test_collect_path_hints_includes_td_tops` | path_hints keys `td_dir`, `tops`, `horizons` |
| `test_project_controller_flushes_joint_on_save` | Flush only after `_joint_loaded_once` |
| `test_project_controller_skips_joint_flush_until_page_loaded` | Unvisited page must not clobber project joint state |

Model: `paleo_workbench/project/models.py` → `JointAnalysisState`, field `ProjectDocument.joint_analysis`.

### 2.6 Navigation after joint-page removal — `test_well_seismic_joint_page.py`

| Test | Anchors |
|------|---------|
| `test_geomodel_page_index_and_no_joint_rail` | `PAGE_INDEX_GEOMODEL == 10`, page objectName, joint not a rail page |
| `test_joint_host_empty_without_data` | Host empty status without data |

### 2.7 Related (mapping / assets, weaker layout anchors)

| File | Notes |
|------|-------|
| `test_joint_clip_map.py` | Pure mapping `modeling_clip_to_joint_slices` (#92); used by page `_apply_clip_to_joint_slices` |
| `test_joint_asset_resolver.py` | Hybrid asset resolve; path_hints |
| `test_well_seismic_fence_probe.py` | Scene probe / `probe_slice_indices` (not page chrome) |
| `test_geological_modeling_3d_page.py` | Older UI: asserts `gl_widget`, tree count — **tree top-level labels may lag** current dual geoviz/geomodel groups (see §4) |
| `test_geoviz_package_independence.py` | Export name `"WellSeismicJointWidget"` |

### 2.8 Risk note for unified viewport

Any merge of modeling GL + joint GL into one viewport will break or require updates to:

1. `objectName` / attribute pins on `Joint3DHost` / `Joint2DHost` / 4-pane `_main_splitter`.
2. Collapse tests that assume separate `joint_*_host` visibility.
3. `_align_joint_camera` path that copies **between** two cameras.
4. Profile detach into `Joint2DHost`.
5. Dual tree groups (geoviz vs geomodel) if layer semantics change.

---

## 3. Public APIs

### 3.1 `WellSeismicJointHost`

**File:** `paleo_workbench/viz/joint_host.py`  
**Class:** `WellSeismicJointHost(QObject)`

Non-UI seam (PRD #85 / ticket #86). Does **not** own widgets or camera.

#### Signals

| Signal | Payload | When |
|--------|---------|------|
| `status_changed` | `str` | Human status for chrome labels |
| `scene_updated` | — | After scene content changes; listeners refresh widgets |

#### Properties / read API

| Member | Returns |
|--------|---------|
| `scene` | `WellSeismicScene` or `None` |
| `paths` | `JointAssetPaths \| None` |
| `survey_meta` | `dict` (copy) |
| `engine_error` | `str \| None` if geoviz import/scene failed |
| `well_names()` | `list[str]` from scene trajectories |

#### Mutating API

| Method | Purpose |
|--------|---------|
| `set_project(project)` | Bind `ProjectDocument` for hybrid resolve |
| `reload(*, preferred_domain=None, auto_default_fence=True)` | Resolve assets, bind wells/survey/tops/curves, async preview volume |
| `set_vertical_domain(domain, *, emit_scene=True)` | `'Time'` / `'Depth'` (prefix match); optional suppress `scene_updated` |
| `add_well_to_well_fence(well_a, well_b, *, name=None)` | Create well-to-well fence on scene |
| `shutdown()` | Stop preview volume `OwnedWorkerJob` |

**Not on host:** camera pose, slice indices, layer visibility, profile detach — those are widget/page concerns.

Internal (not public contract): `PreviewVolumeWorker`, `_apply_wells_and_survey`, `_apply_tops_and_curves`, `_on_volume_ready` / `_on_volume_failed`.

### 3.2 `WellSeismicJointWidget`

**Package path:** `geo-viz-engine/packages/geoviz_well_seismic_3d/geoviz_well_seismic_3d/joint_widget.py`  
**Import:** `from geoviz import WellSeismicJointWidget` (lazy re-export) or `geoviz_well_seismic_3d.WellSeismicJointWidget`

Docstring contract: hosts must not dig private `Renderer3D._view`; use public overlay/camera APIs.

#### Properties

| Property | Role |
|----------|------|
| `scene` | Bound `WellSeismicScene` |
| `renderer` | Underlying `geoviz_seismic.renderer_3d.Renderer3D` or `None` |
| `profile_widget` | Fence 2D profile (may be reparented); `FenceProfile2D` |

#### Profile detach

| Method | Behavior |
|--------|----------|
| `take_profile_widget()` | Returns `_profile`, sets internal `_profile = None` for host reparenting |

Used by `GeologicalModeling3DPage._ensure_joint_widget` to put profile in `Joint2DHost`.

#### Camera

| Method | Signature / notes |
|--------|-------------------|
| `set_camera_pose(*, distance=250.0, elevation=30.0, azimuth=45.0)` | Prefers `renderer.set_camera_pose`; fallback `view.setCameraPosition` **inside** widget only |

Page: `_align_joint_camera` reads modeling `gl_widget.opts` and calls this.

#### Slice indices

| Method | Behavior |
|--------|----------|
| `slice_indices() -> tuple[int,int,int] \| None` | `(il, xl, sample)` via `renderer.get_slice_positions` or private attrs fallback |
| `set_slice_indices(il, xl, sample)` | Prefers `renderer.apply_slice_positions(..., rebuild=True)`; fallback `set_position_external` + `_update_slice_planes` |

Page: `_apply_clip_to_joint_slices` maps modeling clip sliders → joint indices via `paleo_workbench.viz.joint_clip_map.modeling_clip_to_joint_slices`.

#### Visibility

| Method | Behavior |
|--------|----------|
| `set_layer_visibility(*, wells=True, fences=True, volume=True)` | Independent layers: fence flags on scene; volume toggles **planes** not whole renderer (`set_planes_visible` / plane attrs); rebuilds well/fence overlays |

#### Scene / overlays

| Method | Role |
|--------|------|
| `set_scene(scene)` | Bind + `_sync_from_scene` (volume load, wells, active fence curtain, profile, probe) |
| `set_well_trajectories(trajectories)` | Replace well polylines |
| `set_fence_curtains(extractions)` | Fence curtain meshes |
| `set_probe_marker(xyz_render \| None)` | Probe scatter |

#### Private (hosts must not use)

- `_view()`, `_sync_from_scene`, `_curtain_mesh`, `_clear_items`, `_traj_to_render`, `_on_profile_probe`

### 3.3 Downstream renderer API (delegated)

**File:** `geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/renderer_3d.py`

| Method | Used by widget for |
|--------|--------------------|
| `get_slice_positions()` | `slice_indices` |
| `apply_slice_positions(il, xl, sample, rebuild=...)` | `set_slice_indices` |
| `set_camera_pose(...)` | `set_camera_pose` |
| `set_planes_visible(visible)` | `set_layer_visibility(volume=...)` |

---

## 4. Tree → visibility mapping

### 4.1 Tree population

**Method:** `_populate_model_tree` (~L665–L704)

Geoviz joint group (all children checkable, default **Checked**):

```
井震联合 (geoviz)
├── 地震预览体 (geoviz)
├── 联合井轨迹 (geoviz)
├── 井间剖面 fence (geoviz)
├── 井震 3D 视口
└── 井震 2D 剖面条
```

Geomodel tie group (meshes in modeling `gl_widget`, separate stack):

```
井震标定与综合 (geomodel)
├── 地震剖面三维切片 (Seismic Slices)
├── 井眼旁显测井曲线 (3D GR Logs)
├── 合成地震记录叠加 (Synthetic Seismograms)
├── RGB 属性融合三维切片 (RGB Fusion Slice)
└── 井震连井三维剖面幕墙 (Cross-Well Seismic Fence)
```

`itemChanged` → `_on_tree_item_changed` (parent check cascades to children).

### 4.2 `_sync_joint_visibility_from_tree`

**Method:** ~L1278–L1301

| Tree label | Local flag | Effect |
|------------|------------|--------|
| `井震 3D 视口` | `show_3d` | With volume: show `_joint_3d_panel`, `joint_3d_host`, `_joint_widget` |
| `地震预览体 (geoviz)` | `show_vol` | Same panel show (OR with `show_3d`); layer `volume=` |
| `井震 2D 剖面条` | `show_2d` | `_joint_2d_panel` + `joint_2d_host` visibility |
| `联合井轨迹 (geoviz)` | `show_wells` | `set_layer_visibility(wells=...)` |
| `井间剖面 fence (geoviz)` | `show_fence` | `set_layer_visibility(fences=...)` |

Panel rule:

```text
_joint_3d_panel / joint_3d_host / _joint_widget visible  ⇔  show_3d OR show_vol
_joint_2d_panel / joint_2d_host visible                  ⇔  show_2d
_joint_profile visible                                   ⇔  show_2d AND show_fence
```

Layer call when widget exists:

```python
self._joint_widget.set_layer_visibility(
    wells=show_wells, fences=show_fence, volume=show_vol
)
```

Helper: `_tree_item_checked(name) -> bool` (default **True** if label missing).

### 4.3 Modeling tree visibility (parallel path)

`_sync_visibility_from_tree` (~L1234–L1251) maps non-geoviz tree labels to `mesh_items_map` / `vol_item` on **`gl_widget` only**. Invoked together with joint sync from `_on_tree_item_changed`.

### 4.4 Persistence of checks

- **Collect:** `collect_joint_analysis_state` walks only groups whose title contains `"井震联合"`; stores child name → checked bool in `JointAnalysisState.tree_checks`.
- **Restore:** `_apply_joint_tree_checks_from_project` on first `showEvent`, then `_sync_joint_visibility_from_tree`.
- **Save gate:** project save flushes joint state only if `_joint_loaded_once` (see persistence tests).

### 4.5 Call sites that re-sync joint visibility

1. `_on_tree_item_changed`
2. `_apply_joint_tree_checks_from_project`
3. `_on_joint_scene_updated` (after set_scene / profile update)

---

## 5. Dual-viewport reality (design fact for #103)

Today there are **two independent OpenGL surfaces** on the modeling page:

| Surface | Owner | Content |
|---------|-------|---------|
| `gl_widget` (`GLViewWidget`) | Page modeling pipeline | Stratigraphy volumes/meshes, geomodel well-seismic overlays |
| `_joint_widget.renderer` (`Renderer3D`) | geoviz joint package | Orthogonal seismic slices + joint wells/fences |

Coupling today:

- **One-way camera:** `_align_joint_camera` (modeling → joint).
- **One-way clip:** modeling clip sliders → joint slice indices (`_apply_clip_to_joint_slices`).
- **Domain guard:** Time domain soft-hides modeling volume items (`_update_domain_z_guard`).
- **Shared project/host data**, separate render trees and tree groups.

Unified viewport work must decide how to preserve:

- objectName / splitter anchors used by tests,
- profile detach into 2D strip,
- independent layer checks (`set_layer_visibility` semantics),
- persistence of tree_checks without voxel payloads.

---

## 6. Quick symbol index

| Concern | Primary symbol | Path |
|---------|----------------|------|
| Page layout | `GeologicalModeling3DPage.__init__` | `paleo_workbench/ui/pages/geological_modeling_3d_page.py` |
| Collapse 2D/3D | `_toggle_joint_2d_panel`, `_toggle_joint_3d_panel` | same |
| Mount widget | `_ensure_joint_widget` | same |
| Align camera | `_align_joint_camera` | same |
| Tree joint vis | `_sync_joint_visibility_from_tree` | same |
| Non-UI host | `WellSeismicJointHost` | `paleo_workbench/viz/joint_host.py` |
| Widget facade | `WellSeismicJointWidget` | `geo-viz-engine/packages/geoviz_well_seismic_3d/geoviz_well_seismic_3d/joint_widget.py` |
| Persist model | `JointAnalysisState` | `paleo_workbench/project/models.py` |
| Clip→slice map | `modeling_clip_to_joint_slices` | `paleo_workbench/viz/joint_clip_map.py` |
| Shell index 10 | `AppShell.geomodel_page` | `paleo_workbench/ui/app_shell.py` |
