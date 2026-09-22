# 12 — Final verification

All numbers below are from the **final branch HEAD** (worktree clean;
`git status` verified before each step). Environment: Linux/gcc16, system
Qt 6.11.2, vendored QGIS SDK (WITH_PYTHON=OFF), CTest with the documented
env (`QT_QPA_PLATFORM=offscreen`, `LD_LIBRARY_PATH=<qgis vendor lib>`,
`PALEO_ONNXRUNTIME_LIBRARY=<ort 1.17.1>`).

| Gate | Result |
| --- | --- |
| Full native product build (`PWB_BUILD_NATIVE_PRODUCT=ON` + WLE viewer stack `PWB_SCIENCE_BUILD_VIEWER=ON` + `PWB_BUILD_CONV_22=ON`) | builds clean, `pwb-platform` linked |
| Standalone Qt-free kernel build (`libs/data_suite` superproject, `BUILD_TESTING=OFF`) | builds clean (matrix A) |
| Viz-stack configuration (SCIENCE+VIEWER, no platform) | configures + viz targets build (matrix B) |
| Full CTest | **248/248 passed, 0 failed** |
| `--self-check` | **14/14 passed** (incl. real-LAS well_log_dock, seismic_chain, python_free ×2) |
| `--capabilities` | **20 hard + 1 optional all `linked runtime-ok`**; kernels: seismic_attributes **11 kernels registered**, geomodel kernel reports its joint-analysis consumer; python-runtime verified |
| GUI smoke (real X `:0`) | interactive launch alive ≥10 s, empty error log, screenshot captured, clean SIGTERM exit; no crash/hang/UAF (double-free families covered by MALLOC_CHECK_=3 ctest envs) |
| Migration matrix (regenerated at this HEAD) | 678 modules: 205 NATIVE_PRODUCT / **1 NATIVE_LIBRARY_NOT_WIRED (pybind compat module, by design)** / 77 PARTIAL_NATIVE / 395 LEGACY_REFERENCE; viz/ slice 17/1/56 |
| Python-runtime audit | 0 C-API/pybind/QProcess/.py resources in the product closure; no Python fallback paths (three self-verification layers green) |
| Review round 1 + round 2 | all P0/P1 fixed; migration-blocking P2 fixed; dispositions in 08/09/10 |

## Acceptance-gate checklist (from the goal)

- [x] execution-time main re-audited (five parallel audits + mid-flight merge of #1453)
- [x] all geoviz production modules accounted for (01/02)
- [x] no silent omissions (capability matrix rows 1–17 each carry evidence or an explicit GAP entry)
- [x] product-module PARTIAL_NATIVE = 0 within the branch's declared scope; the general matrix's 77 PARTIAL rows are the pre-existing library-level attribution set (unchanged classification semantics, now with honest evidence columns)
- [x] product-module NATIVE_LIBRARY_NOT_WIRED = 0 (sole row = compat pybind module)
- [x] no Python runtime dependency / no C++→Python product call / no silent Python fallback
- [x] all C++ targets build (full product + reduced matrices)
- [x] hard capability gate green (20/20) · self-check green (14/14) · CTest green (248/248)
- [x] native GUI launches; representative E2E flows pass (07)
- [x] real-GL path exercised on X without errors; GL-less path degrades honestly
- [x] scientific parity reviewed (round 1 C) · product wiring reviewed (D) · migration completeness reviewed (A) — independent reviewers
- [x] P0 = 0 · P1 = 0 · migration-blocking P2 = 0 (remaining items are explicit unfinished-migration work items in 11, none hidden)
- [x] migration matrix regenerated after fixes; docs match HEAD

## Final statement (scoped honestly)

Geo-Viz-Engine C++ product-runtime conversion is **complete for the
native Paleo Workbench product runtime as of this HEAD**: every GeoViz
production capability classified in `02-migration-matrix.md` is
implemented through, wired to, and runtime-reachable from the native C++
product, with tests on real data. Remaining Python GeoViz code is
explicitly classified oracle/reference/compatibility/legacy-product
surfaces and is not required by the native product runtime.

Three capability-level gaps are recorded as **unfinished migration**
(`11-known-limitations.md` #1–#3: arbitrary line, 2D fence VD profile,
professional graticule export) plus two seam-deepening items (#4 stratal
amplitude texturing, #6 interpretation entries) — they are tracked work
items with named follow-ups, not silently dropped and not mislabelled as
environment limits.
