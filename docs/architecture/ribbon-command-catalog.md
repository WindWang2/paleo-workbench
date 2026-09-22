# Ribbon command catalog (native product)

**Baseline**: `470d7500`.
**Sources (code is authority)**:
- Spec table: `libs/ui_ribbon/src/ribbon_spec.cpp` (`build_workspace_specs`, 58 `cmd(...)` rows)
- Install / wiring: `apps/paleo_workbench_platform/ribbon_command_install.cpp` (M4 `register_real` / `register_disabled`, last registration wins)
- Chrome library: `libs/ui_ribbon` (Qt-free core + Qt ribbon bar)
- Design authority: `docs/ui-redesign/qt-ribbon-workspaces-2026-09-21/`

## Rules frozen by the table

1. **Five workspaces, fixed order** — never reorder; tab indices are load-bearing.
2. **Exactly one Primary per workspace** — see workspace sections below.
3. **Middle three ARE stage views** — entering data-management / validation must not rewrite `ProjectSession::mapping_stage`.
4. **One CommandRegistry** — ribbon / palette / menus / shortcuts share ids; no parallel QAction sets (D4).
5. **Honest disable** — missing backends register disabled with a Chinese reason, never a fake enable.

## Summary

| Metric | Value |
| --- | --- |
| Commands in spec | **58** |
| Wired (`register_real`, effective) | **36** |
| Disabled placeholders (effective) | **22** |
| Spec ↔ install id coverage | **58 / 58** |

> Some ids are briefly registered real and then re-registered disabled in the same install TU (last wins). The **effective** column below reflects final process state after `ribbon_commands::install`.

Full per-command tables for all five workspaces (groups, ids, labels, kinds, overflow, effective install, notes) and the disabled inventory are maintained in-repo; regenerate from `ribbon_spec.cpp` + `ribbon_command_install.cpp` if they drift.

## How to re-verify

```bash
git rev-parse --short HEAD  # expect docs branch tip descended from 470d7500
rg -c 'cmd\(' libs/ui_ribbon/src/ribbon_spec.cpp
rg -c 'register_real\(|register_disabled\(' apps/paleo_workbench_platform/ribbon_command_install.cpp
```
