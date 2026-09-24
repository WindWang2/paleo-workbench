# QGIS Native Python Runtime — Runtime Inventory (capability report)

Date: 2026-09-23 · Base: `192422c60` · Upstream reference: `final-4_2_0`
(downloaded, SHA-256 verified, extracted to
`/home/kevin/.build-tmp/qgis-src/`).

Every line below was checked on disk — no inference from QGIS documentation.

## 1. What the vendored closure already has

| Component | Path in `third_party/qgis` | Status |
|---|---|---|
| `QgsPythonRunner` (abstract core entry point) | `src/core/qgspythonrunner.{h,cpp}` | **present** — `run` / `runFile` / `eval` / `setArgv` / `setInstance`, exactly the "not an interpreter" contract |
| `QgisInterface` (the `iface` surface) | `src/gui/qgisinterface.h` (65 KB, **279** `virtual` declarations) | **present** |
| Python-aware code editors | `src/gui/codeeditors/qgscodeeditorpython.{h,cpp}`, `qgscodeeditorwidget.*`, `qgscodeeditordockwidget.*` | **present** (QScintilla-based) |
| C++ Processing framework | `src/core/processing/**`, `src/analysis/processing/**` | **present** — the single `QgsProcessingRegistry` Python must feed |
| `QgsApplication` / project / layer tree / canvas | `src/core`, `src/gui` | **present** |

## 2. What is missing (and must be imported from `final-4_2_0`)

| Upstream path | Files | Size | Purpose |
|---|---|---|---|
| `src/python/` | 5 | 60 KB | the `qgispython` support library: `qgispython.cpp` (22), `qgspythonutils.h` (238), `qgspythonutilsimpl.cpp` (971), `qgspythonutilsimpl.h` (144), `CMakeLists.txt` |
| `python/PyQt6/` | 3 005 | 22 MB | PyQGIS binding sources — **1 524** `.sip.in` files (`core` 15 MB, `gui` 6.0 MB, `analysis` 552 K, `3d` 552 K, `server` 404 K) |
| `python/plugins/processing` | — | 44 MB | built-in Processing Python plugin: algorithm wrappers, script provider, modeler, GUI |
| `python/console/` | 12 | 184 KB | QGIS's own Python Console (`console.py`, `console_editor.py`, `console_output.py`, `console_sci.py`, `console_settings.py`, `process_wrapper.py`, …) |
| `python/pyplugin_installer/` | — | 196 KB | QGIS plugin-manager backend (install/uninstall/repository metadata) |
| `python/qsci_apis/` | — | 2.1 MB | API files for console/editor completion |
| `python/{__init__,utils,user}.py`, `common/`, `custom_widgets/`, `ext-libs/`, `testing/`, `PyQt/` | — | <260 KB | the `qgis` Python package root, `qgis.utils.iface`, plugin bootstrap helpers |
| `python/plugins/{grassprovider,db_manager,MetaSearch}` | — | 5.8 MB | built-in plugins **not** required by paleo → classified D, not imported (see `07-plugin-runtime-design.md`) |
| **Total (selected)** | **≈5 960** | **≈74 MB** | excluding the three D-class plugins: ≈68 MB |

The `qgispython` target is cheap to build — upstream `src/python/CMakeLists.txt`
links only `qgis_core`, `Python::Python` and `${OPENPTY_LIBRARY}`; `QgisInterface`
is forward-declared only, so **no GUI dependency**. `qgis_python.h` is produced
by `GENERATE_EXPORT_HEADER`, i.e. no extra template must be vendored.

## 3. Capability answers (as required by the goal spec)

| Question | Answer at base | After the planned work |
|---|---|---|
| Python available? | yes — host Python **3.14.7**, headers + `libpython3.14.so` present | unchanged: the QGIS distribution's interpreter is authoritative, not a paleo venv |
| `qgispython` library? | **NO** — not vendored, never built (`-DWITH_BINDINGS=OFF`) | YES (`PALEO_WITH_QGIS_PYTHON`) |
| PyQGIS import? | **NO** — no `python/` tree at all | YES (`PALEO_WITH_QGIS_BINDINGS`) |
| `qgis.core` / `qgis.gui` / `qgis.analysis` / `qgis._3d`? | **NO** | core/gui/analysis YES; `_3d` only if the 3D target is ever enabled — currently **no** |
| `processing`? | C++ framework YES; **Python processing plugin NO** | YES |
| built-in plugins? | **NO** | Processing + console YES; grassprovider/db_manager/MetaSearch **no** (class D) |
| script provider (Python Processing scripts)? | **NO** | YES |
| `QgsPythonRunner::isValid()`? | **false** — no runner instance installed | true |

## 4. Host toolchain audit (Linux verification host)

| Requirement | Status | Note |
|---|---|---|
| Python 3.14 dev (`Python.h`, `libpython3.14.so`) | **present** | bindings compile against this interpreter |
| PyQt6 (runtime) | **present** | QGIS 4.x bindings are PyQt6/SIP-based |
| `PyQt6.sip` module | **present** | needed at link time |
| `Qsci/qscimod6.sip` (QScintilla binding source) | **present** at `/usr/lib/python3.14/site-packages/PyQt6/bindings/Qsci/` | required by `python/CMakeLists.txt` (`QSCI_SIP_MOD_NAME`) |
| QScintilla2 Qt6 (C++ `QgsCodeEditorPython`) | **present** (`/usr/include/qt6/Qsci`, `libqscintilla2_qt6.so`) | Phase D can reuse QGIS's own editor |
| **`sip` build executable** | **MISSING** (no `sip` CLI, no `sipbuild` module) | **build gap**: the bindings build cannot run until a sip ≥ 6 matching the installed PyQt6 is provided (distribution package or pip) |
| PySide6 | absent | not applicable |

The missing `sip` tool is recorded as a **packaging prerequisite**, not a design
change: no paleo-specific Python environment is created to work around it.

## 5. Explicitly rejected shortcut

This machine also has **system QGIS 4.2.2** with a complete PyQGIS install
(`/usr/lib/python3.14/site-packages/qgis`: `core`, `gui`, `analysis`, `_3d`,
`server`, `processing`). It is **not** used:

1. `third_party/qgis/README.paleo-workbench.md` forbids substituting an
   installed QGIS for the vendored source;
2. the system copy is a *different patch release* (4.2.2 vs vendored 4.2.0) —
   mixing them would break the ABI-agreement gate (#9);
3. importing it would silently make paleo depend on a host-installed
   distribution, which the packaging matrix must not assume.

It stays useful as a *behavioural oracle* when writing PyQGIS smoke tests.

## 6. Consequences for the phase plan

- **Correction (found during implementation)**: `qgispython` is *not* a
  separable gate. `third_party/qgis/src/CMakeLists.txt` adds `src/python` only
  inside `if (WITH_BINDINGS)`, so the support library ships together with the
  bindings. `02` §5's "bindings missing but qgispython present" remains a valid
  *runtime* state (an install image without the Python modules), but it cannot
  be produced by the build.
- Phase D (script editor) needs **no new UI code** — `QgsCodeEditorPython` and
  `QgsCodeEditorWidget` are already vendored.
- Phase B (`iface`) is large but mechanical: 279 virtual members must be sorted
  into the A/B/C/D tiers.
