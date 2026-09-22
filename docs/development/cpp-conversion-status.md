# C++ conversion reality — snapshot

**Snapshot date**: 2026-09-22 (Asia/Shanghai).
**Code baseline**: `18c674ef` (`origin/main`).
**Method**: re-derived from tree layout, merged commits, and committed
closure ledgers — not from stale root README claims.

## One-sentence status

The **native product runtime** (`pwb-platform`) is the production C++ desktop
workbench (ribbon five-workspaces shell, QGIS map stack, catalog/workflow
closures, seismic/well/joint viz). Python remains a **legacy parallel product**
and the **oracle** for parity work; default *packaging* entry is still the
Python console script until the M5/M12 entry-switch blockers are cleared.

## Evidence anchors (do not paraphrase without re-checking)

| Claim | Evidence |
| --- | --- |
| Native executable | `apps/paleo_workbench_platform` → target `pwb-platform` |
| Product preset | CMake preset `linux-native-product` / `windows-msvc-native-product` (`PWB_BUILD_NATIVE_PRODUCT=ON`); root `cmake_minimum_required` **3.27**; Qt **6.8** via `find_package(Qt6 6.8 …)` |
| Ribbon shell on main | `fa9ba744` / merge `cebc9f0a` — `libs/ui_ribbon`, five workspaces |
| GeoViz product runtime closure | [`geoviz-cpp-final-closure/12-final-verification.md`](geoviz-cpp-final-closure/12-final-verification.md) — 248/248 CTest, 14/14 self-check, 20 hard capabilities (on that branch HEAD) |
| Python-free native closure | [`geoviz-cpp-final-closure/04-python-retirement.md`](geoviz-cpp-final-closure/04-python-retirement.md) |
| Conversion ladder | [`cpp-conversion-main-plan.md`](cpp-conversion-main-plan.md) (M1–M12) |
| Default entry not yet flipped | [`cpp-entry-switch-review.md`](cpp-entry-switch-review.md) |
| Known unfinished migration (as of #1454 ledger) | [`geoviz-cpp-final-closure/11-known-limitations.md`](geoviz-cpp-final-closure/11-known-limitations.md) items 1–6; follow-up PR `#1473` was open at snapshot time — re-check before repeating those gaps |

## Dual-track rules for writers

1. Say **native product** when you mean `pwb-platform`.
2. Say **legacy Python product** when you mean `paleo_workbench` / `paleo-workbench` console script.
3. Say **oracle** when Python exists only to freeze fixtures or parity.
4. Never imply the native binary `import`s geoviz or PySide.
5. `docs/development/**` ledgers are SHA-scoped; update or supersede them instead of silently editing history.

## Scale (tree, not “% complete”)

| Surface | Approx. size at snapshot |
| --- | --- |
| `libs/**/*.cpp` | ~991 |
| `libs|apps/**/*.hpp` | ~895 |
| `paleo_workbench/**/*.py` | ~678 modules |
| `libs/` libraries | 63 |
| ADRs under `docs/adr/` | 33 files |

Percent-of-files metrics are **not** the project’s completion oracle; user
flows + wiring + tests on a stated SHA are.
