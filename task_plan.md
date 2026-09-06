# Task Plan — Scientific Interpretation & Algorithm V6 (feat/scientific-interpretation-v6)

## Goal
Make Paleo Workbench scientifically trustworthy across well logs, multi-well
correlation, map/well/seismic coordinate linkage, small/medium seismic
interpretation, geological constraints, interpolation, single-factor maps,
multi-factor synthesis, geological mapping, uncertainty/QC/provenance, and
Harness scientific actions.

Primary rule: a result must never look scientifically valid when an input
unit, identity, null convention, coordinate convention, geological
constraint, calibration, or algorithm capability was actually missing or
ignored. Prefer explicit unavailable/degraded/unsupported over silent
approximation.

HARD EXCLUSION: no 100GB seismic volume support/benchmark/optimization.

## Current Phase
PHASE 1 — Scientific audit (A–Q) → docs/development/scientific-interpretation-v6/00-baseline.md

## Phases
- [ ] PHASE 0: Setup — worktree `.worktrees/scientific-interpretation-v6`,
      branch `feat/scientific-interpretation-v6` off main (295fabc3),
      submodules geo-viz-engine (5e03beba) + well-log-engine (f845e7ab) init,
      uv venv (cp312) + geoviz editables; baseline test run
- [ ] PHASE 1: Scientific audit A–Q (parallel) → 00-baseline.md
- [ ] PHASE 2: Well scientific contract V2 (identity/depth-domain/unit/null
      invariants; §2–4) + tests
- [ ] PHASE 3: Well identity/correlation duplicate-name correctness +
      registry scale O(W + N log W) (§5–6)
- [ ] PHASE 4: well-log-engine gap-aware curves/parity (§7, submodule branch
      if engine changes needed)
- [ ] PHASE 5: Coordinate/calibration fail-closed chain + SEG-Y scalar/
      geometry unification (§8–9)
- [ ] PHASE 6: Method × Constraint capability matrix + result diagnostics
      (§10)
- [ ] PHASE 7: Kriging V2 (anisotropy, diagnostics, CV, LOO) (§11)
- [ ] PHASE 8: Constrained IDW audit + interpolation evaluation workbench
      (§12–13)
- [ ] PHASE 9: Factor map contract + contour QA + fusion V2 + MapProduct
      gate (§14–17)
- [ ] PHASE 10: QC first-class model + Harness scientific actions (§18–19)
- [ ] PHASE 11: Performance + full test matrix (§20–21)
- [ ] PHASE 12: 3 review rounds + fixes (§22)
- [ ] PHASE 13: Docs 00–13 (§23), commits, submodule bumps, PR (§24)

## Decisions (locked)
1. Do NOT replace existing systems (catalog, engines, harness, mapping V5) —
   converge and harden.
2. Unknown unit/CRS/null = unknown; never guess; typed diagnostic or refusal
   when semantics depend on it.
3. Stable IDs, never display names, identify wells/curves everywhere.
4. RAW immutable; corrections produce DERIVED + DataRun.
5. No fake barrier kriging; unsupported = reported unsupported.
6. 100GB seismic explicitly out of scope.
7. Windows/GitBash environment; reuse root checkout's native builds only if
   ABI-compatible (cp312); native rebuilds bounded (CMAKE_BUILD_PARALLEL_LEVEL=2).

## Blocked Items
(none)

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| well-log-engine submodule network clone failed | git submodule update --init --reference | manual local clone from main checkout + checkout gitlink commit — OK |

## Environment facts
- Worktree: C:\Users\wangj.KEVIN\projects\paleo-workbench\.worktrees\scientific-interpretation-v6
- Windows, Git Bash; uv 0.10.9; project pins CPython >=3.12,<3.13
- Root checkout .venv = cp312 (pytest 9.1.1) but editable installs point at
  MAIN checkout — never use it for worktree tests; use worktree .venv
- Native modules: check native/ + geo-viz-engine builds; fallback paths exist

## FINAL STATUS (2026-09-07)
ALL PHASES COMPLETE.
- PHASE 0–13 done; 14 superproject commits + 4 geo-viz-engine submodule
  commits on feat/scientific-interpretation-v6 (both repos)
- 3 review rounds run (scientific/architecture/adversarial); all P0/P1
  findings fixed with regression tests (f7359415 + engine 40ebd168)
- docs/development/scientific-interpretation-v6/ 00–13 complete
- 100GB seismic excluded (program boundary honored)
