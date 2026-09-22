# 01 — Findings

## Code state (mastered for this refresh)

- Single app: `apps/paleo_workbench_platform` → `pwb-platform`.
- 63 libraries under `libs/`, grouped in `docs/architecture/module-map.md`.
- ~991 `.cpp` / ~895 `.hpp` under libs+apps; ~678 Python modules under
  `paleo_workbench/`.
- CMake presets: `linux-native-product`, `windows-msvc-native-product`,
  `native-product-smoke`, plus conversion/developer presets.

## Module boundaries

- Qt-free cores vs `ui_*` / app install seams (documented in module map).
- Single catalog rail; stage authority on `ProjectSession`; shared commands.

## C++ conversion reality

- Native product runtime is real and Python-free in its closure (geo-viz
  closure docs).
- Packaging default entry still Python per `cpp-entry-switch-review.md`.
- Ribbon adoption is on `main`; plan file had drifted to “草案” — corrected.
- Unfinished migration items remain listed in geo-viz `11-known-limitations.md`;
  open follow-up `#1473` at refresh time — docs point readers to re-check.

## Doc IA gaps fixed

| Gap | Fix |
| --- | --- |
| No docs index | `docs/README.md` |
| README Python-first | rewrite dual-track |
| PROJECT.md core-convergence only | rewrite native-first |
| CONTEXT.md silent about C++ | dual-track banner (landed in follow-up audit commit; verify file header) |
| CLAUDE.md map-stack Python-only | native + legacy split |
| No module map | `docs/architecture/module-map.md` |
| No conversion snapshot | `docs/development/cpp-conversion-status.md` |
| Ribbon plan status stale | status line → adopted on main |


## Follow-up audit (2026-09-22)

Documentation-to-code audit under `review/` corrected: CONTEXT dual-track banner
was claimed here before it existed; banner is now required in CONTEXT.md.
See `review/review_findings.md` for the full finding list and fixes.
