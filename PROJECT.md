# Project: Paleo Workbench (native C++ product + legacy Python track)

## Status banner (2026-09-22)

Paleo Workbench is a unified desktop scientific workstation for geological
mapping, well-log analysis, 3D seismic visualization, and spatial data science.

- **Production shell**: native C++ `pwb-platform` with ribbon five-workspaces.
- **Legacy track**: Python `paleo_workbench` (PySide6) — frozen for new UI
  features; still valuable as oracle and as a runnable legacy product until
  M12 entry switch.
- **Doc IA**: [`docs/README.md`](docs/README.md).

Older “core-convergence” Python-only project sheets are historical; do not
treat them as the live architecture map.

## Architecture

1. **Native host** — `apps/paleo_workbench_platform` wires catalogs, mapping,
   seismic, joint 3D, workflow stage actions, and the ribbon shell.
2. **Library mesh** — `libs/*` (see [`docs/architecture/module-map.md`](docs/architecture/module-map.md)):
   platform/runtime, data/catalog, mapping/cartography, science/viz, seismic,
   workflow/factors, UI, closure adapters.
3. **QGIS map stack** — vendored QGIS SDK for canvas, layer tree, editing,
   layout export paths used by the native product.
4. **Job / resource runtime** — `job_runtime` + workstation task center;
   Python-track ResourceGovernor (ADR 0064) remains the legacy authority.
5. **Provenance** — catalog versions/runs (ADR 0056); workflow interpretation
   and mapping workspace freshness stay fail-closed on stale inputs.
6. **Conversion discipline** — C++ kernels freeze Python oracles
   (`tools/oracle/*`); native product must not call back into Python at
   runtime.

## Feature inventory (product-facing, native-first)

Runtime truth for optional surfaces is `pwb-platform --capabilities` on your
build — the table below is a module map, not a guarantee every row is linked
in every preset.

| # | Feature | Native home | Notes |
|---|---------|-------------|--------|
| F1 | Ribbon five workspaces | `libs/ui_ribbon` + app install | Adopted on main (`fa9ba744`) |
| F2 | Project open/save/new | `libs/project`, catalog closure | `.paleo.json` + artifacts catalog |
| F3 | Data management workspace | `ui_pages_data`, ingest, catalog | Import plan → commit |
| F4 | QGIS map authoring | `libs/qgis`, `ui_composite` | Digitize / style / layer tree |
| F5 | Factor prepare (IDW/kriging/…) | `mapping_kernel`, `factor_fusion` / `factor_host`, app `closure_mapping_install` + `closure_workflow` | Oracle-backed kernels |
| F6 | Contour / facies products | `mapping_kernel` layer products | CONV-03 family |
| F7 | Composer / layout export | `mapping_document`, `layout_export`, `cartography` | Geographic graticule / unfinished items: see geo-viz `11-known-limitations.md`; open follow-up **#1473 is not merged** — do not treat as shipped |
| F8 | Seismic import + attributes | `seismic_io`, `seismic_attributes`, `seismic_viewer` | SEG-Y → PWBVOL / attribute chain |
| F9 | Well log / cross-well / well-tie | `visualization`, `well_science`, viz-b docks | WLE viewer stack optional capability |
| F10 | Joint well-seismic 3D | `geo3d_viz`, `ui_wellseis` | Fence / stratal / analysis seams |
| F11 | Validation / QC / review | `ui_review`, `closure_review` | Review ≠ pass |
| F12 | Workflow stage actions | `ui_workstation`, `workflow_*`, app `workflow_install` | Governed stage dispatch |
| F13 | Command palette / shortcuts | `ui_shell` CommandRegistry | Shared with ribbon |
| F14 | Legacy Python workstation | `paleo_workbench/` | No new production UI path |

## Milestones (conversion ladder — summary)

See [`docs/development/cpp-conversion-main-plan.md`](docs/development/cpp-conversion-main-plan.md)
for the full M1–M12 ledger. Snapshot interpretation:

| Band | Meaning at 2026-09-22 |
| --- | --- |
| M1–M5 | Platform / data / seismic entry paths delivered; entry-*switch* still gated |
| M6–M10 | Large kernel + UI swarm body landed into `libs/` + app installs |
| GeoViz closure | Native product runtime treated as closed for declared capabilities on the closure SHA; unfinished items listed explicitly |
| Ribbon M0–M6 | Adopted as production shell on `main` |
| M12 | Default packaging entry still Python until switch review blockers clear |

## Interface contracts (native)

- **Catalog**: single repository rail; RAW immutability; versioned artifacts
  under `<project>.artifacts/…`.
- **Stage**: `ProjectSession::mapping_stage()` is the only write authority for
  facies_calibration / constraint_factor / integrated_compilation.
- **Commands**: one `QAction` / CommandRegistry identity per user command.
- **Jobs**: cooperative cancel via job runtime; UI must not `start()` an owner
  that still reports running (see open stability issues).
- **Capabilities**: `pwb-platform --capabilities` is the runtime feature
  probe; do not invent “supported” from docs alone.

## Code layout

```
apps/paleo_workbench_platform/   # pwb-platform host
libs/                            # 63 C++ libraries
paleo_workbench/                 # legacy Python product + domain oracle
tools/oracle/                    # fixture generators
native/                          # bridges + vendored QGIS build tree
docs/                            # see docs/README.md
tests/                           # pytest (Python) + tests/cpp (CTest)
scripts/cpp-migration/           # gates, resource admission, deploy helpers
geo-viz-engine/ well-log-engine/ # submodules
```

## Documentation refresh

Ledger for the 2026-09 documentation IA refresh:
[`docs/development/project-documentation-refresh-2026/`](docs/development/project-documentation-refresh-2026/).
