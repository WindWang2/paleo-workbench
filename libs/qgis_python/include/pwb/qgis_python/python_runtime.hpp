#pragma once

// QGIS-native Python runtime host service (Prompt 7, Phase A).
//
// Responsibilities are deliberately narrow (see
// docs/development/qgis-native-python-runtime/03-qgispython-bootstrap.md §3):
// detect/load qgispython, own QgsPythonUtils, initialise Python in QGIS's own
// order, install QgsPythonRunner, expose capability, shut down cleanly.
//
// It is NOT a script engine, NOT an interpreter wrapper and never calls
// Py_Initialize() — QGIS's qgispython library owns the interpreter.

#include <memory>

#include <pwb/qgis_python/python_capability.hpp>

class QgsPythonUtils;
class QgisInterface;

namespace pwb::qgis_python {

class PythonRuntime {
public:
    static PythonRuntime& instance();

    // Initialises Python once. Safe to call repeatedly: the second call is a
    // no-op that reports the existing state. Never throws.
    // `iface` may be nullptr (headless/QGIS-process-style start); when paleo
    // has a running shell it must pass the Phase B adapter.
    bool initialize(QgisInterface* iface = nullptr, QString* error = nullptr);

    bool isEnabled() const;
    bool isInitialized() const;

    // Idempotent. Uninstalls the runner first, then exits Python, then drops
    // the library. Python never outlives QgsApplication: call this before the
    // application is torn down.
    void shutdown();

    const PythonCapability& capability() const;

    // Execution helpers. All of them run on the calling thread — callers must
    // be on the GUI thread (see 04-pyqgis-host-contract.md, rules T1/T2).
    bool runString(const QString& command, QString* error = nullptr);
    bool evalString(const QString& expression, QString* result,
                    QString* error = nullptr);
    bool runFile(const QString& path, QString* error = nullptr);

    // Last Python traceback (empty when none). Tracebacks are surfaced, never
    // swallowed.
    QString lastTraceback() const;

private:
    PythonRuntime();
    ~PythonRuntime();

    PythonRuntime(const PythonRuntime&) = delete;
    PythonRuntime& operator=(const PythonRuntime&) = delete;

    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace pwb::qgis_python
