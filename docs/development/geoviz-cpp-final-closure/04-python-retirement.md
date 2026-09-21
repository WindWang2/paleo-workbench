# 04 — Python runtime retirement (product scope)

Target (from the goal): the **native product runtime** must be 100%
Python-free. The Python paleo-workbench shell remains a supported legacy
product; its own runtime keeps importing geoviz — that is the legacy
product's business, not a native-product dependency.

## Verified state at final HEAD (audit `05` has the scans)

* **Zero** Python C API / pybind11 / Py_Initialize / PyRun / PyImport in
  the pwb-platform TU closure. The only pybind modules in-tree are
  `mapping_bind` (CONV-20) and `cartography_bind` (CONV-27): default OFF,
  never linked by the product, one-way kernel→bind dependency.
* **Zero** QProcess / python3 / python.exe invocations in libs/apps C++.
* **Zero** `.py` resources in Qt resources or install trees
  (`cmake/PwbInstall.cmake` pattern-excludes `*.py`).
* **No silent fallback to Python** anywhere in the product: every
  "fallback" hit in the round-1 scan is native-degraded or fail-closed
  (map render falls back to the non-QGIS native Qt backend; layout export
  refuses; contour-draft throws unless the native marching-squares hook is
  bound; the joint host shows UnavailableJointHost).
* Self-verification mechanisms (all green): `platform.python_free` ctest
  (ldd closure scan), `--self-check` python_free_process (twice per run,
  `/proc/self/maps`), `--diagnostics` python-runtime verdict, and the
  deploy-tree audit script.

## Python sources — remaining classes

| Class | Members | Notes |
| --- | --- | --- |
| ORACLE / dev-only | `tools/oracle/*` (93 generators), `libs/**/oracle/*.py`, pytest suites, `tests/fixtures` makers | never in the product install |
| COMPATIBILITY_ONLY | `mapping_bind`, `cartography_bind` (+ their smoke tests) | consumed BY legacy Python; never by the product |
| LEGACY product | `paleo_workbench/**` (678 modules incl. the 56 LEGACY viz rows) | the legacy shell stays runnable; retirement of the shell itself is the M12 decision, explicitly out of this closure's scope (documented in `docs/development/cpp-platform/native-product-closure.md`) |

No GeoViz product capability is served by Python at runtime in the native
product (capability matrix `02`); the remaining Python is oracle/compat/
legacy-product classified with evidence.
