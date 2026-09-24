# QGIS Native Python Runtime — PyQGIS Host Contract (Phase A contract)

Date: 2026-09-23 · Base: `192422c60`

This document is the contract between the paleo C++ host and the QGIS Python
runtime. Anything not stated here is left to QGIS; anything stated here is
paleo's responsibility.

## 1. Ownership

| Object | Owner | Lifetime |
|---|---|---|
| `QgsApplication` | paleo bootstrap (existing, unchanged) | process |
| `QgsProject` | `MapSession` (Prompt 2/3 authority) | session |
| `QgsMapCanvas`, `QgsLayerTreeView` | shell/session widgets (Prompt 1/2) | widget tree |
| `QgsPythonUtils *` | `QgisPythonRuntime` | process, created once |
| `QgsPythonRunner` instance | installed by `QgisPythonRuntime`, owned by QGIS core | process |
| Python objects (`PyObject *`) | CPython; **never** stored by paleo | GIL-bound |
| `QgisInterface` adapter | `QgisPythonRuntime` | process, outlives plugins |

Rule 9 of the goal spec is enforced structurally: **Python never holds a second
`QgsProject`, layer registry, processing registry or layout store.** `iface`
accessors resolve the host's live objects on each call.

## 2. Threading and the GIL

| Rule | Statement |
|---|---|
| T1 | `initialize()` runs on the GUI thread, after `QgsApplication` init and before the first project open |
| T2 | every `QgsPythonUtils` call (`runString`, `evalString`, `runFile`, plugin ops) happens on the thread that called `initPython()`, i.e. the GUI thread |
| T3 | Python Processing algorithms execute inside QGIS's own task/processing machinery; paleo never calls into Python from an arbitrary worker thread |
| T4 | a worker thread that needs a Python result must go through a registered Processing algorithm or a queued signal to the GUI thread — never a direct `QgsPythonUtils` call |
| T5 | GUI objects (`QgsMapCanvas`, widgets) are touched only from the GUI thread; PyQGIS wrappers handed to Python obey the same affinity |
| T6 | paleo does not call `PyGILState_Ensure()` itself: `QgsPythonUtilsImpl` owns GIL handling. Paleo code that must run Python does it through `QgsPythonRunner` or `QgsPythonUtils` |

## 3. Initialisation / shutdown ordering

```text
boot:   QgsApplication → shell → session → QgisPythonRuntime::initialize()
        → plugins (opt-in) → project open

exit:   project close → plugin unload → QgsPythonRunner::setInstance(nullptr)
        → QgsPythonUtils::exitPython() → QgsApplication cleanup
```

`shutdown()` is idempotent and safe to call twice. Python must never outlive
`QgsApplication` (upstream's own warning; calling `exitQgis()` from Python
inside the app is a hard crash — see `03` §5).

## 4. Capability and state surface (consumed by Phase L diagnostics)

```cpp
struct PythonCapability {
    bool pythonRuntimeAvailable;   // qgispython found + loaded
    bool pythonEnabled;            // QgsPythonUtils::isEnabled()
    bool bindingsAvailable;        // qgis.core/gui/processing importable
    bool processingAvailable;      // Python processing plugin usable
    bool consoleAvailable;         // QGIS console package present
    QString libraryPath;           // resolved qgispython path
    QString libraryError;          // QLibrary::errorString() on failure
    int    qgisVersionInt;         // 40200
    QString pythonVersion;         // from the runtime, e.g. "3.14.7"
};
```

Everything else (sys.path, plugin paths, loaded plugins, startup hook results)
is produced by the diagnostics module from Python itself, sanitised per
`09-security-trust-model.md`.

## 5. Error policy

| Situation | Behaviour |
|---|---|
| `qgispython` missing | capability=false, one structured diagnostic, product continues |
| `instance()` unresolvable | same; recorded with the resolved path |
| `initPython()` leaves `isEnabled()==false` | same; runner not installed |
| Python code raises | traceback surfaced verbatim (never swallowed) via `QgsPythonUtils::getError()` |
| plugin load fails | fail honestly: message + traceback, plugin stays unloaded |
| bindings missing but `qgispython` present | `bindingsAvailable=false`; console/processing features report unavailable; `QgsPythonRunner` still works for non-PyQGIS statements |

No failure path throws, aborts, or falls back to another interpreter.

## 6. Forbidden by this contract

1. `Py_Initialize()` / `Py_Finalize()` anywhere in paleo code (gate #1).
2. A paleo-owned venv/conda used as the product runtime (gate #2).
3. A second script engine, second plugin backend, second algorithm registry
   (gates #6, #14).
4. Executing Python found in a project directory without explicit opt-in
   (see `09`).
5. Caching a `QgsProject`/canvas/layer pointer inside the adapter at init time
   (risk R-1 in `01-overlap-audit.md`).
