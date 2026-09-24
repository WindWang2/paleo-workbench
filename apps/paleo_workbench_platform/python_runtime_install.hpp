#pragma once

// App-bootstrap seam for the QGIS-native Python runtime (Prompt 7, Phase A).
//
// Called once from bootstrap after QgsApplication and the shell exist and
// before the first project is opened. It never throws and never aborts
// startup: a missing/broken Python runtime is a degraded product, not a
// failure (architecture gate #10).

#include <QString>

class QgisInterface;

namespace pwb::qgis_python {

// `iface` may be nullptr (headless start). When the shell is up it must pass
// the Phase B adapter so `iface` in PyQGIS resolves to paleo's real objects.
// Returns true when Python is enabled; *error receives a human-readable reason
// otherwise.
bool installPythonRuntime(QgisInterface* iface = nullptr,
                          QString* error = nullptr);

// Shutdown hook: plugins unload, runner removed, Python exited. Idempotent.
// Must run before QgsApplication cleanup.
void uninstallPythonRuntime();

}  // namespace pwb::qgis_python
