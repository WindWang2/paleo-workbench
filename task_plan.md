# Task Plan — Data & Runtime Foundation V6 (feat/data-runtime-foundation-v6)

## Goal
Repository-scale program: converge catalog/runtime/project persistence into a
transactional, lazy, crash-safe foundation for 100k–500k entities / 10k wells /
multi-GB payloads / long background jobs. Hard exclusion: NO 100GB seismic
support/benchmarking (small/medium fixtures only).

## Base
- main @ 295fabc3; worktree .worktrees/data-runtime-foundation-v6, branch
  feat/data-runtime-foundation-v6
- Test env: main checkout .venv (Python 3.12.13, pytest 9.1.1, PySide6, offscreen);
  run pytest FROM WORKTREE ROOT so pythonpath "." resolves to worktree code.
  pytest 9: use explicit `tests/...` args (geo-viz testpaths absent in
  worktree unless submodules initialized).

## Hard constraints (owner-locked)
1. DataCatalogService remains the public lifecycle authority.
2. No raw SQLite exposure to UI/business code.
3. No process-wide lock across multi-GB IO.
4. Preserve valid existing contracts (RAW/DERIVED/... semantics, pagination,
   lineage/DataRun, ResourceGovernor, TaskScheduler, OwnedWorkerJob, Harness 2.0,
   project save/reopen, missing/relink, portable packaging).
5. Main stays read-only; all work on branch.
6. No 100GB seismic work.

## Phases (milestone commits per prompt §18)
- [x] PHASE 0: Setup — worktree, branch, planning files, baseline test run
- [x] PHASE 1: Initial audit (subsystems A–L, parallel agents) + issue mapping
- [x] PHASE 2: 00-baseline.md (d67c4639)  (commit 1: audit/baseline)
- [x] PHASE 3: Lazy catalog — SQLite indexed repository under DataCatalogService;
      project-open <500ms to responsive shell at 100k  (commit 2)
- [x] PHASE 4: Transaction/revision model — BEGIN IMMEDIATE/CAS, typed conflicts,
      no last-writer-wins  (commit 3)
- [x] PHASE 5: Payload registration protocol (PREPARE..PUBLISH) + GC lease/coord
      (commit 4)
- [x] PHASE 6: Working-copy state machine  (commit 5)
- [x] PHASE 7: Project open/save/backup/recovery decision table  (commit 6)
- [x] PHASE 8: Runtime session generation + real cancellation  (commit 7)
- [x] PHASE 9: ResourceGovernor convergence (OMP/BLAS/env mutation removal)  (commit 8)
- [ ] PHASE 10: Lineage/DataRun atomicity + path identity/relink fail-closed  (commit 9)
- [ ] PHASE 11: Scale fixtures + benchmarks (100k/500k/10k wells)  (commit 10)
- [ ] PHASE 12: 3 review rounds (data-correctness; concurrency/arch;
      perf/adversarial/recovery) → fix P0/P1 + relevant P2  (commit 11)
- [ ] PHASE 13: Docs 00–11 complete; PR to main with full evidence

## Current Phase
PHASE 8 (session generation + cancellation)

## Decisions (locked — do not revisit)
(none yet beyond hard constraints)

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| git check-ignore .worktrees NOT_IGNORED | 1 | Pattern is `.worktrees/` (dir form); matches once dir exists — safe |

## Notes
- There is a sibling worktree .worktrees/workstation-ux-v6 (parallel UX task) — DO NOT TOUCH.
- Planning files (task_plan/findings/progress.md) are git-tracked; overwrite in
  worktree is expected, gets committed on the branch.
