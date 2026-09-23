# QGIS Native Python Runtime — Overlap Audit & File Lease Ledger

Date: 2026-09-23 · Branch: `feat/qgis-native-python-runtime` · Base: `192422c60`

## 1. Sibling worktrees (Prompts 1–6) and what each owns

All six live under `/home/kevin/projects/`, share the bare repo
`/home/kevin/projects/paleo_project/.bare`, and were checked with
`git fetch --all --prune` before this branch was created.

| Prompt | Worktree | Branch | PR | Owns (authority) |
|---|---|---|---|---|
| 1 — Shell/UI | `paleo-qgis-shell` | `feat/qgis-native-shell-convergence` | #1480 MERGED | `MainWindow`, docks, menus, toolbars, `QAction` registry |
| 2 — Layer/MapCanvas | `paleo-qgis-layers` | `feat/qgis-native-layer-control` | #1483 OPEN | `QgsProject` layer tree, `QgsMapCanvas`, editing session |
| 3 — Project/Data | `paleo-qgis-data` | `feat/qgis-native-data-management` | #1482 OPEN | project persistence, providers, data management |
| 4 — Processing/Task | `paleo-qgis-processing` | `feat/qgis-native-processing-task-framework` | none open | `QgsProcessing`, `QgsTask`, scheduler |
| 5 — Layout | `paleo-qgis-layout` | `feat/qgis-native-layout-composer-framework` | #1484 OPEN | `QgsLayout` / composer / publishing |
| 6 — QgsPlot | `paleo-qgis-plot` | `feat/qgis-native-plot-scientific-visualization` | none open | `QgsPlot` / `Qgs2DPlot` visualisation |

Stale, unowned: `/home/kevin/projects/paleo_project/worktrees/python-last`
(detached at `671ee4266`, 9 dirty files, contains a `build/` directory). It
predates the QGIS-native programme (base is PR #1310). **Not touched, not used
as a base** — recorded here only so it is not mistaken for prior art.

## 2. Lease ledger for this branch

### Owned exclusively by Prompt 7

| Path | Purpose |
|---|---|
| `libs/qgis_python/**` | thin `QgisPythonRuntime` host service, `iface` adapter, console/editor seams, diagnostics |
| `apps/paleo_workbench_platform/python_runtime_install.*` | startup wiring only |
| `apps/paleo_workbench_platform/python_actions_install.*` | action *seams* (registration into Prompt 1's action system, not the actions' authority) |
| `resources/python/**` | shipped Python resources (startup hooks templates, diagnostics assets) |
| `tests/qgis_python/**` | bootstrap / PyQGIS / iface / console / plugin / lifecycle tests |
| `docs/development/qgis-native-python-runtime/**` | this ledger |
| `third_party/qgis/src/python/**` | vendored `qgispython` closure (new import) |
| `third_party/qgis/python/**` | vendored PyQGIS bindings + built-in Python plugins (new import) |
| `third_party/qgis/UPSTREAM.md` | provenance update for the extension |

### Shared — touch only with an explicit seam, never as authority

| Path | Owner | Prompt 7's permitted use |
|---|---|---|
| `native/qgis_render_bridge/CMakeLists.txt` | build owner | flip `-DWITH_PYTHON`/`-DWITH_BINDINGS` to `ON` behind a new `PALEO_WITH_QGIS_PYTHON` option; no other semantics changed |
| app startup / bootstrap | Prompt 1 | call the runtime install hook; do not redesign bootstrap |
| `QgsApplication` init / QGIS bootstrap | shared | add Python init *after* the existing init order; never re-create the application |
| packaging / install scripts | build owner | ship `qgispython`, bindings, plugin/script dirs; no new Python distribution |

### Forbidden — no edits on this branch

`main_window.*` internals, `MapSession` internals, project/data core,
processing scheduler core, layout core, plot core. Python must **read through**
to the same live objects; where a seam is missing, this branch files the gap as
a documented finding rather than editing the owner's core.

## 3. Overlap risk register

| # | Risk | Mitigation |
|---|---|---|
| R-1 | #1482/#1483/#1484 are open and move the very objects `iface` must expose (`QgsProject`, layer tree, `QgsLayout`) | the `iface` adapter resolves those objects **lazily at call time** from `QgsProject::instance()` and the shell's accessor seam, never caching a pointer captured at init |
| R-2 | Vendored-closure extension (`third_party/qgis/**`) could collide with a parallel branch re-vendoring QGIS | extension is additive (new directories only) + `UPSTREAM.md` provenance entry; no existing file content changes |
| R-3 | Flipping `WITH_BINDINGS` changes the QGIS build for every consumer of the bridge | gated behind `PALEO_WITH_QGIS_PYTHON` defaulting to `OFF`, so the existing build is bit-identical until enabled |
| R-4 | Legacy Python product stack could be re-animated by accident | `docs/development/python-retirement/` is treated as settled; nothing from `legacy/**` is imported; gate #7 is checked explicitly in `14-final-verification.md` |
| R-5 | System QGIS 4.2.2 / PyQGIS on this machine looks like a shortcut | explicitly forbidden by the vendored-source policy; the capability report records it as "present but unusable" |

## 4. Decision recorded for this run

**Extend the vendored closure** (upstream `src/python/` + `python/` from tag
`final-4_2_0`) rather than importing the system PyQGIS. Rationale: the
vendored-source policy is a hard rule, the system copy is a different patch
release (4.2.2 vs 4.2.0), and only an in-tree closure keeps ABI agreement with
the vendored `qgis_core`/`qgis_gui`. Cost is accepted: it adds an upstream
bindings build to the bridge.
