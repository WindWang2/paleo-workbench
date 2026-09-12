# 00 — Overlap Audit (Workbench UX V11)

Date: 2026-09-12
Base SHA: `6c08fb7d` (`origin/main`, "Merge pull request #1253")
Branch: `workbench-ux-v11`
**Stacked on:** `origin/review-convergence-20260912` @ `6576e364` (open PR **#1277**, 8 commits ahead of `6c08fb7d`).

## Repository state survey

### Merged (not re-shipped by this goal)

| PR | Scope |
|---|---|
| #1251 | V9 adaptive workstation UI: dock framework, responsive policies |
| #1252–#1254 | V10 QGIS authoring UX / spatial layer platform / native vector authoring |
| #1247, #1246 | QTimer context binding fix, review defect repairs |
| #1240, #1233, #1235 | Prior workstation UX convergence waves (V6/V7/V8) |
| #1232 | Data & runtime foundation V6 (lazy catalog, transactional CAS) |

### Open PRs

| PR | Branch | Relationship to this goal |
|---|---|---|
| #1267 `v10-review-fixes` | fixes #1255–#1264 (action registry vocab, undo macros, locators, provider_writable, perf gates, health probe, paths, topo counts) | **Not touched.** Exclusive owner of #1255–#1264. This goal does not re-implement. Where my action-authority work touches `action_registry`, I layer on top of the merged main state and keep the parallel-vocabulary guard intact. |
| #1277 `review-convergence-20260912` | fixes #1265, #1266, #1268–#1276 | **Stacked on.** See below. |

### #1277 completed items — NOT re-implemented by this goal

The goal statement required checking whether #1277 already delivered:

1. **Virtual attribute table** — #1272: `composite_attribute_table.py` migrated from `QTableWidget × N×C` to a `QAbstractTableModel` virtual model (317-line rework), mirror deltas no longer serialize the full FeatureCollection. **Done in #1277.** This goal *generalizes* the pattern into a shared Model/View foundation module and adopts it for remaining item-per-cell surfaces; it does not re-do the #1272 fix.
2. **Theme lifecycle** — #1274: theme-manager lambda holding a destroyed `CompositeDocument` replaced by a QObject slot. **Done in #1277.** This goal's theme work is limited to semantic tokens / hard-coded color cleanup elsewhere.
3. **Snapping feedback** — #1276: snap config push failure no longer swallowed; checkbox returns to unchecked. **Done in #1277.**
4. **Data Manager 100k fix** — #1269: paged mode now uses `list_asset_identities` (3-column SQL) instead of full `list_assets()` hydration. **Done in #1277.** This goal builds the shared async/paged model layer around the existing `paged_asset_model.py` without rewriting its query path.

Also shipped by #1277 and owned there (not re-implemented): POSIX loader guard (#1265), tautological-assert cleanup (#1266), layer-switch session commit (#1268), sand-ratio unit fix (#1270), freeze pins into fusion (#1271), RAW editable snapshot (#1273), interpolation honesty (#1275).

### Open issues

- **#1278** (issue, not PR): 相图编辑迁移 QGIS 原生拓扑编辑 roadmap. Owned by the parallel **QGIS goal**; this goal does not migrate phase editing to native topology. UI-side affordances remain via the existing stage surfaces.
- #1230 (CI slow family) — CI concern, explicitly out of scope ("无需线上 CI").

### Parallel goals boundary (per goal §22)

| Area | Owner | This goal's stance |
|---|---|---|
| Catalog schema / DataVersion semantics / lineage schema | Data Fabric goal | Presentation adapters only; no schema changes. `data_page.py` business-model changes deferred to Data Fabric owner; I touch only view/model wiring. |
| QGIS tree authority / native editing / topology engine | QGIS goal | No behavior change in `composite_document.py` / `composite_editing.py` QGIS semantics; only shared state presentation (badges, availability reasons). |
| `native/qgis_render_bridge` C++ | QGIS goal | Untouched. |

## Base decision

`workbench-ux-v11` is based on `origin/review-convergence-20260912` @ `6576e364` rather than bare `main`, because four of the goal's foundation inputs (virtual attribute table, theme lifecycle, snapping feedback, paged Data Manager identity query) land in #1277 and re-implementing them was explicitly forbidden. If #1277 merges first, this PR's diff against `main` collapses to this goal's own commits. Base SHA for review purposes: **`6c08fb7d`** (merge-base with main).

## Existing foundations to preserve (goal §5) — confirmed present

- `ui/dock_framework.py`, `ui/dock_manager.py`, `layout_persistence.py` — dock framework (single, kept).
- `ui/tokens.py`, `ui/style.py`, `ui/theme.py` — design tokens & theme.
- `ui/workstation/ui_context.py` (153 lines, minimal), `ui/view_coordination.py` (920 lines) — context coordination to extend, not replace.
- `ui/command_registry.py`, action registry + `evaluate_tool` availability evaluator (single authority confirmed by #1277 review).
- `ui/pages/paged_asset_model.py` (704), `asset_table_model.py` (374) — Model/View seeds to generalize.
- `ui/workstation/inspector.py` (765), `task_center.py` (475) — Inspector/task surfaces to unify.
- QGIS native layer tree (`ui/native_layer_tree.py`) — authority respected.

No second dock framework, action system, or layer tree is created by this goal.
