# Task Plan — Professional Workstation UI/UX V7 (feat/workstation-ux-v7)

## Goal
Converge Paleo Workbench into a high-density, context-driven, visually unified
professional geoscience workstation (QGIS + Petrel/Kingdom + VS Code reference).
Focus: UI beauty, UI-function matching, when tools appear/are enabled, QGIS shell
consistency. UI must truthfully present what the system can do, explain why not,
and map geological context to tools/panels/inspector/status.

HARD EXCLUSIONS: no 100GB seismic anything; no QGIS C++ branch overhauls (adapter
seams only); no second domain authority; no fake backends/silent fallbacks.

## Current Phase
PHASE 0 (setup) — COMPLETE. PHASE 1 (audit) — COMPLETE → docs 00.
Next: M1 contextual command surface.

## Phases (milestones; each = atomic commits + tests + doc updates)
- [x] PHASE 0: worktree `.worktrees/workstation-ux-v7` branch feat/workstation-ux-v7
      off main db21f6cf; submodules local-clone init; uv venv cp312 + editables;
      native pyds copied (cp312); baseline test run (see progress.md)
- [x] PHASE 1: Full UI audit (5 parallel explore agents) → findings.md + 00-baseline.md
- [ ] PHASE 2: Docs 01-target-state / 02-architecture / 03-decisions (before code)
- [x] M1: Context model V7 — ToolContext/ToolAvailability/QgisCapabilitySnapshot/
      LayerCapabilitySnapshot/LayerPresentationState typing seams + adapters;
      UIContextService extension (active layer detail, dirty, selection, degraded)
- [x] M2: Availability matrix (§4 phase1/2/3 × layer kind/role × editing) + disabled
      reasons everywhere (§5); kill MappingPage second authority (shared evaluation);
      unify 3 stage vocabularies; MapActionController reason plumbing
- [x] M3: Toolbar/menu IA (§6): TOOL_GROUPS regroup done; dead actions
      reachable; compact/overflow deferred to M7 (narrow-screen work)
- [x] M4: Layer Tree V7 (§7): decorations (dirty/stale/error/reviewed/frozen/
      published/missing/degraded), group aggregates from group_summary, hover,
      locate, stage-switch state preservation, no full rebuild
- [x] M5: Inspector V7 (§8): typed layer/feature/factor-raster/mapproduct sections
      consuming real domain data
- [x] M6: Visual convergence (§9): fix RED ratchet; migrate 44 snapshot files to
      style.bind/QSS; emoji→SVG; status vocab unification; badge/state adoption;
      new ratchets (font-size, fixed-width, status-map import lint)
- [x] M7: Layout (§10): hub force-float legacy resolution, dead pages/presets/
      placeholders removal, 1366×768 narrow handling
- [x] M8: QGIS UX (§11): capability-gated entries (Style Manager production entry,
      CRS entry), consistent unavailable/degraded semantics
- [x] M9: Task/Agent UX (§12): cancelling/slot/retry presentation honesty
- [x] M10: Accessibility/DPI/keyboard (§13): accessibleNames, focus chain, shortcut
      registration unification, DPR
- [x] M11: Visual QA V7 (§14): new states + 1366×768/2560×1440 + theme coverage +
      semantic assertions
- [x] M12: Performance (§17): differential updates verified, structural bounds
- [x] M13: Review rounds ×3 + P0/P1 fixes with regressions (§18)
- [x] M14: Docs 04–08 final sync, PR to main (§19)

## Decisions (locked so far)
1. All UI-side: no native/qgis_render_bridge C++ changes; capability via adapters.
2. Keep CommandRegistry + StageToolProfile + UIContextService as authorities — extend,
   do not create parallel systems. Unify vocabularies BY DERIVATION, not by new tables.
3. Availability truth = pure evaluation function over ToolContext (testable without Qt
   where possible); surfaces (toolbar/palette/menu/status) all render its output.
4. Dead code found in audit gets deleted with tests updated (not left hidden).
5. Planning files tracked in-repo per convention; durable docs in
   docs/development/workstation-ux-v7/.

## Blocked Items
(none)

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| (see progress.md session log) | | |

## Environment facts
- Worktree: C:\Users\wangj.KEVIN\projects\paleo-workbench\.worktrees\workstation-ux-v7
- Windows Git Bash; uv 0.10.9; venv .venv cp312 (project pins >=3.12,<3.13)
- Native pyds copied from main checkout (ABI-compatible cp312)
- qgis_render_bridge NOT built (as on main) — qgis-marker tests skip; fallback path
  is the verified surface. QGIS 4.2.0 exists at C:/Program Files/QGIS 4.2.0 if ever
  needed; building the bridge is OUT of scope for V7.
- Run UI tests: QT_QPA_PLATFORM=offscreen .venv/Scripts/python.exe -m pytest ...
