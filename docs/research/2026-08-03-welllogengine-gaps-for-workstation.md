# WellLogEngine API gaps for a ResFormSTAR-class shell

**Issue:** #215 (wayfinder research; map #207)  
**Scope:** Read-only survey of `well-log-engine/docs/*.md` and public headers under `well-log-engine/include/welllog/` (session, scene, qtwidgets, io, export, core, table)  
**Status:** Research complete (no code changes beyond this note)  
**Date:** 2026-08-03  

**Question:** Given the current WellLogEngine public surface (Session, presentation, multi-well, import adapters, export), what **gaps** block a ResFormSTAR-class shell from phase-1 **single-well** + **multi-well correlation** workflows?

Phase-1 product intent (from #207): interpreter opens a log-first app, loads wells, applies a multi-track template, pans/zooms a single-well plot, runs multi-well correlation, picks tops/links, and exports — engine under the hood. No proprietary ResForm formats/pixels.

---

## 1. Engine boundary (what is *not* a gap)

Architecture is explicit ([`well-log-engine/docs/architecture.md`](../../well-log-engine/docs/architecture.md), ADR 0011):

> WellLogEngine owns the log **scene and interaction semantics**; it does **not** own product windows, project files, permissions, or business workflows.

So the following are **by design host/shell responsibilities**, not missing engine APIs:

| Host-owned concern | Why |
|---|---|
| Product shell chrome (ribbon, docks, well tree IA) | Product window |
| Workspace / project persistence format | Project file |
| Well catalog (paths, UWI aliases, open set, CRS labels) | File management |
| Permission / licensing / multi-user | Business |
| Import UX (file pickers, multi-file well assembly policy) | Host orchestrates `welllog-io` adapters |
| Template **library product UX** (browse/author UI) | Product; *format* may need engine |
| Toolbar “tool modes” as UI | Host; can drive `ApplyPatch` / commands |

PRD #143 phase-one SDK is delivered ([`prd-143-completion.md`](../../well-log-engine/docs/prd-143-completion.md)). Gaps below are **workstation-shell blockers**, not incomplete PRD closeout.

---

## 2. Current public surface (inventory)

### 2.1 Session — `include/welllog/session/session.hpp`

| Area | Public capability |
|---|---|
| Documents | `SetDocumentCommand` (insert/replace by id); `document(id)` |
| Presentation | `SetPresentationCommand` + full `ScenePresentation` |
| Multi-well | `SetWellLayoutCommand` / `ClearWellLayoutCommand`, `WellPlacement`, gap, pack L→R |
| Shared depth | `SetSharedDepthViewportCommand`, `SetSurfaceHorizontalViewCommand` |
| Correlation | `SetDepthTransformCommand`, `AlignWellsToMarkersCommand`, `SetCrossWellOverlaysCommand` (horizon line / correlation band) |
| Viewport | pan/zoom/reset, metrics, crosshair |
| Selection | **Reference Depth Range** (or row span) on one Sampling Axis only (ADR 0024) |
| Edit | `DocumentPatch` / `ApplyPatchCommand`, `Undo`/`Redo` (per document) |
| Stream | `AppendBatchCommand`, coalesce, fixed/follow-latest viewport |
| Query | `prepared_scene`, `prepared_surface_scene`, `pick_surface_curve`, layout/overlays/transforms |
| Observability | diagnostics, performance budgets/snapshot, view events |

**Not present on Session public API:** document enumeration/remove, active tool, BeginEdit/CommitEdit, first-class `SetTrackWidth` / `ReorderTrack` / `SetLayerVisibility` (docs list them; headers use full presentation replace or patch entities), entity-typed selection variants.

### 2.2 Scene / presentation — `include/welllog/scene/scene.hpp`

| Built-in layer | Spec type |
|---|---|
| Curve | `CurveLayerSpec` + `TrackScaleSpec` |
| Interval / Marker / Symbol / Text | respective `*LayerSpec` |
| Crossover fill | `CrossoverFillLayerSpec` |
| Image | `ImageLayerSpec` (+ host tile resolver) |
| Custom | `CustomLayerSpec` → document `CustomLayerSource` |
| Pattern | `PatternDefinition` |
| Track header | `TrackHeaderSpec` — **only** `height` + `font_size`; prepared entries name/color/range/unit/mode |

**Missing vs docs SCN-02 / Frame Plan:** first-class **Grid Layer** (`GridLayerSpec` not in public headers).  
**No** presentation codec / template schema — builder is in-memory only.

### 2.3 Document — `include/welllog/core/document.hpp`

`WellLogDocument` exposes axes, curves, QC masks, intervals, markers, symbols, image sources, annotations, custom sources. **No** `WellMetadata`, **no** `defaultPresentation` (both appear only in data-model contract prose).

### 2.4 Qt widgets — `include/welllog/qtwidgets/`

- `WellLogView`: single-doc focus via `set_document_id`; paints multi-well when `well_layout()` non-empty (`prepared_surface_scene`).
- Gestures: pan/zoom depth, crosshair, Ctrl+drag depth-range selection, hover/click **curve** pick.
- `TableModel`: virtualized curve tables.

No built-in pick-tops tool, marker drag, or track-header chrome outside the scene.

### 2.5 IO adapters — `include/welllog/io/`

| Adapter | Output |
|---|---|
| `LasSourceAdapter` | `LasImport` → `WellLogDocument` + diagnostics |
| DLIS / LIS / Format716 | document (+ format-specific catalog fields, e.g. 716 `well_name`) |
| `ManifestCodec` | **document only** (buffers via host resolvers) |

No presentation/template I/O. No project/workspace format. Format vocabulary stays out of Core (ADR 0005 / 0049).

### 2.6 Export / table

- Vector/raster: PDF, SVG (paginated), PNG/TIFF; page chrome fields include host-supplied `well_name` on `ExportPageSpec`.
- Multi-well: compose surface scene then export (integration tests prove SVG path).
- Table: curve wide-tables only; `TableKind::intervals|markers|annotations` **reserved**, not built.

### 2.7 Python convenience (not a full product API)

`numpy_bridge` `submit_curve` / `submit_multi_well_section` builds **one default track per curve** — not multi-track professional templates. Shell must own presentation construction.

---

## 3. Phase-1 workflow → coverage map

| Workflow step (ResFormSTAR-class) | Engine today | Blocks phase-1? |
|---|---|---|
| Open work area / list wells | Host catalog | No (host) |
| Import LAS/DLIS/LIS/716 | IO adapters → document | Partial: well identity not on document |
| Apply multi-track template | In-memory `ScenePresentationBuilder` only | **Yes** — no portable template I/O; host must invent format or rebuild every open |
| Single-well pan/zoom/crosshair | Session + WellLogView | No |
| Multi-scale tracks, crossover fill, patterns | Presentation layers | No (if host builds presentation) |
| Track headers (minimal name/scale) | `TrackHeaderSpec` | Partial — weak vs workstation chrome |
| Depth grid / dedicated depth track | No Grid layer | **Yes** for “professional plot” polish |
| Multi-well side-by-side | `SetWellLayout` + surface scene | No |
| Align on tops / stretch | `AlignWellsToMarkers` + `DepthTransform` | No (markers must exist) |
| Cross-well links / bands | `CrossWellOverlay` | Partial — no undo/history; no entity pick |
| Pick tops / edit markers | `ApplyPatch` Upsert/Remove Marker | **Yes** for interactive pick — no marker pick, no active tool |
| Table linked to plot | Selection depth range + TableModel | Partial — no tops table projection |
| Export single/multi plot | Prepared scene / surface + exporters | No (host fills page metadata) |
| Undo tops edit | Document history | No for patch; **Yes** for layout/overlay/align session state |

---

## 4. Prioritized gap list

Each item: **P0** = blocks phase-1 single-well *or* correlation MVP; **P1** = severely degrades ResForm-class UX but workarounds exist; **P2** = later polish / stretch.

Ownership: **host-only** | **needs-engine-ticket**.

### P0 — must resolve before honest phase-1 claim

#### G1. Portable multi-track template / presentation I/O  
**needs-engine-ticket** (preferred) · also host can interim-own  

- **Evidence:** `ScenePresentation` / `ScenePresentationBuilder` are runtime-only; `ManifestCodec` writes/reads `WellLogDocument` only (`io/manifest.hpp`). Docs’ `defaultPresentation` / `PresentationProfile` are not on the public document type.
- **Why it blocks:** Workstation success criterion is “apply a multi-track template” across wells. Without a versioned codec (tracks, scales, layers, patterns, header heights, mnemonic bindings), every host reinvents templates and loses engine-aligned EntityId/revision semantics.
- **Host interim:** JSON/YAML template → host builds `ScenePresentation` (acceptable for prototype #214).
- **Engine ticket shape:** Presentation/template schema + codec (round-trip with patterns); optional document-linked default presentation; mnemonic-binding hints as data (not auto-guess at render time).

#### G2. Well identity / metadata on the document  
**needs-engine-ticket**  

- **Evidence:** `WellLogDocument` has no metadata API; data-model prose mentions `WellMetadata`. Export `well_name` is a host string on `ExportPageSpec`. Format716 keeps `well_name` on the adapter side only.
- **Why it blocks:** Multi-well surface and catalog need stable display names/UWI; hosts currently invent parallel maps keyed by `EntityId`.
- **Engine ticket shape:** Optional well metadata (name, UWI/API, field, source URI) on document + manifest field; adapters fill when present.

#### G3. Interactive tops / marker–interval pick + selection richness  
**needs-engine-ticket** (pick/selection) · **host-only** (tool chrome)  

- **Evidence:** Public picks are `pick_curve`, `pick_fill`, `pick_image`, `pick_custom`, `pick_surface_curve`. Selection is only `SelectionDepthRange` / row span (ADR 0024 implementation), not entity IDs. Data-model §12 describes broader selection variants not shipped.
- **Why it blocks:** Correlation “pick tops / links” needs hit-testing markers/intervals at depth, selection feedback, and patch commits. Host can approximate with depth→nearest marker math, but multi-track / multi-well surfaces need engine pick identity (document_id + marker_id + depths).
- **Host-only part:** Toolbar modes, cursors, confirm/cancel UI calling `ApplyPatchCommand`.
- **Engine ticket shape:** `pick_marker` / `pick_interval` (single + surface); optional selection tags for Marker/Interval/Overlay EntityIds; view events for pick commits.

#### G4. Session-level correlation state not on undo stack  
**needs-engine-ticket**  

- **Evidence:** History records document patch/append snapshots (`HistoryEntry` per document). `SetWellLayoutCommand`, `SetCrossWellOverlaysCommand`, `SetDepthTransformCommand` / `AlignWellsToMarkersCommand` mutate session maps without `can_undo` integration.
- **Why it blocks:** Interpreters expect Undo after aligning wells or drawing a correlation band; host would need a second undo stack (forbidden mirror of session state — ADR 0011).
- **Engine ticket shape:** Extend history (or session undo) to cover layout, per-well depth transform, and cross-well overlays; or document these as host-transactional with explicit inverse commands packaged as one undo unit.

#### G5. Well catalog / workspace / project model  
**host-only**  

- **Evidence:** Architecture: engine does not own project files. No catalog types in public headers.
- **Why it blocks shell but not engine:** Phase-1 still cannot ship without a host model: work area, well list, open documents ↔ session document ids, paths, last template, correlation set.
- **Host ticket shape:** Workspace model (#213); map catalog wells → `SetDocument` / layout; persist outside Manifest (or wrap Manifest per well + host project sidecar).

### P1 — strong workstation expectations

#### G6. Grid layer + depth-track semantics  
**needs-engine-ticket**  

- **Evidence:** Requirements SCN-02 and rendering Frame Plan mention grid; no `GridLayerSpec` in public scene API. Hosts can fake grid via `CustomLayerSource` polylines.
- **Why P1:** Single-well “professional” plots always show depth grids/scales; custom layers work but lose standard export/legend behavior and authoring cost.
- **Engine ticket:** First-class grid layer (major/minor spacing, linear/log awareness optional).

#### G7. Track header chrome ownership & richness  
**needs-engine-ticket** (engine draws headers) · **host-only** (shell title bars)  

- **Evidence:** `TrackHeaderSpec` = height + font size; `PreparedTrackHeaderEntry` carries curve name/color/scale/unit. No dual headers, scale bar widgets, per-well column titles on surface, or interactive header hit targets.
- **ADR 0023:** headers should describe each curve’s name, color, range, unit, scale type — **data** is prepared; **product chrome** (drag reorder from header, context menus) is host.
- **Split:** Engine owns in-scene header geometry/text; host owns dock chrome and may need engine hit-test on header entries later.
- **Engine ticket:** Richer header layout options; optional well-column title band on multi-well surface; header pick targets if interactive reorder is in phase-1.

#### G8. Document lifecycle on multi-well session  
**needs-engine-ticket**  

- **Evidence:** Multiple docs via repeated `SetDocumentCommand` (`insert_or_assign`); no public `document_ids()`, `RemoveDocument`, or clear-all.
- **Why P1:** Host catalog close/unload forces opaque map tracking; remove may leave layout/transform/overlay dangling ids unless host carefully rebuilds commands.
- **Engine ticket:** List/remove/clear document APIs with defined layout/overlay cleanup.

#### G9. Template application / mnemonic binding policy  
**host-only** (policy) · **needs-engine-ticket** only if binding lives in template schema (G1)  

- Mapping GR/RT/NPHI/RHOB → tracks/scales/colors is product convention (ResForm Compatibility Model in `CONTEXT.md` is **import** semantics, not UI template).
- Host owns dictionaries and “apply template to well” algorithm; engine should not auto-normalize scales from visible data (ADR 0023).

#### G10. Import orchestration & multi-file well  
**host-only**  

- Adapters parse one source unit to one document (LIS multi-logical-file requires explicit well selection — ADR 0049). Host decides whole-file import, curve filtering, and concatenating runs.

#### G11. Interval/marker/annotation table projections  
**needs-engine-ticket**  

- **Evidence:** `TableKind` reserved values; Phase A = curves only (`table_projection.hpp`).
- **Why P1 for correlation:** Tops tables next to the plot are standard; host can build QAbstractTableModel from document spans as interim.

### P2 — later / non-blocking workarounds

#### G12. Wellbore trajectory / MD↔TVD resource  
**needs-engine-ticket** (later)  

- `DepthDomain` enum exists; piecewise `DepthTransform` can approximate display alignment. Full survey trajectory math is out of render core by design (data-model §7) but a first-class immutable transform resource would help MD/TVD/TVDSS switching.

#### G13. Incremental presentation commands  
**needs-engine-ticket** (convenience)  

- Docs list `SetTrackWidth`, `ReorderTrack`, `SetLayerVisibility`. Shipped path: rebuild `ScenePresentation` or `ApplyPatch` on `TrackSpec` / `CurveLayerSpec`. Fine for MVP; incremental commands reduce host bugs.

#### G14. Active tool / BeginEdit–CommitEdit  
**needs-engine-ticket** (optional) · **host-only** interim  

- Architecture mentions active tool; not in public session API. Host can implement tools as command sequences + local gesture state without mirroring viewport/selection.

#### G15. WITSML / live protocol clients  
**host-only / deferred**  

- Explicitly deferred in PRD completion; AppendBatch is enough if host streams tails.

#### G16. Mixed-mode export rasterization path completeness  
**needs-engine-ticket** (export polish)  

- Snapshot/report surface exists; some mixed-mode paths documented as follow-up. Pure vector + raster snapshots suffice for phase-1.

---

## 5. Recommended ownership split (phase-1)

```text
┌──────────────────────── Workstation shell (host) ─────────────────────────┐
│ Workspace/catalog · file open · template library UX · toolbars · docks     │
│ Mnemonic→track binding · well tree · project save · export dialogs         │
└───────────────┬───────────────────────────────┬────────────────────────────┘
                │ build/apply presentation      │ ApplyPatch / overlays
                ▼                               ▼
┌────────────────────────── WellLogEngine ──────────────────────────────────┐
│ Document + Manifest · ScenePresentation · Session commands/events          │
│ Multi-well layout · DepthTransform · CrossWellOverlay · Prepared scene     │
│ WellLogView GL · Table projection · PDF/SVG/PNG/TIFF · LAS/DLIS/LIS/716    │
└────────────────────────────────────────────────────────────────────────────┘
```

| Do in host first | Prefer engine ticket first |
|---|---|
| Catalog, project file, shell IA (#209–#214) | G1 template codec |
| Tool mode UI driving patches | G3 marker/interval pick + selection |
| Interim template JSON → builder | G2 well metadata |
| Curve table UI from existing projection | G4 session undo for correlation |
| CustomLayer grid interim | G6 grid layer; G8 doc remove/list |

---

## 6. Suggested engine tickets (derived; not filed here)

1. **Presentation/template codec + schema** (G1) — blocks #212 grill.  
2. **WellMetadata on document + manifest + adapters** (G2).  
3. **Marker/interval (surface) pick + entity selection** (G3).  
4. **Undo/history for layout, depth transform, cross-well overlays** (G4).  
5. **Document list/remove + layout consistency** (G8).  
6. **GridLayerSpec** (G6).  
7. **Richer track/well header presentation** (G7).  
8. **Table projections for intervals/markers** (G11).

Host map tickets already cover G5/G9/G10 (#211–#214, #213).

---

## 7. Top 5 gaps (executive)

1. **G1 — Template/presentation portable I/O** — needs-engine-ticket (host interim OK).  
2. **G3 — Tops pick + entity selection** — needs-engine-ticket + host tool chrome.  
3. **G4 — Undo for correlation session state** — needs-engine-ticket.  
4. **G5 — Well catalog / workspace** — host-only.  
5. **G2 — Well metadata on document** — needs-engine-ticket.

Honorable mentions for single-well “looks professional”: **G6 grid**, **G7 header chrome**.

---

## 8. Sources (primary)

| Path | Role |
|---|---|
| `well-log-engine/docs/architecture.md` | Host vs engine boundary |
| `well-log-engine/docs/requirements.md` | SCN/VIEW/TBL/EDT scenarios |
| `well-log-engine/docs/data-model-and-api.md` | Contract (some ahead of headers) |
| `well-log-engine/docs/prd-143-completion.md` | Delivered vs deferred |
| `well-log-engine/docs/qt-python-integration.md` | Widget non-responsibilities |
| `include/welllog/session/session.hpp` | Commands/events surface |
| `include/welllog/scene/scene.hpp` | Presentation + prepared scene + multi-well compose |
| `include/welllog/core/document.hpp` | Document entities |
| `include/welllog/qtwidgets/well_log_view.hpp` | Embed widget |
| `include/welllog/io/{las,dlis,lis,format716,manifest}.hpp` | Import + manifest |
| `include/welllog/table/table_projection.hpp` | Table Phase A limits |
| `include/welllog/export/pagination.hpp` | Export snapshot / page chrome |
| ADRs 0011, 0012, 0013, 0022, 0023, 0024, 0025, 0005, 0049 | Decisions |
| GitHub #207, #215 | Map + this research question |

---

## 9. Conclusion

WellLogEngine **already supplies** the hard rendering/session core for phase-1: documents, multi-track presentation model, multi-well layout, marker alignment, cross-well overlays, patch-based interpretation edits, table linkage for curves, and publication export.

What still blocks a ResFormSTAR-class **shell** is mostly **product state outside the scene** (catalog/workspace/templates UX) plus a short list of **engine host-API gaps**: portable templates, well metadata, tops picking/selection, and undo for correlation commands. Grid/header richness and tops tables improve fidelity but have host-side workarounds.

No code was changed outside this research note.
