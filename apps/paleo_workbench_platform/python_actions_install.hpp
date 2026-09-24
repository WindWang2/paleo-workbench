#pragma once

// Python action seam (Prompt 7, Phases C/D/F/L).
//
// The menu/toolbar authority belongs to the shell (Prompt 1). This file only
// CREATES the actions and hands them back; the shell decides where they go.
// Every action is capability-gated: an action whose backend is not available is
// disabled and says why, instead of failing silently.

#include <pwb/qgis_python/python_capability.hpp>

class QAction;
class QObject;

namespace pwb::qgis_python {

struct PythonActionSet {
    QAction* console = nullptr;
    QAction* scriptEditor = nullptr;
    QAction* runScript = nullptr;
    QAction* processingScripts = nullptr;
    QAction* plugins = nullptr;
    QAction* diagnostics = nullptr;
};

// Creates the actions as children of `parent`. Safe to call before the runtime
// is initialised; the enabled state is refreshed by refreshPythonActions().
PythonActionSet installPythonActions(QObject* parent);

// Re-evaluates enabled state and tooltips from the current capability. Call
// after initialize() and after any capability change.
void refreshPythonActions(const PythonActionSet& actions,
                          const PythonCapability& capability);

}  // namespace pwb::qgis_python
