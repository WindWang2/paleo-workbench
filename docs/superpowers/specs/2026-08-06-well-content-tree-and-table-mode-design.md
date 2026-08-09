# Well Content Tree + Graphic/Table Dual View — Design Spec

**Date:** 2026-08-06  
**Status:** Implementable (wayfinder complete)  
**Product:** WellPlot Desktop (`well-log-engine/apps/wellplot-desktop/well_log_workstation`) — single-well path first  
**Map:** [Wayfinder: 单井井道数据树与图/表双视图规格](https://github.com/WindWang2/paleo-workbench/issues/331)  
**Prototype (throwaway):** `well-log-engine/apps/wellplot-desktop/well_log_workstation/prototypes/well-content-tree-shell.html`

This document is the **canonical product + acceptance spec** for first-ship. Implementation tickets should be split from it via `/to-tickets`. It does **not** restate full ticket resolutions; each locked decision links to its issue.

---

## 1. Problem and scope

### Problem

Interpreters import multi-curve LAS (e.g. A2) into WellPlot Desktop and need to:

1. See **all available scalar tracks** for the selected well, organized by import source.
2. **Check/uncheck** which tracks appear in the plot — without the workspace catalog tree growing into a data browser, and without the plot template silently becoming the only source of truth for “what is on screen”.
3. Switch the main view between **graphic** and **table** on the **same display set**, with virtualized table performance suitable for real log lengths.

Today: `workspace_tree` is **catalog-only** (well level); tracks come from **template → HostPresentation**; there is no per-well content tree and no host table mode wired to the same selection model (research baseline + ADR 0022/0024).

### In scope (first-ship)

- Single-well analysis page only.
- Well Content Tree (import source → displayable track leaves) with tri-state parents.
- Dual-layer: **Display Set** (checks) × **template** (layout/style).
- Scalar curves only in the tree (including AT10–AT90 as independent leaves).
- Graphic | Table mode switch; shared display set; virtualized table; selection linkage.
- Shell layout **variant A** (left dual tabs).

### Out of scope (this effort / first-ship)

See §11. Production implementation of this feature is **out of the wayfinder map** but **in** the follow-on epic derived from this spec.

---

## 2. Terminology

Stable terms (also in root `CONTEXT.md` under Well Log Visualization):

| Term | Meaning |
|------|---------|
| **Well Content Tree（井内容树）** | Per-selected-well inspector tree: **import source / logical dataset → displayable track leaves**. Separate from workspace catalog. |
| **Display Set（显示集）** | The set of checked track-leaf identities that participate in the current graphic and table views. |
| **Displayable Track Leaf（可显示井道叶子）** | A source-side displayable track instance with stable identity (first-ship: scalar curve instance). Not a template `BoundTrack` slot. |
| **Dual-layer composition（双层合成）** | Display Set chooses *what* is shown; plot template supplies layout/style for *matched* slots; unmatched checked leaves get default style. |
| **View Mode（视图模式）** | `graphic` \| `table` for the single-well main area; session-scoped per well; default `graphic`. |

Related existing terms: Whole-File Log Import, Canonical Curve Instance, HostPresentation (host multi-track presentation), Sampling Axis / Reference Depth (engine + ADR 0022).

---

## 3. Information architecture

**Locked in** [Grilling: 井内数据树的信息架构（井 → 数据 → 井道）](https://github.com/WindWang2/paleo-workbench/issues/333); **shell placement updated by** [Prototype: 单井数据树 + 图/表切换壳层线框](https://github.com/WindWang2/paleo-workbench/issues/338).

```
[Workspace catalog — navigation only]
  Workspace → Wells / Plots

[Well Content Tree — selected well; not catalog]
  <Import source / logical dataset>     ← data node (tri-state checkbox)
    ├─ <Displayable track leaf> ☑       ← always two levels, even if one leaf
    └─ …
```

Rules:

1. One successful import (e.g. one LAS) → one data node; a well may have several sources in parallel.
2. Always **two levels**; never collapse a single-track source to a lone leaf under the well.
3. Leaves = source displayable instances (stable ids), **not** template slots.
4. **Depth scale is not a tree node**; it is the shared vertical axis of the main view. Metadata (axis type, depth range, sample count) may appear on the data node.
5. Parent **tri-state** checkbox; truth is the leaf set.
6. Catalog vs content tree **separated** in the shell (see §7).

---

## 4. Visibility × template (dual layer)

**Locked in** [Grilling: 复选可见性与图版/布局的职责划分](https://github.com/WindWang2/paleo-workbench/issues/334).

| Layer | Owner | Responsibility |
|-------|--------|----------------|
| **Display Set** | Well Content Tree checkboxes | Which leaves participate in graphic + table |
| **Layout / style** | Plot template | Width, scale, color, order hints for **matched** mnemonics/slots |

**Compose rule:**

1. Start from checked leaves.
2. Matched template slot → apply slot style; unmatched → **default style** track.
3. Template never hides a checked leaf; tree never invents slot geometry without defaults.

**Defaults:** On first open / no remembered set → check only leaves the **current template can match** (e.g. `std-gr-rt-den` → GR, RT, DEN).

**Live:** Checkbox changes apply immediately (optional short debounce is an implementation detail).

**Empty set:** Empty canvas + guidance; do not force-check; do not silently restore template defaults.

**Template switch:** **Keeps** Display Set; restyles only. Optional explicit “reset checks to template matches” is allowed as a user action (prototype had this).

---

## 5. Data kinds matrix (first-ship)

**Locked in** [Grilling: 首期进树的数据种类范围](https://github.com/WindWang2/paleo-workbench/issues/335).

| Kind | Tree | Graphic | Table |
|------|------|---------|-------|
| **All scalar curves** (incl. AT10–AT90) | Independent leaves under import source; no group node for AT* | Curve tracks via dual-layer compose | Same Sampling Axis: `Depth \| columns…`; multi-axis split tables (ADR 0022) |
| Tops / intervals | **Not in tree** | Existing tops UI / markers | Separate tops tables if any (ADR 0022) |
| Lithology / patterns | **Not in tree** | Out of first-ship main path | Out |
| Imaging / array / waveform | **Not in tree** | Out | Out |

Example (A2):

```
A2.Las
  ☑ GR  ☑ RT  ☑ DEN  ☐ CAL  ☐ AT10 … ☐ AT90  ☐ …
```

---

## 6. Dual-view product contract

**Locked in** [Grilling: 图形/表格双视图产品契约](https://github.com/WindWang2/paleo-workbench/issues/336).

1. **Shared Display Set** — Graphic and Table share checks; mode switch does not change checks.
2. **Switch UI** — Single-well main toolbar / segmented control; **default graphic**; remember mode **per well within session**; no cross-session persistence for mode (first-ship).
3. **Table columns** — `Depth` + checked leaves; same Sampling Axis → wide table; different axes → **split tables** (tabs or stacked); no implicit resample in first-ship (ADR 0022). Depth column uses that table’s Reference Depth.
4. **Selection** — Bidirectional **semantic** selection (well + curve identity + Reference Depth / sample index; not screen Y) per ADR 0024; hover may be light/one-way first-ship; mode switch **preserves** Selection.
5. **Scope** — Single-well page only; correlation does not inherit this contract in first-ship.

---

## 7. Shell layout (prototype go A)

**Locked in** [Prototype: 单井数据树 + 图/表切换壳层线框](https://github.com/WindWang2/paleo-workbench/issues/338).

| Region | Content |
|--------|---------|
| **Left** | Dual tabs: **工区** (catalog) \| **井内容** (Well Content Tree for selected well) |
| **Center** | Toolbar **图形 \| 表格** + canvas or virtualized table; empty-set guidance |
| **Right** | Template list (style layer) + **read-only** derived “current display tracks” list |

Note: Early tree-IA text mentioned a right-hand panel; **shell decision is left dual tabs** (go A). Implement Qt against A; do not promote the HTML prototype.

**Asset:** `well-log-engine/apps/wellplot-desktop/well_log_workstation/prototypes/well-content-tree-shell.html`

---

## 8. Performance and degradation

**Locked in** [Grilling: 表格模式性能预算与交互降级](https://github.com/WindWang2/paleo-workbench/issues/337). Align spirit with ADR 0014 reference workstation; table budgets are product acceptance for the host table path.

| Topic | Requirement |
|-------|-------------|
| Virtualization | **Must** virtualize (on-demand Table Projection / `QAbstractTableModel` or equivalent). **Forbid** materializing a full-length wide float/`QVariant` buffer for the on-screen table. |
| Check / column change | Remap columns only; no full-table copy rebuild. |
| Clipboard | Materialize **selection only** (TSV/HTML). |
| Scroll | Steady-state P95 ≤ **16.7 ms** |
| Check or Graphic↔Table | Main path P95 ≤ **100 ms** |
| First enter table | P95 ≤ **300 ms** first paint; **≤ 1 s** must show shell/progress |
| Acceptance data | ≥ A2-scale (~1.5×10⁴ rows × ≥20 cols) and stress ≥ **1×10⁵ rows × 20 cols** (single axis) |
| Column count | No hard cap; horizontal on-demand; soft tip at **≥ 64** columns (incl. Depth); never auto-uncheck |
| Export | **Separate path** (may background); not on scroll hot path; default range = Display Set ∩ current table axis, full logical rows; fail without killing open table |
| Degrade | Immediate shell + progress; cancellable; optional “performance mode” (drop decorations); **never** silent row/col truncation; **no** decimated table (no implicit resample); on hard failure → error + graphic still usable |

---

## 9. ADR and code anchors

| Anchor | Role |
|--------|------|
| [ADR 0022](../../adr/0022-virtualized-table-projections.md) | Virtualized table projection; same-axis wide table; split multi-axis; no implicit resample; export formats |
| [ADR 0024](../../adr/0024-shared-semantic-selection.md) | Shared semantic Selection Set graph↔table |
| [ADR 0014](../../adr/0014-performance-acceptance-baseline.md) | Reference workstation / frame-time spirit |
| Research | `docs/research/2026-08-05-well-track-tree-and-table-mode-baseline.md` |
| Host shell | L-layout: catalog tree, template list, track list, multi-track canvas / engine surface |
| Host presentation | Template apply → multi-track `HostPresentation` |
| Prior product fix | Default multi-track template (`std-gr-rt-den`); no silent multi→single GR fallback (PR #330) |

No new product ADR batch for this feature unless implementation discovers a new architectural fork.

---

## 10. Acceptance checklist

### Product

- [ ] Catalog remains well-level; Well Content Tree is separate (left **井内容** tab).
- [ ] Tree is always import source → leaves (two levels); AT* are independent leaves.
- [ ] Parent tri-state checks batch-toggle children; leaf set is source of truth.
- [ ] Default checks = current template matches only.
- [ ] Checking a non-template curve adds a default-styled track immediately.
- [ ] Switching template does **not** change checks (restyle only).
- [ ] Empty Display Set → empty main view + guidance (not an error).
- [ ] Graphic and Table share Display Set; mode switch does not alter checks.
- [ ] Mode control on single-well main area; default graphic; per-well session memory.
- [ ] Table columns = Depth + checked leaves; multi-axis split; no implicit resample.
- [ ] Selection bidirectional semantic (graph↔table); mode switch keeps Selection.
- [ ] Tops/lithology/imaging not in first-ship tree.
- [ ] Correlation page not required to implement this contract.

### Performance / table

- [ ] On-screen table is virtualized; no full wide buffer materialization.
- [ ] Meets latency budgets in §8 on acceptance + stress data sizes.
- [ ] ≥64 columns soft tip; checks not truncated.
- [ ] Export path independent of scroll; failures recoverable.
- [ ] Degrade/cancel/error paths user-visible; graphic remains usable on table failure.

### Spec completeness (meta)

- [ ] Another agent can split tracer-bullet tickets without rediscovery of tree placement, dual-layer rules, table columns, virtualization, or first-ship kinds.

---

## 11. Non-goals and open items

### Non-goals

- Production code inside the wayfinder map (done separately).
- Full plugin SDK for custom tree node types.
- ResForm private project 1:1 compatibility.
- Seismic / geomodel primary workflows.
- Correlation dual-view / shared Well Content Tree (second phase candidate).

### Open items (do **not** block first-ship epic start)

| Item | First-ship default if needed | Blocks first ship? |
|------|------------------------------|--------------------|
| Display Set cross-session persistence | Session-only (like View Mode); no workspace write | **No** |
| Track layout algorithm (widths, stacking, color clash beyond template defaults) | Reasonable sequential layout + template widths + default palette | **No** |
| Table vs plot PDF/SVG export UX details | Follow existing export menus; table export path separate when implemented | **No** |
| Engine multi-track parity with host under dual-view | Prefer engine when already preferred; host table path still required | **No** |
| Correlation reuses Well Content Tree | Out of first-ship | **No** |
| Non-scalar leaves (lithology, imaging) | Out of tree | **No** |

---

## 12. Decision index

| Ticket | Gist |
|--------|------|
| [Wayfinder map #331](https://github.com/WindWang2/paleo-workbench/issues/331) | Destination: implementable single-well tree + dual-view spec |
| [#332 Research](https://github.com/WindWang2/paleo-workbench/issues/332) | Host catalog-only; template→tracks; ADR 0022/0024 constraints |
| [#333 Tree IA](https://github.com/WindWang2/paleo-workbench/issues/333) | Source → leaves; two levels; tri-state; depth not in tree |
| [#334 Dual layer](https://github.com/WindWang2/paleo-workbench/issues/334) | Display Set × template; live; empty guide; template keeps checks |
| [#335 Kinds](https://github.com/WindWang2/paleo-workbench/issues/335) | Scalars only; AT* independent; tops/lithology/imaging out |
| [#336 Dual view](https://github.com/WindWang2/paleo-workbench/issues/336) | Shared set; switch UI; columns/split; selection; single-well |
| [#337 Perf](https://github.com/WindWang2/paleo-workbench/issues/337) | Virtualize; budgets; soft column tip; export path; degrade |
| [#338 Prototype](https://github.com/WindWang2/paleo-workbench/issues/338) | go A: left dual tabs |
| [#339 Deliverable form](https://github.com/WindWang2/paleo-workbench/issues/339) | This md + `/to-spec` issue; CONTEXT terms at spec time |

---

## Appendix A — Testing seams (for `/to-tickets` / implement)

Prefer **few high seams**, external behavior only:

1. **Display-set composition (primary pure seam)**  
   Inputs: ordered leaves with stable ids + mnemonic/slot hints, checked set, current template.  
   Outputs: ordered styled track descriptors for `HostPresentation` / canvas (matched style vs default).  
   Cases: default checks; check extra curve; uncheck template match; empty set; template switch keeps checks.

2. **Table projection (virtualized)**  
   Inputs: display set + sampling axes.  
   Outputs: column map; row count; `data(row,col)` without full materialization; multi-axis → multiple projections.  
   Cases: same-axis wide table; two axes → two tables; selection ids round-trip.

3. **Shell wiring (thin Qt)**  
   Left tabs catalog vs content; mode switch; empty guidance; checks drive both modes.  
   Prior art: `well-log-engine/apps/wellplot-desktop/tests/test_well_log_workstation_shell.py`, `well-log-engine/apps/wellplot-desktop/tests/test_well_log_workstation_templates.py`.

Avoid: asserting QPainter/GL pixels as primary acceptance; testing private widget trees without behavior.

---

## Appendix B — `/to-spec` template mapping

| Template section | Where in this doc |
|------------------|-------------------|
| Problem Statement | §1 |
| Solution | §§3–8 summary |
| User Stories | Tracker issue body (extensive list) |
| Implementation Decisions | §§3–9, Appendix A |
| Testing Decisions | Appendix A, §10 |
| Out of Scope | §1, §11 |
| Further Notes | §12, open items |
