# Research: Well–seismic fence & Time-domain 2D profile public APIs

**Ticket:** paleo-workbench #117 (wayfinder research)  
**Date:** 2026-07-25  
**Scope:** Read-only inventory of public APIs in geoviz / joint host for well-to-well fence and Time-domain 2D profile.  
**Primary sources:** package source under `geo-viz-engine/packages/geoviz_well_seismic_3d/`, host under `paleo_workbench/viz/joint_host.py`, page consumers.

---

## 1. Executive summary

| Need | Public API today? | Where |
|------|-------------------|--------|
| Create well-to-well fence from two well names | **Yes** | `WellSeismicScene.add_well_to_well_fence`, host wrapper, UI combos |
| List / activate fences | **Yes** (scene only) | `fences`, `active_fence_id`, `set_active_fence`, `add_fence` |
| Vertical domain Time / Depth | **Yes** | `WellSeismicScene.set_vertical_domain` + host `set_vertical_domain("Time"\|"Depth")` |
| 2D fence VD profile widget | **Yes** (via joint widget, not package `__all__`) | `FenceProfile2D` via `profile_widget` / `take_profile_widget` |
| Drive 2D profile from **orthogonal** IL/XL/Time slices | **No** | Profile is **active-fence only** |
| Timeslice **picking of wells** (click well on time plane) | **No** in joint / well-seismic-3d | Related: map `WellsLayer.hit_test`; SeismicView polyline-on-timeslice is **not** well-named |
| Draw well-to-well line on 3D by interaction | **Partial / gap** | Scene fence → translucent curtain mesh; no click-pick path. `Renderer3D.set_arbitrary_polyline` is a parallel, unlinked path |
| Force 2D profile to **Time** fence while scene may be Depth | **Gap** | Single scene-wide `vertical_domain`; extract uses that domain for `sample_axis` |

---

## 2. Layer map

```
UI pages
  WellSeismicJointPage
  GeologicalModeling3DPage
        │
        ▼
WellSeismicJointHost          (paleo_workbench/viz/joint_host.py)
  · lifecycle, reload, domain, fence pair API
  · owns WellSeismicScene
        │ scene_updated / scene property
        ▼
WellSeismicJointWidget        (geoviz_well_seismic_3d/joint_widget.py)
  · Renderer3D (orthogonal 3D planes)
  · FenceProfile2D (fence 2D VD; detachable)
  · overlays: wells, fence curtains, probe
        │
        ▼
WellSeismicScene              (geoviz_well_seismic_3d/scene.py)
  · survey, VerticalDomain, wells, fences, volume, probe
  · extract_active_fence / assemble_active_profile_wells
```

**Import seams**

| Symbol | Package export | `geoviz` re-export |
|--------|----------------|--------------------|
| `WellSeismicScene` | `__all__` | yes (`geoviz/__init__.py` `_COMPATIBILITY_EXPORTS`) |
| `WellSeismicJointWidget` | lazy `__getattr__` | yes |
| `FenceSection`, `FenceExtraction`, `well_to_well_path` | `__all__` | `FenceSection` yes; extraction/path via package |
| `VerticalDomain`, `WellHead`, `ProfileWellHit` | `__all__` | `VerticalDomain`, `WellHead` yes; `ProfileWellHit` package only |
| `FenceProfile2D` | **not** in `__all__` | **no** — only via widget `profile_widget` / `take_profile_widget` |
| `WellSeismicJointHost` | workbench only | n/a |

---

## 3. `WellSeismicScene` — fence, domain, profile assembly

**File:** [`geo-viz-engine/packages/geoviz_well_seismic_3d/geoviz_well_seismic_3d/scene.py`](../../geo-viz-engine/packages/geoviz_well_seismic_3d/geoviz_well_seismic_3d/scene.py)  
**Docstring:** primary public seam for joint well–seismic analysis.

### 3.1 Vertical domain Time / Depth

| Member | Behavior |
|--------|----------|
| Default | `VerticalDomain.TIME` (`_domain`) |
| `vertical_domain` | property → `VerticalDomain` enum (`"time"` / `"depth"`) |
| `set_vertical_domain(domain: VerticalDomain)` | Switches domain; on Depth also resets depth transform via `select_depth_transform`; invalidates trajectory cache + fence extract cache |
| `depth_transform` / `set_depth_transform` | `DepthTransformState` (V0 constant for Depth approx) |

Fence extract uses domain for **vertical sample axis**:

```python
# extract_active_fence (scene.py)
if self._domain is VerticalDomain.TIME:
    saxis = survey.t0_ms + np.arange(nt) * survey.dt_ms
else:
    saxis = self._depth_transform.constant.time_ms_to_depth_m(...)
```

Well trajectories (`well_trajectories` → `project_well_trajectory`) also respect active domain (Time needs TD table or wellhead-only warning).

### 3.2 Fence list & well-to-well

| Member | Signature / notes |
|--------|-------------------|
| `fences` | `list[FenceSection]` (copy) |
| `active_fence_id` | `str \| None` |
| `active_fence()` | active `FenceSection` or `None` |
| `add_fence(fence, *, activate=True)` | append; optionally set active |
| `set_active_fence(fence_id)` | `KeyError` if unknown |
| `set_fence_visible(fence_id, visible)` | mutates `FenceSection.visible` |
| **`add_well_to_well_fence(well_names, *, name="Wells")`** | resolves each name in `set_wells` heads → XY → `well_to_well_path` → `FenceSection` → `add_fence(activate=True)` |

Supporting types ([`fence.py`](../../geo-viz-engine/packages/geoviz_well_seismic_3d/geoviz_well_seismic_3d/fence.py)):

- `FenceSection(name, vertices_xy, visible=True, id=uuid)` — polyline in survey XY metres  
- `well_to_well_path(well_xy)` — `N≥2` surface positions → polyline  
- `extract_fence_strip(...)` → `FenceExtraction(fence_id, amplitude, arc_length_m, sample_axis)` shared by 3D curtain + 2D VD  

**Note:** `add_well_to_well_fence` takes a **list** of names (not only two). Host/UI currently pass exactly two.

Arbitrary polylines (non-well vertices) are supported via `add_fence(FenceSection(...))` but **no host/UI action** exposes free-draw fences today.

### 3.3 2D assembly & probe (fence-centric)

| Member | Role |
|--------|------|
| `extract_active_fence(*, n_along=128)` | Sample volume along **active** fence; cached per fence id |
| `assemble_active_profile_wells()` | Wells within `set_near_well_distance_m` (default 100 m) of fence polyline → `list[ProfileWellHit]` |
| `set_probe(s_m, z)` / `probe` | Probe on active fence; drives 3D marker + orthogonal slice indices |
| `probe_slice_indices()` | `(il, xl, sample)` via registration or survey |
| `world_to_render_xyz` | World XY + domain Z → volume/render index space |
| `slice_inline` / `slice_crossline` / `slice_time` | Orthogonal volume slices only (data API; not the 2D profile widget) |

`ProfileWellHit`: `name`, `s_m`, `distance_m`, `tops`, optional curve arrays — used by `FenceProfile2D` for vertical ticks/labels.

---

## 4. `WellSeismicJointHost` — workbench lifecycle seam

**File:** [`paleo_workbench/viz/joint_host.py`](../../paleo_workbench/viz/joint_host.py)  
**Class:** `WellSeismicJointHost(QObject)`

### Public API (relevant)

| Member | Role |
|--------|------|
| `scene` | `WellSeismicScene \| None` |
| `well_names()` | trajectory keys after load |
| `reload(*, preferred_domain=None, auto_default_fence=True)` | Hybrid assets; optional domain restore; may auto-create default fence from first two wells when volume ready |
| **`set_vertical_domain(domain, *, emit_scene=True)`** | String `'Time'` / `'Depth'` (case-insensitive **prefix**); maps to `VerticalDomain`; Depth sets V0=3000 m/s transform |
| **`add_well_to_well_fence(well_a, well_b, *, name=None)`** | Validates non-empty distinct pair → `scene.add_well_to_well_fence([a,b], name=label)` → `scene_updated` |
| Signals | `status_changed(str)`, `scene_updated()` |

**Not on host:** fence list management, active fence switch, profile detach, camera, slice indices, 3D drawing interaction. Those stay scene / widget / page.

**Auto fence:** `_on_volume_ready` if `auto_default_fence` and `len(names)≥2` and `not scene.fences` → `add_well_to_well_fence(names[:2], name="默认井间")`.

Persistence (project, not host API): `JointAnalysisState.vertical_domain`, `active_fence_wells`, `active_fence_name` in [`paleo_workbench/project/models.py`](../../paleo_workbench/project/models.py).

---

## 5. `WellSeismicJointWidget` — 3D + profile facade

**File:** [`geo-viz-engine/packages/geoviz_well_seismic_3d/geoviz_well_seismic_3d/joint_widget.py`](../../geo-viz-engine/packages/geoviz_well_seismic_3d/geoviz_well_seismic_3d/joint_widget.py)

### 5.1 Profile widget & detach

| Member | Behavior |
|--------|----------|
| `profile_widget` | Public property → internal `FenceProfile2D` (or `None` if import failed / after take) |
| **`take_profile_widget()`** | Returns `_profile` and sets `_profile = None` so host can reparent into a separate panel |

**Consumer:** `GeologicalModeling3DPage._ensure_joint_widget` prefers `take_profile_widget()`, reparents into `joint_2d_host`, stores `_joint_profile`. On `scene_updated`, page calls both `joint_widget.set_scene(scene)` and `profile.set_scene(scene)` because detach removes auto-sync from widget’s `_sync_from_scene` when `_profile is None`.

`WellSeismicJointPage` keeps profile **inside** the joint widget (no take).

### 5.2 How 2D profile content is set — fence vs orthogonal slices

| Content path | Mechanism |
|--------------|-----------|
| **Fence 2D VD** | `FenceProfile2D.set_scene` → `scene.extract_active_fence()` + `assemble_active_profile_wells()` + probe paint ([`profile_2d.py`](../../geo-viz-engine/packages/geoviz_well_seismic_3d/geoviz_well_seismic_3d/profile_2d.py)) |
| **3D fence curtain** | `set_scene` / `set_layer_visibility` → `extract_active_fence` → `set_fence_curtains([ext])` → translucent mesh via `_curtain_mesh` |
| **Orthogonal IL / XL / Time planes** | `Renderer3D` only (`load_volume`, `set_slice_indices` / `apply_slice_positions`). **Not** fed into `FenceProfile2D` |
| **Probe linkage** | Click on 2D profile → `probe_changed(s_m, z)` → `scene.set_probe` → 3D marker + **orthogonal** slice jump |

There is **no** public switch on the joint widget to display “current IL/XL/Time 2D profile” in the bottom strip. That strip is **always** the active fence section (or empty placeholder text: “无活动剖面（创建井间剖面或折线）”).

### 5.3 Other public overlay / control APIs

| Method | Role |
|--------|------|
| `set_scene(scene)` | Volume load + wells + active fence curtain + profile scene + probe |
| `set_well_trajectories(trajectories)` | 3D well polylines |
| `set_fence_curtains(extractions)` | Fence curtain meshes |
| `set_probe_marker(xyz)` | Probe scatter |
| `set_slice_indices(il, xl, sample)` | Orthogonal planes only |
| `slice_indices()` | Read back positions |
| `set_layer_visibility(wells=, fences=, volume=)` | Independent layers |
| `set_camera_pose(...)` | Camera |

Docstring contract: hosts must not touch private `Renderer3D._view`.

### 5.4 `FenceProfile2D` (semi-public)

**File:** [`profile_2d.py`](../../geo-viz-engine/packages/geoviz_well_seismic_3d/geoviz_well_seismic_3d/profile_2d.py)

| Member | Role |
|--------|------|
| `set_scene(scene)` | Bind + `refresh()` |
| `refresh()` | Redraw VD from active fence extract |
| `probe_changed` signal | `(s_m, z)` from click |
| Click mapping | Label coords → arc length s + vertical z from `sample_axis` |

Not re-exported on `geoviz` or package `__all__`; stable access is through the joint widget properties.

---

## 6. Timeslice picking of wells — does a public API exist?

### 6.1 Joint / well-seismic-3d

**No.** Grep of `geoviz_well_seismic_3d` shows:

- No mouse hit-test on 3D wells  
- No timeslice-plane well markers with pick handlers  
- No “pick well A then well B on time slice → fence” API  
- `_pick_curve` is curve-name selection for profile, not geometric picking  

Well presence near a fence is **compute-only**: `assemble_active_profile_wells` projects head XY onto the fence polyline within `_near_well_m`.

### 6.2 Adjacent systems (not joint public contract)

| API | Package | Relation |
|-----|---------|----------|
| `WellsLayer.hit_test(screen_pt, viewport)` | `geoviz_map` | 2D map wells, not seismic timeslice |
| `ProfileVD.enable_polyline_drawing` + `polyline_changed` | `geoviz_seismic` | Draw free polyline on a profile |
| `SeismicView._on_polyline_drawn` → `Renderer3D.set_arbitrary_polyline` | `geoviz_seismic` | Timeslice frac coords → index-space arbitrary curtain + magenta floor line |
| Horizon pick on profiles | `SeismicView` | Horizon points, not wells |

**SeismicView’s timeslice polyline path is not wired into `WellSeismicJointWidget`.** Joint fences use scene `FenceSection` + custom curtain mesh, not `set_arbitrary_polyline`.

### 6.3 Conclusion

**Timeslice picking of wells does not exist as a public joint/geoviz_well_seismic_3d API.** Fence endpoints are chosen by **name** (combo boxes / host `add_well_to_well_fence` / restored `active_fence_wells`).

---

## 7. Gaps vs product intents

### 7.1 Draw well-to-well line on 3D

| Available | Gap |
|-----------|-----|
| After fence exists: 3D **curtain mesh** (`set_fence_curtains`) + well **trajectories** | No interactive “click well A, click well B on 3D / timeslice” |
| Host/UI: combobox pair + “井间剖面” button | No floor-line overlay on the **time plane** for the fence path in joint widget (Renderer3D draws magenta path only for `_arb_polyline`) |
| `add_fence` / `add_well_to_well_fence` for programmatic paths | Joint does not call `renderer.set_arbitrary_polyline` with fence IL/XL waypoints |
| Multi-well list on scene API | Host only exposes two named wells |

**To close (design options, not implemented):**

1. Scene/host: keep name-based fence; widget maps `active_fence().vertices_xy` → registration → `set_arbitrary_polyline` for textured curtain + floor line.  
2. Interaction: 3D or timeslice hit-test against wellhead XY / trajectories → accumulate two names → `add_well_to_well_fence`.  
3. Free-draw polyline on timeslice → `FenceSection` vertices (Survey XY), then extract — parallel to SeismicView, but convert index-space → world XY via registration.

### 7.2 Force 2D profile to Time fence section

| Available | Gap |
|-----------|-----|
| Scene/host domain Time → extract `sample_axis` in ms; profile Z is Time | **Single** `vertical_domain` for trajectories, extract, probe, and 3D Z mapping together |
| Default domain is Time | No API: “3D Depth / model Depth, 2D profile locked to Time fence” |
| `FenceProfile2D` always shows **active fence**, not orthogonal Time slice | No “force profile = vertical section through fence in Time” independent of UI domain combo |

**What works today for Time fence profile:**

1. Ensure domain is Time: `host.set_vertical_domain("Time")` or `scene.set_vertical_domain(VerticalDomain.TIME)`.  
2. Ensure an active fence: `add_well_to_well_fence` or `add_fence` + `set_active_fence`.  
3. Bind profile: `set_scene` / detached `profile.set_scene(scene)` so `extract_active_fence` runs.  
4. Volume + survey must be set or extract returns `None` (empty UI message).

**What does not exist:** dual-domain scene, profile-only domain override, or forcing the 2D panel to show IL/XL/Time orthogonal content instead of the fence strip.

---

## 8. Consumer call paths (reference)

### 8.1 Standalone joint page

[`paleo_workbench/ui/pages/well_seismic_joint_page.py`](../../paleo_workbench/ui/pages/well_seismic_joint_page.py)

- Domain combo → `_host.set_vertical_domain`  
- Well combos + “井间剖面” → `_host.add_well_to_well_fence`  
- `scene_updated` → `_joint.set_scene(host.scene)` (profile stays embedded)

### 8.2 Geological modeling 3D (embedded joint)

[`paleo_workbench/ui/pages/geological_modeling_3d_page.py`](../../paleo_workbench/ui/pages/geological_modeling_3d_page.py)

- `_ensure_joint_widget`: construct widget, `take_profile_widget` → `joint_2d_host`  
- `_on_joint_scene_updated`: `set_scene` on widget **and** detached profile  
- `_on_joint_fence` / restore: host `add_well_to_well_fence`  
- `_on_joint_domain_changed`: host domain + modeling Z guard for Time  

### 8.3 Tests covering fence / domain / profile assembly

| Test file | Covers |
|-----------|--------|
| `tests/test_well_seismic_fence_probe.py` | multi-fence, well-to-well, extract identity, near-well assembly, probe, depth domain, registration |
| `tests/test_well_seismic_3d_scene.py` | domain default Time, trajectories, joint widget facade |
| `tests/test_joint_host.py` | host domain Time/Depth |
| `tests/test_joint_slice_apply.py` | `set_slice_indices` / camera |
| `tests/test_joint_layer_visibility.py` | layer visibility |

---

## 9. Symbol index (absolute-friendly paths)

| Symbol | Path |
|--------|------|
| `WellSeismicScene` | `/home/kevin/projects/paleo_project/geo-viz-engine/packages/geoviz_well_seismic_3d/geoviz_well_seismic_3d/scene.py` |
| `add_well_to_well_fence` (scene) | same, method on `WellSeismicScene` |
| `fences` / `active_fence_id` / `set_active_fence` | same |
| `extract_active_fence` / `assemble_active_profile_wells` | same |
| `VerticalDomain` | `.../models.py` |
| `FenceSection` / `FenceExtraction` / `well_to_well_path` | `.../fence.py` |
| `FenceProfile2D` | `.../profile_2d.py` |
| `WellSeismicJointWidget` | `.../joint_widget.py` |
| `take_profile_widget` / `profile_widget` | same |
| `WellSeismicJointHost` | `/home/kevin/projects/paleo_project/paleo_workbench/viz/joint_host.py` |
| `add_well_to_well_fence` (host) | same |
| `set_vertical_domain` (host) | same |
| `Renderer3D.set_arbitrary_polyline` | `/home/kevin/projects/paleo_project/geo-viz-engine/packages/geoviz_seismic/geoviz_seismic/renderer_3d.py` |
| `SeismicView` timeslice polyline → 3D | `.../seismic_view.py` (`_on_polyline_drawn`) |
| `WellsLayer.hit_test` | `/home/kevin/projects/paleo_project/geo-viz-engine/packages/geoviz_map/geoviz_map/layers/wells.py` |
| Package exports | `.../geoviz_well_seismic_3d/__init__.py` |
| Geoviz re-exports | `/home/kevin/projects/paleo_project/geo-viz-engine/geoviz/__init__.py` |

---

## 10. Bottom-line answers (ticket questions)

1. **WellSeismicScene / Host — fence list, well-to-well, domain**  
   - Scene: full fence CRUD-ish (`add_fence`, list, active, visibility) + `add_well_to_well_fence(names)` + `VerticalDomain` TIME/DEPTH.  
   - Host: thin wrappers for domain string + two-well fence + reload/auto-default fence; **no** fence list API.

2. **WellSeismicJointWidget — profile / take_profile / fence vs orthogonal**  
   - `profile_widget` / `take_profile_widget` expose `FenceProfile2D`.  
   - 2D content = **active fence extract only**. Orthogonal slices live only on `Renderer3D` and do not populate the 2D strip.

3. **Timeslice well picking public?**  
   - **No** in joint stack. Closest unrelated pieces: map well hit-test; SeismicView free polyline on timeslice (not well-named).

4. **Gaps**  
   - **3D well-to-well line:** programmatic fence + translucent curtain exists; interactive draw / timeslice well pick / Renderer3D arbitrary polyline integration for joint fences do not.  
   - **Force Time fence 2D:** set scene domain to Time + active fence; no dual-domain or profile-only Time lock; no orthogonal-slice mode for that panel.
