# QGIS Native Python Runtime — qgispython Bootstrap Design (Phase A)

Date: 2026-09-23 · Base: `192422c60`

## 1. Upstream provenance of everything this phase reuses

| Item | Upstream path | Version read | License / copyright |
|---|---|---|---|
| `QgsPythonUtils` abstract contract | `src/python/qgspythonutils.h` | `final-4_2_0` (structural twin at 4.0.2) | GPL-2.0-or-later, © 2006 Martin Dobias |
| `QgsPythonUtilsImpl` | `src/python/qgspythonutilsimpl.{h,cpp}` | `final-4_2_0` | GPL-2.0-or-later, © 2006 Martin Dobias |
| `instance()` factory | `src/python/qgispython.cpp` | `final-4_2_0` | GPL-2.0-or-later, © 2008 Martin Dobias |
| bootstrap chain (Desktop) | `src/app/qgisapp.cpp` → `QgisApp::loadPythonSupport()` + `QgsPythonRunnerImpl` | 4.0.2 reference tree | GPL-2.0-or-later, QGIS contributors |
| bootstrap chain (headless) | `src/process/qgsprocess.cpp` → `QgsProcessingExec::loadPythonSupport()` | 4.0.2 reference tree | GPL-2.0-or-later, QGIS contributors |

Two upstream call sites exist and they differ only in the arguments passed to
`initPython()`:

- **Desktop**: `initPython( mQgisInterface, /*installErrorHook=*/true, crashLogPath )`
- **Headless** (`qgis_process`): `initPython( nullptr, false )`

Paleo is a GUI application → it follows the **Desktop** chain.

## 2. The real initialisation chain (transcribed from upstream)

```text
QLibrary pythonlib( "qgispython" + QGISPOSTFIX, "4.2.0" )
  .setLoadHints( ResolveAllSymbolsHint | ExportExternalSymbolsHint )   // REQUIRED
  → load()
  → resolve( "instance" )                       // QgsPythonUtils *(*)()
  → pythonUtils = instance()
  → initPython( iface, installErrorHook=true, faultHandlerLogPath )
  → runString( <neuter QgsApplication.initQgis/exitQgis> )   // safety, see §5
  → QgsPluginRegistry::instance()->setPythonUtils( pythonUtils )
  → QgsPythonRunner::setInstance( new QgsPythonRunnerImpl( pythonUtils ) )
  → pythonUtils->initGDAL()
```

Three details are load-bearing and are easy to get wrong:

1. **`ResolveAllSymbolsHint | ExportExternalSymbolsHint`** — without them the
   Python shared library's symbols are not exported globally and extension
   modules fail to resolve. Comment in upstream points to the pykde list
   archive; treat it as non-negotiable.
2. **`QgsPythonRunner::setInstance()` happens *after* `initPython()`**, and only
   if `isEnabled()`. `QgsPythonRunner` is a *conduit* to `QgsPythonUtils`, never
   an interpreter. Gate #3 in the goal spec ("`QgsPythonRunner` valid in the
   product process") is satisfied by this single call.
3. **`initPython` must run before project loading** so that `startup.py`,
   plugin processing providers and expression functions exist for the first
   project open.

## 3. What paleo adds: `QgisPythonRuntime` (thin host service)

New files: `libs/qgis_python/qgis_python_runtime.{h,cpp}` (+ a small
`qgis_python_runner.{h,cpp}` mirroring upstream's `QgsPythonRunnerImpl`).

Permitted responsibilities — nothing outside this list:

| # | Responsibility |
|---|---|
| 1 | detect whether `qgispython` is present and loadable |
| 2 | load it with the required hints and resolve `instance()` |
| 3 | own the `QgsPythonUtils *` for the process lifetime |
| 4 | call `initPython()` with paleo's `QgisInterface` adapter (Phase B) |
| 5 | install `QgsPythonRunner` |
| 6 | apply the upstream `initQgis`/`exitQgis` neutering snippet |
| 7 | call `initGDAL()` |
| 8 | expose a read-only `Capability`/`State` struct (see Phase L) |
| 9 | `shutdown()`: `exitPython()` + drop the runner instance, idempotent |
| 10 | emit a structured diagnostic on every failure path |

Explicitly **not** in scope: any script engine, any second interpreter, any
dependency installation, any plugin-policy logic (that belongs to
`07-plugin-runtime-design.md`).

## 4. Ordering contract inside the paleo process

```text
QgsApplication construction / QGIS bootstrap      (existing, unchanged)
  ↓
shell + canvas + project objects ready           (Prompt 1 / 2 / 3 authority)
  ↓
QgisPythonRuntime::initialize()                  (this branch)
  ├─ load qgispython, initPython( ifaceAdapter, true, logPath )
  ├─ QgsPythonRunner::setInstance( ... )
  └─ initGDAL()
  ↓
first project open
```

Shutdown is the exact reverse: plugins unload → `QgsPythonRunner` instance
dropped → `exitPython()` → `QgsApplication` cleanup. Python must **never**
outlive `QgsApplication` (Phase O).

## 5. Safety transplant (from upstream, kept verbatim in behaviour)

Upstream injects a snippet that makes `QgsApplication.initQgis()` and
`exitQgis()` raise if called from Python inside the application, because doing
so crashes the process. Paleo inherits the same hazard and therefore executes
the equivalent snippet. This is a *port* of upstream behaviour, recorded with
its provenance in §1, not a new invention.

## 6. Graceful degradation (architecture gate #10)

If `qgispython` is absent, unloadable, or `instance()` cannot be resolved, the
runtime:

- leaves `isEnabled() == false`;
- logs one structured diagnostic containing the resolved library path, the
  `QLibrary::errorString()`, and the Python/QGIS version pair;
- leaves `QgsPythonRunner::isValid() == false` — callers must already tolerate
  that (upstream core does);
- **never** throws, never aborts startup, never substitutes another interpreter.

The C++ product must remain fully usable in that state; only Python-dependent
features report "unavailable".

## 7. Build gating

**One gate**, default `OFF` so the current build stays byte-identical until the
closure is proven:

```cmake
option(PALEO_WITH_QGIS_PYTHON "...qgispython + PyQGIS bindings + console + built-in plugins" OFF)
```

which the bridge forwards as `-DWITH_PYTHON=${...} -DWITH_BINDINGS=${...}`.

### Correction made during implementation (review finding 2.10)

An earlier draft assumed two independent gates — `qgispython` alone, then the
bindings. That is **wrong**: `third_party/qgis/src/CMakeLists.txt` reads

```cmake
if (WITH_BINDINGS)
  add_subdirectory(python)     # ← src/python, i.e. the qgispython library
endif()
```

so upstream never builds `qgispython` unless the bindings are being built.
Splitting them would mean patching vendored build logic, which this branch does
not do. Consequences:

- there is exactly one switch, `PALEO_WITH_QGIS_PYTHON`;
- the "qgispython present but bindings absent" degradation path stays in the
  *runtime* (it is what happens when `import qgis.core` fails at runtime), not
  in the build;
- the `sip` prerequisite is therefore a prerequisite for the whole feature, not
  just for the bindings half.

## 8. Tests this phase must produce (`tests/qgis_python/`)

| Test | Assertion |
|---|---|
| `test_qgis_python_bootstrap` | library found/loaded; `isEnabled()` true when enabled |
| `test_qgis_python_missing_library` | absent `qgispython` → no crash, diagnostic emitted, C++ product still usable |
| `test_qgis_python_init_once` | repeated `initialize()` is a no-op; not a second interpreter |
| `test_qgis_python_shutdown` | `shutdown()` idempotent; runner invalid afterwards |
| `test_qgis_python_runner` | `QgsPythonRunner::isValid()` true and `eval()` returns a value through the installed runner |

Parallelism for all builds and test runs: `-j <= 6` (goal-spec hard limit).
