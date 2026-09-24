# QGIS Native Python Runtime — Test Plan

Date: 2026-09-23 · Base: `192422c60` · Runs: `-j <= 6` (goal-spec hard limit)

## 1. Suites and where they live

All under `tests/qgis_python/`. They are compiled/run only when
`PALEO_WITH_QGIS_PYTHON` is `ON`; when the option is `OFF` the suite is not
built, and the existing build is unchanged.

| Suite | Covers | Key assertions |
|---|---|---|
| `test_qgis_python_bootstrap` | Phase A | library found/loaded; `isEnabled()` true when enabled; init once only; shutdown idempotent |
| `test_qgis_python_missing_library` | gate #10 | absent `qgispython` → no crash, structured diagnostic, C++ product still usable |
| `test_qgis_python_runner` | gate #3 | `QgsPythonRunner::isValid()` true; `eval()` returns a value through the installed runner |
| `test_qgis_python_smoke` | gate #4 | `import qgis`, `from qgis.core import QgsProject, QgsApplication`, `from qgis import processing` |
| `test_qgis_python_same_objects` | gate #3/rule 9 | Python's `QgsProject.instance()` is the *same object* as the C++ session project; same processing registry |
| `test_qgis_python_iface` | Phase B | `mapCanvas()`, `activeLayer()`, `layerTreeView()`, `mainWindow()`, `messageBar()` return the live objects; Tier C/D return null + diagnostic |
| `test_qgis_python_console` | Phase C | open/close/reopen, multiline, traceback, run file, project switch, shutdown |
| `test_qgis_python_editor` | Phase D | editor widget hosts a `.py`, run-file and run-selection produce output/traceback |
| `test_qgis_python_processing` | Phase E | script discovery, execution, feedback/cancel, output layer in the real project, invalid script, exception traceback |
| `test_qgis_python_plugins` | Phase F | discover, metadata, enable/load/start, disable/unload, provider plugin, broken plugin, incompatible-iface plugin |
| `test_qgis_python_startup` | Phase H | `startup.py`, `PYQGIS_STARTUP`, invalid startup, untrusted project script **not** executed |
| `test_qgis_python_lifecycle` | Phase O | project close with live Python refs; plugin unload removes its QActions; shutdown with a Python Processing task running; repeated open/close; no UAF/double-free/deadlock |
| `test_qgis_python_diagnostics` | Phase L | every field present; environment variables sanitised; no secrets |

## 2. Evidence rules

1. every suite is run **twice** (catch order/leak dependence);
2. a RED counter-evidence run is recorded for the tests that guard an
   architecture gate: disable the mechanism, show the test fails;
3. lifecycle tests run under the sanitizer configuration the repository already
   uses for Qt/QGIS singletons (see `CMakeLists.txt` note on LeakSanitizer);
4. results are pasted into `14-final-verification.md`, including failures.

## 3. Out-of-scope for automation

Interactive console look-and-feel, plugin-manager UI ergonomics and the
Windows install image are verified manually and recorded in `14`, not faked as
automated results.

## 4. Parallelism

`-j4` default, `-j2` when the host is loaded, `-j6` only when idle. Never more.
