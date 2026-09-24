#pragma once

// QGIS-native Python runtime — capability/state surface (Prompt 7, Phase A).
//
// This struct is the ONLY thing the rest of paleo may read about the Python
// runtime. It is intentionally flat and copyable: no PyObject, no QGIS type,
// no ownership. Produced by PythonRuntime, consumed by the diagnostics panel
// (Phase L) and by any feature that must degrade instead of crash.

#include <QString>

namespace pwb::qgis_python {

struct PythonCapability {
    // qgispython was found, loaded and its instance() resolved.
    bool runtimeAvailable = false;

    // QgsPythonUtils::isEnabled() after initPython().
    bool pythonEnabled = false;

    // `import qgis.core` succeeded, i.e. the PyQGIS bindings are installed
    // for this build. False is a supported state, not an error.
    bool bindingsAvailable = false;

    // The Python processing plugin is importable.
    bool processingAvailable = false;

    // The QGIS console package is importable.
    bool consoleAvailable = false;

    // QgsPythonRunner has an instance installed.
    bool runnerInstalled = false;

    QString libraryPath;   // resolved qgispython path
    QString libraryError;  // QLibrary::errorString() on failure
    QString pythonVersion; // e.g. "3.14.7"
    QString qgisVersion;   // e.g. "4.2.0"

    // True when the runtime can run Python at all.
    bool usable() const { return runtimeAvailable && pythonEnabled; }
};

}  // namespace pwb::qgis_python
