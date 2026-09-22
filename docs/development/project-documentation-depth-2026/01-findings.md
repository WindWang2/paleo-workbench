# 01 — Findings (pass-2, code mastered before writing)

## Ribbon (`libs/ui_ribbon` + app install)

- Spec builder `build_workspace_specs()` declares **58** `cmd(...)` rows across **5** workspaces.
- Each workspace has **exactly one** `CommandKind::Primary`.
- Middle three workspaces map to mapping stages; 数据管理 / 验证 use `std::nullopt` (must not rewrite stage).
- `apps/paleo_workbench_platform/ribbon_command_install.cpp` registers every id via `register_real` / `register_disabled`.
- **Effective** state after install (last registration wins): **36 real / 22 disabled** at baseline `470d7500`.
- Several ids are registered real and then re-registered disabled in the same TU — docs record the **effective** state and call out the pattern so agents do not trust the first hit from `rg`.

## Modules (`libs/*`)

- **63** libraries on disk at baseline.
- Qt vs Qt-free is visible from each lib's `CMakeLists.txt` link lines.
- First `#` comment line in CMake is a usable one-line purpose for most libs.
- Shallow map (`module-map.md`) stays the boundary/rules doc; deep map is the inventory.

## App install seams

- Composition-root TUs live under `apps/paleo_workbench_platform/*_install*`.
- Families: `ribbon_*`, `stage_flow_*`, `workflow_*`, `closure_*`, `m5_*`, `viz_*`, well/joint presenters.
- Banners document honest-skip / no second authority contracts.

## Doc gaps closed this pass

| Gap | Fix |
| --- | --- |
| No ribbon id catalog | `docs/architecture/ribbon-command-catalog.md` |
| Module map only grouped | `docs/architecture/module-map-deep.md` (63/63) |
| Install seams undocumented | `docs/architecture/app-install-seams.md` |
| Pass-1 IA unaware of depth docs | `docs/README.md` + `module-map.md` links |
| No pass-2 ledger | this directory |
