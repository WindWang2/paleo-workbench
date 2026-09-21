# 00 — Baseline

Branch: `feat/geoviz-cpp-final-closure` · forked from `7bfe7585` (#1442 era)
· merged `origin/main` `023c0171` (#1453, the parallel platform-audit
session's fixes) mid-flight · final HEAD: see `12-final-verification.md`.

## Execution-time environment

| Component | Value |
| --- | --- |
| Qt | system Qt 6.11.2 (`/usr/lib/cmake/Qt6`) |
| QGIS SDK | vendored, `../../paleo-workbench/native/qgis_render_bridge/build/qgis-vendor/output` (WITH_PYTHON=OFF build; `libqgis_{core,gui,analysis}.so` verified) |
| onnxruntime | `/home/kevin/pwb-sdks/ort/onnxruntime-linux-x64-1.17.1` (needed by `closure_science.core` in CTest) |
| CTest env | `LD_LIBRARY_PATH=<qgis vendor lib>` (libodbc et al.); `QT_QPA_PLATFORM=offscreen` |
| Oracle interpreter | `/home/kevin/project/oracle-venvs/conv12/bin/python` (numpy 2.5.3, scipy 1.18.1) |
| Display | real X `:0` available (GUI smoke ran on xcb) |
| Compiler | gcc 16, ninja, ccache absent |

## Context: two sessions, one repo

Issues **#1443–#1452** were filed (by the parallel post-merge audit session)
against the same baseline this branch forked from. That session's fixes
landed as **#1453** and were **merged into this branch** mid-flight —
including the closure_science post-hoc CMake gates this branch
independently needed (see `09-review-round-2.md`: without the merge, the
closure-seismic prediction page was dead product code at the fork point).
Scope split: the platform/closure/lifecycle axis belongs to the parallel
session; **this branch owns the GeoViz visualization axis**.

## Re-audit at the fork point (not from old docs)

Five parallel read-only audits re-derived the truth state from HEAD:

1. **Docs/claimed-state**: the committed migration matrix was stale vs
   HEAD; `08-final-acceptance.md` itself said "not yet accepted as a
   fully verified native package".
2. **geo-viz-engine inventory**: 9 Python packages, 227 product modules
   (well_log 49, paleo_map 52, plots 34, seismic 33, common 6, map 16,
   well_seismic_3d 15, well_tie 12, cross_well 10).
3. **Python consumer tracing**: the Python product remains a full
   parallel application (geoviz is a hard runtime import there); 66/74
   `paleo_workbench/viz` modules sit in its import closure — expected,
   it is the legacy product, not the native one.
4. **C++ wiring**: 20/20 hard capabilities green at baseline, but five
   geoviz-specific wiring gaps + the WLE viewer stack never configured
   together with the formal product on main.
5. **Python-runtime audit**: zero Python C API / pybind / QProcess / .py
   resources in the pwb-platform closure (three-layer self-verification
   already in tree: configure-time WITH_PYTHON=OFF, ctest ldd scan,
   /proc/self/maps runtime scan).

### Baseline capability numbers

`--self-check` **13/13** (14/14 once the WLE viewer stack joins),
`--capabilities` **20 hard + 1 optional (well_log_viewer absent) +
6 kernel-class**.
