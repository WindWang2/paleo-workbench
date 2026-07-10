# End-to-End Real Data Pipeline Design

> **Date:** 2026-07-10  
> **Status:** Approved for planning  
> **Program:** Phase 18 (18a implementable; 18b/18c contracts)  
> **Related:**  
> - `docs/superpowers/specs/2026-07-10-visualization-geoviz-adapter-design.md`  
> - `docs/superpowers/specs/2026-07-10-mapping-editor-v1-design.md`  
> - `docs/superpowers/specs/2026-07-07-project-management-design.md`  
> - `paleo_workbench/resources/scanner.py`, `classifier.py`  
> - `paleo_workbench/viz/` (`VizAdapter`)  
> - `paleo_workbench/prediction/adapters.py`, `workflow/factors.py`

## Goal

Build a **pipeline service layer** that turns the repository’s real `data/` tree into a coherent `ProjectDocument`, then (in later gates) feeds prediction canvases and a mapping draft—without inventing a second source of truth outside the project model.

**End-to-end story (multi-delivery):**

```text
data/ (full index)
    → 18a bootstrap ProjectDocument
    → Data page lists real assets; VizAdapter opens LAS/SEGY/map
    → 18b prediction pages bind real LAS/SEGY (display-true)
    → 18c deterministic compile → PaleoMapDocument draft → mapping editor
```

### Decisions

| Dimension | Decision |
|-----------|----------|
| Architecture | Pure pipeline services + thin UI/CLI (方案 A) |
| Entry | Pure function + CLI + UI **「打开样例工程」** |
| Scan scope | Full recursive index of `data/` (path registration only; no copy) |
| Implementation order | 18a → 18b → 18c; this doc is the program design |
| First implementation plan | **18a only** |

## Non-Goals (whole Phase 18 program)

- Real ML inference services or training
- Copying `data/` into a project vault
- Replacing the mapping editor or `VizAdapter`
- Full QC/export productization (成图审核 stays display-first)
- Perfect CRS reprojection of every vendor format
- Checksumming multi-GB SEGY on every cold start (see performance rule)
- Shipping 18b/18c implementation in the first plan (contracts only)

## Current Baseline

- MVP UI pages (Phases 1–17) on `main`; ~501 tests.
- `scan_resources` + `classify_path` already classify LAS/SEGY/horizon/time-depth/etc.
- Data management center + full-index-capable import; visualization loads real LAS/SEGY via `VizAdapter`.
- Prediction pages and factor maps still driven by **mock** adapters (`mock-prediction-v1`, `mock-factor-v1`).
- Mapping editor V1 edits `PaleoMapDocument`; no automatic draft from real assets yet.
- Project open/save via `.paleo.json` and toolbar **新建/打开/保存工程**.

## Architecture

```text
CLI / tests / UI menu
        │
        ▼
paleo_workbench/pipeline/          # no Qt, no AppShell imports
  bootstrap.py   ──18a──► BootstrapResult → ProjectDocument (+ optional .paleo.json)
  assets.py      ──18b contract──► bind PredictionTask.input_refs
  compile_map.py ──18c contract──► PaleoMapDocument draft
        │
        ▼
existing: scan_resources, ProjectManager, VizAdapter, map editor
```

**Boundary rule:** `paleo_workbench/pipeline/` must not import AppShell pages or create Qt widgets. UI pages call pure functions and apply the returned document.

### Phase map

| Gate | Name | Deliverable | First plan? |
|------|------|-------------|-------------|
| **18a** | Sample project bootstrap | Pure bootstrap + CLI + UI menu; full `data/` index | **Yes** |
| **18b** | Asset-backed prediction views | Tasks ↔ resource ids; pages load via `VizAdapter` | Contract only |
| **18c** | Deterministic map draft | Factors/prediction → polygons + wells on `PaleoMapDocument` | Contract only |

### Cross-phase data flow

```text
18a bootstrap
  resources[], stratigraphy, one compilation_run (draft)
       │
18b bind_prediction_assets + (optional) MockPredictionAdapter.run
  prediction_tasks[].input_refs → real files on canvas
       │
18c compile_map_draft
  paleomap_documents[] + active id on run
       │
  Mapping editor / Viz map tab
```

**Provenance:** Generated tasks/docs set `generator_version` / `seed` where models already have those fields. Map draft uses `view_state["generator"] = "deterministic-map-draft-v1"`.

### Dependency order

1. Ship **18a** (first implementation plan).
2. **18b** needs resources + `VizAdapter` (done) + thin page wiring.
3. **18c** needs mock prediction regions and/or factor `sample_points`; can run mock-only if 18b slips.

---

## 18a — Sample project bootstrap (implementable)

### API

```text
bootstrap_sample_project(
    data_root: Path,
    *,
    project_name: str = "惠西南样例工程",
    region: str = "惠西南",
    project_path: Path | None = None,   # for relativize_path
    skip_checksum_over_bytes: int = 50 * 1024 * 1024,
) -> BootstrapResult
```

```text
BootstrapResult(
    document: ProjectDocument,
    skipped: list[{path, reason}],
    stats: {files, by_type},
)
```

Only `document` is serialized to `.paleo.json`. `skipped` / `stats` are for CLI/UI observability.

Optional write helper (CLI / tests):

```text
write_project(doc: ProjectDocument, path: Path) -> Path
  # Existing ProjectManager / JSON schema — no new format
```

### Package layout

```text
paleo_workbench/pipeline/
  __init__.py          # export bootstrap_sample_project, BootstrapResult
  bootstrap.py         # scan + enrich ProjectDocument
  assets.py            # 18b: stubs / protocols only in 18a delivery
  compile_map.py       # 18c: stubs / protocols only in 18a delivery
```

### Document fields filled by bootstrap

| Field | Source / rule |
|-------|----------------|
| `meta.name` / `region` / `project_root` | Args; `project_root` = parent of `.paleo.json` if known, else `data_root.parent` or cwd |
| `resources[]` | Full recursive scan of `data_root` via existing classifier; skip `._*` junk |
| `resources[].path` | Prefer relative to `project_path` when set; else absolute; `external=True` when outside project dir |
| `resources[].checksum` | SHA256 if size ≤ threshold; else `None` + `parsed_summary.checksum_skipped=true` |
| `resources[].parsed_summary` | Always `size_bytes`; optional `rel_dir` (parent under `data_root`) for UI grouping |
| `stratigraphy.target_horizon` | Prefer first horizon `*.dat` stem under `层位/` (sorted), else `""` |
| `stratigraphy.sequence_boundaries` | All horizon file stems under `层位/` (sorted) |
| `stratigraphy.applicable_wells` | Well-log basenames without extension (`A1`… from `*.Las`) |
| `stratigraphy.applicable_seismic_ranges` | Seismic resource names |
| `compilation_runs` | One draft run: name = project name + ` 演示编制`, `target_horizon` as above, empty step list OK |
| `factor_map_tasks` / `prediction_tasks` / `paleomap_documents` | **Empty in 18a** (18b/c fill) |

**Not in 18a:** parsing well-head coordinates into `well_overlays`, running mock prediction, writing map geometry.

### Scanner changes

Extend `scan_resources` with optional:

```text
skip_checksum_over_bytes: int | None = None
```

When set and `stat().st_size > threshold` → skip hash (`checksum=None`). Bootstrap always passes the 50 MB default. Import/rescan may reuse later.

### Performance rule (full index)

- Register every file under `data_root` (full index).
- Do **not** SHA256 files over `skip_checksum_over_bytes` (default 50 MB) or when skip is requested for seismic-scale assets.
- Still classify and list large SEGY files.

### CLI

```text
python -m paleo_workbench.pipeline.bootstrap \
  --data-root data \
  --out sample.paleo.json \
  [--name ...] [--region ...]
```

| Outcome | Behavior |
|---------|----------|
| Success | Exit 0; print resource count and output path |
| Missing `data_root` | Exit 2; clear stderr |
| Empty tree (0 files) | Exit 2 / raise `ValueError("no files under data_root")` |
| Unexpected error | Exit 1 |

No Qt import on this module path.

### UI entry

| Surface | Behavior |
|---------|----------|
| Label | **「打开样例工程」** (文件 menu if present, else adjacent to 打开工程) |
| Resolve `data/` | (1) `Path.cwd()/data`, (2) walk from package/repo root to `data/`, (3) env `PALEO_SAMPLE_DATA` |
| Success | Same as open-project success: set document, `_refresh_shell`, status bar name |
| Failure | Non-destructive `QMessageBox`; keep current project |
| Persist | Do **not** auto-save `.paleo.json`; user uses 保存工程. CLI is the materialize-file path |
| Dirty project | If unsaved dirty tracking exists, confirm discard/save; if not, simple confirm replace; dirty tracking is a documented follow-up if absent |

### Errors (18a)

| Case | Behavior |
|------|----------|
| `data_root` missing / not a dir | `FileNotFoundError`; CLI exit 2; UI message |
| Zero files | `ValueError`; fail loudly (mis-pointed root) |
| Unreadable file mid-scan | Skip; append to `BootstrapResult.skipped` |
| UI handler | Catch pipeline errors; never leave half-applied shell state |

### Tests (18a)

1. **Unit:** temp `data/` with LAS + DAT + large fake `.sgy` → types correct; large file `checksum is None`.
2. **Unit:** horizon stems → stratigraphy fields.
3. **Unit:** CLI writes loadable JSON via `ProjectManager`.
4. **UI smoke:** window action loads project; data page resource count > 0 (offscreen).
5. **Boundary:** `pipeline` must not import `paleo_workbench.ui`.
6. Full suite remains green (baseline ≥ 501).

### Acceptance (18a)

- [ ] Menu and CLI produce a project with a full classified index of repo `data/`.
- [ ] Data page lists assets; LAS/SEGY **在可视化中打开** still works on indexed paths.
- [ ] No prediction/map tasks required for 18a success.
- [ ] `pipeline/` has zero Qt imports.

---

## 18b — Asset-backed prediction views (contract)

**Intent:** 测井/地震预测 pages show **real LAS / SEGY** from `ProjectDocument.resources`. Task summary fields may remain mock/replaceable.

### Binding model

Use existing `PredictionTask.input_refs: dict[str, list[str]]`:

| Key | Value | Meaning |
|-----|--------|---------|
| `well_log_resource_ids` | `list[str]` | Resource ids (`type=well_log`) for canvas |
| `seismic_resource_ids` | `list[str]` | Resource ids (`type=seismic`) for volume |
| `horizon` | optional single-id list | Linked horizon resource if any |

Helpers in `pipeline/assets.py` (pure; implement in 18b):

```text
bind_prediction_assets(
    project: ProjectDocument,
    task: PredictionTask,
    *,
    well_log_ids: list[str] | None = None,
    seismic_ids: list[str] | None = None,
) -> PredictionTask
  # mutates input_refs; does not run ML

suggest_assets_for_demo(project) -> dict
  # first N LAS + first SEGY by stable sort for a default task
```

### Page data path

```text
PredictionTask
  → resolve primary well_log / seismic resource id from input_refs
  → VizAdapter.ref_from_resource + resolve
  → WellLogCanvasPanel / SeismicViewPanel load real payload
  → if missing/unreadable: message state (same as viz); keep mock summary panels
```

**Fallback:** If `input_refs` empty, keep `well_log_data_from_prediction` / `seismic_volume_from_prediction` mock converters.

### Non-goals (18b)

- Real facies ML
- Multi-well cross-plot editor
- Writing prediction grids to disk

### Acceptance sketch (when implemented)

- Bound task + real LAS path → canvas shows real curves.
- Unbound task → mock path still works.
- Binding only changes `input_refs` + display (not scientific claims).

---

## 18c — Deterministic map draft (contract)

**Intent:** From project state, produce one **editable** `PaleoMapDocument` the mapping editor can open. Fully demo/replaceable; no scientific claim.

### Compiler API (`pipeline/compile_map.py`)

```text
compile_map_draft(
    project: ProjectDocument,
    *,
    target_horizon: str | None = None,
    prediction_task_id: str | None = None,
    seed: int = 0,
) -> PaleoMapDocument
```

**Input priority:**

1. `target_horizon` arg → else active compilation run → else `stratigraphy.target_horizon`
2. Optional `PredictionTask.result_summary.predicted_regions`
3. Optional `FactorMapTask.parameters.sample_points`
4. Well-log resource names as well labels when coordinates missing

**Outputs on `PaleoMapDocument`:**

| Field | Rule |
|-------|------|
| `name` | `f"{horizon} 相带草稿"` |
| `linked_target_horizon` | resolved horizon |
| `linked_prediction_task_id` | if used |
| `facies_polygons` | Deterministic simple polygons (grid cells or buffers from sample points / mock regions); existing editor schema |
| `well_overlays` | From factor sample_points and/or well-head parser if available; else synthetic coords with real well names |
| `line_features` / `label_features` | Empty or minimal labels |
| `map_chrome` | Title = name; legend keys from facies names |
| `view_state["generator"]` | `"deterministic-map-draft-v1"` |
| Demo flag | `view_state["is_demo_draft"] = true` |

Append to `project.paleomap_documents`; set `compilation_runs[0].active_paleomap_document_id` when a run exists.

**Determinism:** Same `seed` + same inputs → same geometry.

### UI hook (later)

- 制备 or 编图: **「生成演示草稿」** → `compile_map_draft` → select doc on mapping page.
- Optional CLI `--with-map-draft` is **out of 18a scope**.

### Non-goals (18c)

- Topology-perfect geology
- Reading vendor `.dfb` / phase maps as ground truth
- Review/export QC automation

### Acceptance sketch (when implemented)

- After compile, mapping editor loads polygons + wells.
- Save draft still uses existing `document_io`.
- Demo draft is clearly flagged in `view_state`.

---

## Error handling (program)

| Layer | Rule |
|-------|------|
| **pipeline/** | Raise clear exceptions; never show Qt dialogs |
| **BootstrapResult** | Soft-skip unreadable files; hard-fail missing root / zero files |
| **UI** | Catch pipeline errors → `QMessageBox`; keep current project |
| **CLI** | stderr + exit 2 (usage/path), exit 1 (unexpected) |
| **18b later** | Resolve failure → canvas message; task list stays |
| **18c later** | Insufficient inputs → `ValueError` with actionable message; no silent empty map |

## Testing strategy

| Level | 18a (now) | 18b/c (later) |
|-------|-----------|----------------|
| Unit | temp tree scan, checksum skip, stratigraphy, CLI JSON round-trip | bind_refs, compile determinism, polygon schema |
| Import boundary | `pipeline` must not import `paleo_workbench.ui` | same |
| Integration | open sample → data page count; optional viz open_ref smoke | prediction canvas real LAS; map editor load draft |
| Regression | full suite green | + focused suites |

## Rollout

1. Implement **18a** on a feature branch: menu + CLI + tests.
2. Update `task_plan.md` / `progress.md` when shipping.
3. **18b** then **18c** as separate plan cycles using this design’s contracts.
4. Optional later: bootstrap flag `--with-demo-tasks` chaining mock prediction + map draft (**not** 18a default).

## Open follow-ups (non-blocking for 18a)

- Unsaved dirty-project guard if not already tracked
- Well-head `.dat` → real coordinates for overlays (helps 18c)
- Checksum policy tuning if full `data/` scan is slow on HDD

## Success criteria (program-level)

1. One action (menu or CLI) yields a project whose data page shows real classified assets from `data/`.
2. LAS/SEGY already openable in visualization via existing adapter (no new renderer).
3. 18b/c can land without reshaping 18a’s document shape—only filling tasks/maps.
