// App-bootstrap seam implementation (Prompt 7, Phase A).
//
// This is the ONLY place in the application that starts Python. It adds no
// policy of its own: everything is delegated to PythonRuntime.

#include "python_runtime_install.hpp"

#include <qgsmessagelog.h>

#include <pwb/qgis_python/python_runtime.hpp>

namespace pwb::qgis_python {

bool installPythonRuntime(QgisInterface* iface, QString* error) {
    PythonRuntime& runtime = PythonRuntime::instance();
    const bool ok = runtime.initialize(iface, error);

    const PythonCapability capability = runtime.capability();
    QgsMessageLog::logMessage(
        QStringLiteral(
            "QGIS Python runtime: runtimeAvailable=%1 pythonEnabled=%2 "
            "bindings=%3 processing=%4 console=%5 (%6)")
            .arg(capability.runtimeAvailable ? QStringLiteral("yes")
                                             : QStringLiteral("no"),
                 capability.pythonEnabled ? QStringLiteral("yes")
                                          : QStringLiteral("no"),
                 capability.bindingsAvailable ? QStringLiteral("yes")
                                              : QStringLiteral("no"),
                 capability.processingAvailable ? QStringLiteral("yes")
                                                : QStringLiteral("no"),
                 capability.consoleAvailable ? QStringLiteral("yes")
                                             : QStringLiteral("no"),
                 capability.libraryError.isEmpty()
                     ? QStringLiteral("no error")
                     : capability.libraryError),
        QStringLiteral("Python"));

    return ok;
}

void uninstallPythonRuntime() { PythonRuntime::instance().shutdown(); }

}  // namespace pwb::qgis_python
