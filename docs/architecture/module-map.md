# Module map — native product boundaries

Baseline: `18c674ef` (2026-09-22). Counts are directory-level (`libs/` has
**63** libraries). The tree below is a **grouped sketch** of boundaries, not an
exhaustive per-library inventory — run `ls libs` on the SHA for the full set.
Qt-free domain logic lives under `libs/`; the host and product wiring live under
`apps/paleo_workbench_platform/` (`pwb-platform`).

## Runtime shape

```
pwb-platform (apps/paleo_workbench_platform)
├─ bootstrap / AppContext / MainWindow
├─ install_* seams (catalog, mapping, seismic, joint3d, ribbon, workflow, …)
└─ governed actions → libs/* services

libs/*
├─ platform / runtime     application, domain, job_runtime, platform_services,
│                         tool_policy, workspace, project
├─ data / catalog         catalog, data_suite, ingest, interchange, providers
├─ mapping / cartography  mapping_kernel, mapping_document, mapping_bind,
│                         cartography, layout_export, qgis
├─ science / viz          science_suite, science_service, algorithms,
│                         visualization, viz_charts, geo3d_viz, geomodel,
│                         well_science
├─ seismic                seismic_io, seismic_service, seismic_viewer,
│                         seismic_attributes
├─ workflow / factors     workflow*, prediction, factor_fusion, factor_host
├─ UI                     ui, ui_shell, ui_ribbon, ui_workstation, ui_stageflow,
│                         ui_controllers, ui_* pages/widgets/workers, …
└─ closure adapters       closure_workflow, closure_science, closure_review,
                          closure_agent
```

## Hard rules (product)

1. **Single catalog rail** — product writes go through the shared
   `workflow_runtime::CatalogRepository` / catalog closure adapter. No second
   catalog authority in the app.
2. **Qt-free cores** — numerical / persistence kernels stay Qt-free; Qt types
   stay in `ui_*`, `qgis`, and the app host.
3. **Honest failure** — missing inputs/services fail closed; no silent Python
   fallback in the native product (see geo-viz closure `04-python-retirement.md`).
4. **Command uniqueness** — Ribbon / menus / shortcuts / Ctrl+K share one
   `CommandRegistry` / governed `QAction` set (`libs/ui_ribbon` + shell).
5. **Stage authority** — mapping stage is `ProjectSession::mapping_stage()`;
   the middle three ribbon workspaces are views of that stage, not a second
   state machine.

## Python / submodules (outside the native closure)

| Path | Role today |
| --- | --- |
| `paleo_workbench/` | Legacy desktop product + domain oracle for conversion |
| `tools/oracle/` | Fixture generators that import real Python product code |
| `native/` | Optional pybind bridges / vendored QGIS build tree (product links the **C++** QGIS SDK, not Python QGIS) |
| `geo-viz-engine/`, `well-log-engine/` | Submodules; native product consumes C++ ports / WLE viewer stack, not the Python geoviz import graph |

## Where UI lives

| Concern | Library / host |
| --- | --- |
| Ribbon five workspaces | `libs/ui_ribbon` + app ribbon install |
| Workstation frame / docks / command palette | `libs/ui_shell`, `libs/ui_workstation` |
| QGIS map canvas / edit / layer tree | `libs/qgis`, `libs/ui_composite`, `libs/ui_map` |
| Data management pages | `libs/ui_pages_data`, `libs/ui_data_core` |
| Well / seismic / joint hosts | `libs/ui_wellseis`, `libs/seismic_viewer`, `libs/visualization` |
| Validation / review | `libs/ui_review`, `libs/closure_review` |

Design authority for the shell: `docs/ui-redesign/qt-ribbon-workspaces-2026-09-21/`.

## Deeper inventory (pass-2)

- Per-library table (63 libs, Qt vs Qt-free, CMake one-liner): [`module-map-deep.md`](module-map-deep.md)
- Ribbon command catalog (58 ids + effective install): [`ribbon-command-catalog.md`](ribbon-command-catalog.md)
- App install seams (`*_install` composition root): [`app-install-seams.md`](app-install-seams.md)
