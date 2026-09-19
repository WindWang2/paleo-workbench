# Scope ledger — C++ build / inventory / packaging / resource hardening

Branch: `cpp-build-packaging-hardening`
Base: `origin/main` at `ff67dcf3`
Worktree: `../worktrees/cpp-build-packaging-hardening`
Task family: **HY-4** — engineering hardening of the existing C++ conversion, not a new
product direction.

> Branch-name note: the task asked for `feat/cpp-build-packaging-hardening`. This environment
> cannot create nested git refs — `git branch feat/x` and `git update-ref refs/heads/feat/x`
> both report success while writing nothing, and any `a/b` ref is created for no branch. The
> branch is therefore the flat `cpp-build-packaging-hardening`. Branch naming is cosmetic here;
> every other rule (no work on `main`, own worktree, no reuse of another task's worktree) holds.

## 1. This branch is responsible for

| # | Area | Deliverable |
| --- | --- | --- |
| A | Migration inventory automation | `tools/migration/pwb_migration_inventory.py` + generated report |
| B | CMake feature graph | `cmake/PwbFeatures.cmake`, hoisted option declarations, dependency validation, feature summary, duplicate-`add_subdirectory` guard |
| C | Resource gate hardening | `scripts/cpp-migration/Invoke-ResourceGate.ps1`, `invoke-resource-gate.sh`, plus self-tests |
| D | Low-memory build presets | `CMakePresets.json` (`developer-fast`, `conversion-kernel`, `native-product-smoke`, `low-memory`, `windows-msvc`, `linux-ninja`) |
| E | Build artifact hygiene | `tools/verify/pwb_artifact_hygiene.py` + audit findings |
| F | Native packaging skeleton | `cmake/PwbInstall.cmake`, `pwb-diagnose`, install rules (opt-in) |
| G | Local verification driver | `tools/verify/pwb_local_verify.py` |
| H | Python dependency audit | `tools/migration/pwb_python_dependency_audit.py` |
| I | Developer documentation | `docs/development/cpp-building-and-verification.md` + this ledger |

## 2. This branch is explicitly NOT responsible for

* workflow business semantics, stage meanings, artifact maturity rules;
* QGIS UI, layer trees, docks, toolbars, cartography;
* Catalog schema, migration/versioning semantics, GC policy;
* scientific algorithms (interpolation, contouring, fusion maths);
* prediction algorithms, ONNX runtime behaviour, model packaging semantics;
* building any application service that the Product Closure direction owns;
* any other CONV slice's implementation.

Where a defect was found in one of those areas, this branch records it and either applies a
*minimal* fix that is required for the build graph to be coherent, or files it as a note. It
never absorbs another direction's work.

## 3. Boundary rules actually applied

1. **New files over edits.** The deliverables are almost entirely new files
   (`tools/`, `cmake/PwbFeatures.cmake`, `cmake/PwbInstall.cmake`, docs, self-tests).
2. **Minimal patch to shared files.** `CMakeLists.txt` changed by: one `include` +
   `pwb_resolve_feature_dependencies()` near the top, one `pwb_feature_summary()` at the end,
   and two `add_subdirectory` -> `pwb_add_subdirectory_once` substitutions for
   `libs/well_science`.
3. **`CMakePresets.json` is additive.** The three original CPP-A presets are byte-identical in
   behaviour; new presets use fresh `binaryDir` values under `build/presets/`.
4. **No business-logic edits.** No file under `libs/*/src`, `libs/*/include`, `tests/cpp/**`
   was modified by this branch.
5. **Packaging is opt-in.** `PWB_ENABLE_PACKAGING` defaults to `OFF`; with it off the
   generated build graph is identical to `main`.
6. **Defaults are preserved.** Hoisting a switch into `PwbFeatures.cmake` was only done where
   the declaration already existed in the root file, so no default value changed. Switches
   owned by a subdirectory (`PWB_BUILD_TOOLS`, the science/seismic test switches) are
   deliberately *not* re-declared and are reported read-only in the summary — re-declaring them
   was observed to flip `PWB_BUILD_TOOLS` from ON to OFF and break `tests/cpp/data`.

## 4. Interaction with the other parallel worktrees

Sibling worktrees observed on this machine while this branch was developed:

| Worktree | Branch |
| --- | --- |
| `paleo-workbench` | `main` |
| `paleo-workbench-geodata-qgis-v13` | `feat/geological-data-lineage-qgis-control-v13` |
| `paleo-workbench-geotopo-editor` | `feat/geotopo-editor` |
| `paleo-workbench-paleo-ui` | `feat/paleo-ui-workbench` |
| `paleo-workbench-vector-perf` | `feat/vector-perf-increment` |
| `worktrees/cpp-prediction-ai-runtime-closure` | `feat/cpp-prediction-ai-runtime-closure` |
| `worktrees/cpp-build-packaging-hardening` | this branch |

Conflict-avoidance measures:

* The shared build slot lock lives in the **common** git dir, so it coordinates across every
  worktree, including the ones owned by other directions.
* The resource gate was left backward compatible: existing flags and exit code `75` keep their
  meaning, so callers in other worktrees keep working.
* Shared root-file edits are deliberately tiny so that a rebase onto a moved `main` is trivial.

## 4b. Deliberate behaviour changes (kept minimal, each one intentional)

1. **`PWB_BUILD_CONV_04` now implies `PWB_BUILD_MAPPING_KERNEL`.** In `main` the switch was
   declared *after* `add_subdirectory(libs/mapping_kernel)`, so `-DPWB_BUILD_CONV_04=ON` without
   also passing `PWB_BUILD_MAPPING_KERNEL=ON` configured nothing at all — a silently dead switch.
   The implication table makes it work, matching how `CONV-03`, `CONV-05` and `CONV-17` behave.
2. **`libs/well_science` is added through a guard.** `CONV-09` and `CONV-11` both reach it; the
   guard makes the second `add_subdirectory()` a no-op instead of redefining its targets.
3. **No other default changed.** All 33 hoisted switches were compared against their original
   declaration sites; the defaults that already existed are reproduced exactly. Switches owned by
   a subdirectory are *not* hoisted, because doing so flips their real default (this was observed
   and fixed during development: `PWB_BUILD_TOOLS` went ON -> OFF and broke `tests/cpp/data`).

## 5. Findings recorded but not fixed here

These were discovered while hardening the build graph. They belong to other directions, so this
branch documents them instead of changing behaviour:

* `tests/cpp/data/CMakeLists.txt` binds `$<TARGET_FILE:pwb-inspect>` / `pwb-migrate` /
  `pwb-data-loop` into `add_test` unconditionally. Any configuration with `PWB_BUILD_DATA=ON`
  and `PWB_BUILD_TOOLS=OFF` fails at generate time. Left as-is: the fix is a guard on the
  test-registration side, which the data direction owns.
* `libs/data_suite/CMakeLists.txt` calls `project(PwbDataSuite ...)` even when included as a
  subdirectory of the root project. Unusual, and it is why the standalone entry and the root
  entry can drift apart. Not changed: it is the data direction's build entry.
* The three original CPP-A presets share one `binaryDir`, so switching between debug and
  release silently reuses the other's cache. The preset validator now warns about it; the
  presets themselves are left untouched for compatibility.

## 6. Local verification only

No online CI is waited on, no workflow file is added or modified, and no remote check is a
completion criterion. All acceptance evidence is local: configure, targeted build, `ctest`,
oracle fixtures, the resource-gate self-tests, and the generated reports.
