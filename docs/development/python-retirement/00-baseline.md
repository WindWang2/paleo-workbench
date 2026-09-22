# Python Retirement — Baseline

Date: 2026-09-22 · Executor: ZCode automated goal run · Mode: fully automated,
no human confirmation, online CI not awaited.

## Repository state at start

| Item | Value |
|---|---|
| `origin/main` | `18c674ef` (merge of `feat/ribbon-five-workspaces` lineage) |
| Base of this branch | `0936779e` = head of `codex/cpp-100-percent-final-closure` (PR #1473) |
| Branch | `chore/archive-legacy-python-product` (stacked on PR #1473) |
| Worktree | `../paleo-workbench-wt-python-archive` (independent; main workspace untouched) |

## PR / issue state checked at execution time

- **PR #1435** — *Close native product migration evidence and wiring* — **MERGED** 2026-09-21.
- **PR #1436** — *feat: 剩余转换全面推进* — **MERGED** 2026-09-21.
- **PR #1453** — *fix(native): post-migration deep audit and C++ product closure* — **MERGED** 2026-09-21.
- **PR #1454** — *feat(geoviz): complete Geo-Viz native C++ product conversion and final closure* — **MERGED** 2026-09-21.
- **PR #1473** — *feat(native): C++ 100% final closure — six product gaps closed + first full MSVC build of the tree* — **OPEN**, mergeable, base `main`, 60 files (+2381/−127). Closes the six remaining product gaps (catalog-project, workflow-runtime, science-prediction, data-preview, well-crosswell, joint3d) and records configure/build/CTest evidence on MSVC (503/503 build steps, CTest 223/250 — see its `06-test-evidence.md`).
- **PR #1474 / #1475** — documentation-refresh stack against `main` — open, orthogonal to this work.

## Case selection (per goal spec)

PR #1473 is **open** and this Python retirement depends on its final C++
closure → **Case B**: the cleanup branch is **stacked on the #1473 head**
(`codex/cpp-100-percent-final-closure`), the cleanup PR base will be set to
that branch, and no #1473 code is copied into this branch. The PR body will
state `Depends on #1473.`

## Migration truth at baseline

`docs/development/cpp-final-closure/migration-matrix.json` (schema 2,
committed on the base) covers **678** tracked `paleo_workbench/**/*.py`
modules:

| final_classification | modules |
|---|---|
| NATIVE_PRODUCT (wired + runtime-reachable) | 205 |
| NATIVE_LIBRARY_NOT_WIRED | 1 (`mapping/geological_pipeline/native_bind.py`) |
| PARTIAL_NATIVE | 77 |
| LEGACY_REFERENCE (unattributed, conservative) | 395 |
| **python_runtime_required** | **0** |
| **python_modules_packaged** | **0** |

Product entry: `pwb-platform` (C++/Qt, `apps/paleo_workbench_platform`),
with `--self-check` / `--capabilities` / `--diagnostics`. The native product
install tree is already audited Python-free by
`scripts/cpp-migration/final-closure-gate.sh` (`run_package` refuses any
`*.py` / `*.pyc` in the install/deploy trees).

## Headline inventory (full detail in 01-python-inventory.md)

Tracked Python files at baseline: **1897**.

| class | files |
|---|---|
| P1 legacy product implementation (+ its tests/launchers/benchmarks) | 1529 |
| P2 oracle / reference generators | 104 |
| P3 active development tooling | 18 |
| P4 compatibility bindings (pybind hosts) | 6 |
| P5 active test infrastructure | 77 |
| P6 scratch / one-off | 56 |
| P7 third-party / vendored | 107 (98 `third_party/qgis` keep + 9 `paleo_workbench/_vendored` archived with the package) |

Planned at baseline: **archive 1593** (`git mv`) + **1 conftest archive-copy**,
**keep 303**. Final tree after review amendments: 1760 renames, 0 deletions
(see 03/04 addenda and the manifest).
