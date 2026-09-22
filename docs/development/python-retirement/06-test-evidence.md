# Python Retirement — Test Evidence

Verification environment: Linux (GCC 16.2.1), Qt 6.11.2 system prefix,
vendored QGIS SDK (dev build) reused from the sibling main checkout,
resource gate at `-j 2` / `CTEST_PARALLEL_LEVEL=2`, `QT_QPA_PLATFORM=offscreen`.
Online CI: not awaited (per goal). All numbers below are from actual runs.

## Static stage (final-closure-gate.sh static)

- `pwb_migration_inventory.py` — regenerated (docs/development/cpp-migration-inventory.md), exit 0
- `pwb_final_closure_matrix.py` — regenerated: **678 modules, 0 python-runtime-required, 0 packaged** (208 NATIVE_PRODUCT / 79 PARTIAL_NATIVE / 390 LEGACY_REFERENCE / 1 NOT_WIRED at this base)
- `unittest tools.migration.tests.test_final_closure_matrix` — **OK (4 tests)**
- `pwb_artifact_hygiene.py` — exit 0
- `pwb_python_dependency_audit.py` — exit 0 (known classes only: compat seams + vendored QGIS + informational packaging notes)
- `audit-python-runtime-deps.sh` — **AUDIT PASS** (source scan clean; pybind confined to the two compat seams)
- `check-python-retirement.sh` — **PYTHON_RETIREMENT_GATE_PASS** (archive isolation / tree shape / sanctioned shim)
- tracked-cache artifact check — clean

## Configure + build

- configure (Ninja, `PWB_BUILD_NATIVE_PRODUCT=ON` + testing/integration/packaging): **exit 0**
- `pwb-platform` target: **built and linked** (40 MB executable)
- full-tree build (all targets incl. test executables): **870/870 steps, exit 0**
- Compile fixups required on top of the stacked base (#1473, MSVC-only evidence):
  1. `libs/providers/src/plugin_loader.cpp` — `::dl_close` → POSIX `::dlclose`
  2. `cmake/PwbFeatures.cmake` — `PWB_BUILD_NATIVE_PRODUCT` now implies
     `PWB_BUILD_CONV_32` (#1473's workflow_install.cpp consumes the
     interpretation headers "in every shape" but the product closure did not
     build them)

## Runtime smoke (built binary, offscreen)

- `pwb-platform --self-check` — **13/13 checks PASS** (incl.
  `python_free_process: verified`, `qgis_runtime`, `service_registry — 20
  hard services`, ui_shell/data/seismic/layout chains). One diagnostic-only
  GDAL warning (GDAL_DATA/plotting driver env) — not a self-check failure.
- `pwb-platform --capabilities` — lists the hard capability table
  (qgis_platform, data_integration, science_kernels, seismic_viewer,
  seismic_attributes — 11 kernels, seismic_io, seismic_service, …), all
  `linked` / `runtime-ok`.
- `pwb-platform --diagnostics` — clean report; `python runtime: verified`.
- `audit-python-runtime-deps.sh --exe <pwb-platform>` — **clean: closure
  python-free** (ldd closure has no python/PySide/shiboken objects).
- Self-check host note: the binary requires the vendored SDK's lib dir on
  `LD_LIBRARY_PATH` in a build-tree run (deployed trees get it from the
  launcher); `libodbc.so.2` comes from the SDK output, not the system.

## Diagnostics-scan fixup (stacked)

`scan_python_runtime()` matched a bare `python` substring against
`/proc/self/maps` paths — a checkout named `…-python-archive` failed the
product's own `python_free_process` check with its own executable as the
"leak". Patterns tightened to library path shapes (`libpython`, `/python`,
`pyside`, `shiboken`); self-check went 11/13 → 13/13.

## CTest

The final-closure gate's `build` stage builds the `pwb-platform` target
only; the focused test executables need a full-tree build first (pre-existing
gate behavior, recorded here). After `cmake --build` (all targets):

- gate `test` stage (regex `^(platform\.|integration\.|data\.|science\.|seismic\.|mapping\.)`, two passes): **100% passed, 0 failed out of 68 — both passes** (CTEST_EXIT=0)
- full CTest (all 246 registered tests, CTEST_PARALLEL_LEVEL=2):
  **244/246 after the stacked fixups below** (first full run: 242/246)
  - `workflow_interpretation.fault_lifecycle` — infinite `test_pid()` recursion from #1473's MSVC portability helper (POSIX branch called itself); busy-looped at 99% CPU. Fixed → passes in 0.03 s.
  - `closure_science.mock_facies` — same recursion, burned its 120 s timeout. Fixed → passes in 0.06 s.
  - `prediction.runtime`, `closure_science.core` — **environment**: this host has no `libonnxruntime` (both fail fast with the explicit "ONNX Runtime native library unavailable" message; unrelated to the retirement diff — no retirement change touches libs/prediction or libs/closure_science).

Note: the gate's `build` stage builds the `pwb-platform` target only, so the
focused/full test runs required a full-tree `cmake --build` first (870/870,
exit 0). The CONV-32 closure expansion (stacked fixup, see 05) newly builds
the workflow_interpretation test set in the native-product configure —
which is how the #1473 recursion bug surfaced.

## Python-side verification (no pytest on the verification host)

- All 97 auto-edited active `.py` files compile (`py_compile`), 0 failures.
- Kept-suite import closure: every kept test's `tests.*` import resolves;
  no kept test imports the archived package transitively (scan-verified).
- Archived-reference import chain: resolves through the shim up to
  third-party deps (numpy absent on the bare system python — generators run
  in the dev env/CI; frozen fixtures keep CTest Python-independent). See
  known limitation K4.
- The retired suite keeps its original conftest (bootstrapped to the
  archive) and an archive-local `qgis_support.py` copy.
