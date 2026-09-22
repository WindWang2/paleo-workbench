# Python Retirement — Review Findings

Two independent review passes after implementation (read-only review
agents, evidence-backed findings), plus the verification-loop findings from
local build/test. All P0/P1 items were fixed before the PR; dispositions
below.

## Review A — retirement correctness (P0=0 P1=2 P2=5 P3=4)

| # | Sev | Finding | Disposition |
|---|---|---|---|
| A1 | P1 | perf-gate executed the archived `bench_interpolation` and (mis-classified by me as "stays") `render_engine_benchmark.py` | **Fixed** — both benchmark legs retired; the gate keeps the geoviz slow perf suite; ledger 02 corrected |
| A2 | P1 | ledgers 05/08 untracked; 06/07/09 missing; dangling 06 reference | **Fixed** — all committed; ledgers 00-09 complete |
| A3 | P2 | retirement manifest stale after amendment commits | **Fixed** — regenerated from the final tree (schema 2, 1760 renames, amendments recorded) |
| A4 | P2 | doubled archive path segments (`scratch/scratch`, `examples/examples`) | **Fixed** — de-doubled via git mv; manifest paths match |
| A5 | P2 | `qgis_support.require_qgis()` imported the archive without the path set (collection-time import) | **Fixed** — shim hoisted to module level |
| A6 | P2 | archived suite lost its `tests.qgis_support` (restored to active tree) | **Fixed** — archive-local copy with archive-relative path |
| A7 | P2 | archived conftest `_assert_bridge_origin` computed repo root one level short | **Fixed** — `parents[3]` |
| A8 | P3 | ledger numeric drift (P1 count, sums, 826 vs 828, conftest-copy semantics) | **Fixed** |
| A9 | P3 | stale ci.yml `--ignore` flags + #1429 narration | **Fixed** |
| A10 | P3 | pyproject dev deps justified by archived tests; stale marker comments | **Fixed** — setuptools/scikit-image dropped; comments refreshed |

## Review B — native purity / packaging isolation (P0=0 P1=1 P2=4 P3=4)

| # | Sev | Finding | Disposition |
|---|---|---|---|
| B1 | P1 | `well-log-engine.yml` still ran the archived `test_welllog_engine_native_integration.py` (permanently red) | **Fixed** — leg + two serving steps removed |
| B2 | P2 | `icon_file()` resolved `icons/` but the staged set lives under `ui/assets/icons/`; `tree-branch-opened.svg` name never existed | **Fixed** — prefix + name corrected; test fixture follows; the never-existed `map/tree-attribute-table.svg` recorded as K10 |
| B3 | P2 | closure_agent oracle generator half-detached (segment-joined retired-root paths) | **Fixed** — all paths point at the archive |
| B4 | P2 | `build-osgeo.ps1` bypassed the sanctioned shim | **Fixed** — imports `tools/oracle/_legacy_reference` |
| B5 | P2 | deploy tree staged no product resources | **Fixed** — deploy stages `share/paleo-workbench/resources`, launcher exports `PALEO_RESOURCES_DIR` |
| B6 | P3 | retirement-gate logic holes (literal-only pattern, narrow launcher scope, spoofable shim marker, env-only install check) | **Fixed** — normalized pattern, `scripts/` scope, comment-stripped markers, gate invoked with the install dir from run_package; deploy-tree check ordered after deploy |
| B7 | P3 | PwbInstall layout docs listed removed dirs | **Fixed** |
| B8 | P3 | stale CI narration + root-CMake "Python remains the production path" strings | **Fixed** — retirement-aware wording |
| B9 | P3 | pyproject relies on auto-discovery luck | **Fixed** — `[tool.setuptools] py-modules = []` |

## Verification-loop findings (build/test phase)

| # | Finding | Disposition |
|---|---|---|
| V1 | #1473 `plugin_loader.cpp` POSIX branch called `::dl_close` (the wrapper itself) — GCC rejects; MSVC never compiled that branch | Fixed (stacked fixup) |
| V2 | #1473 `workflow_install.cpp` consumes CONV-32 headers "in every shape" but the native-product closure did not build them | Fixed (stacked fixup): `PWB_BUILD_NATIVE_PRODUCT` now implies `PWB_BUILD_CONV_32` |
| V3 | #1473 `test_pid()` POSIX branch recursed infinitely (fault_lifecycle hang, mock_facies timeout); MSVC branch was correct | Fixed (stacked fixup) in both tests |
| V4 | `scan_python_runtime()` matched a bare `python` substring — the worktree's own name failed the product self-check | Fixed: library-path shapes; self-check 13/13 |
| V5 | First package run flagged `include/pwb/catalog/legacy_migration.hpp` (product header) via the too-broad `*legacy*` pattern | Fixed: `*legacy/python_reference*`; deploy-check ordering corrected |

## Residual P0/P1 count at PR time: **0 / 0**

Remaining P2/P3-class items are recorded in `08-known-limitations.md`.
