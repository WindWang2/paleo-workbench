// Python action seam implementation (Prompt 7, Phases C/D/F/L).
//
// Wiring notes (all verified against upstream final-4_2_0):
//   * the QGIS Python Console is a *Python* package: python/console/console.py
//     exposes show_console(), which is what QGIS itself calls to open it.
//   * the script editor is the console's own EditorTabWidget
//     (python/console/console_editor.py) — there is no separate editor entry
//     point, so "Script Editor" opens the console on its editor tab.
//   * "Processing Scripts" and "Python Plugins" need the processing plugin and
//     the plugin-manager UI (Phases E/F); until those are wired the actions are
//     disabled with an explicit reason rather than faked.

#include "python_actions_install.hpp"

#include <QAction>
#include <QFileDialog>
#include <QObject>
#include <QWidget>

#include <qgsmessagelog.h>

#include <pwb/qgis_python/python_diagnostics.hpp>
#include <pwb/qgis_python/python_runtime.hpp>

namespace pwb::qgis_python {

namespace {

const char* kOpenConsole =
    "import console.console\n"
    "console.console.show_console()\n";

void log(const QString& message) {
    QgsMessageLog::logMessage(message, QStringLiteral("Python"));
}

void runOrReport(const QString& what, const QString& code) {
    QString error;
    if (!PythonRuntime::instance().runString(code, &error)) {
        log(QStringLiteral("Python action '%1' failed: %2")
                .arg(what, error.isEmpty() ? QStringLiteral("unknown error")
                                           : error));
    }
}

}  // namespace

PythonActionSet installPythonActions(QObject* parent) {
    PythonActionSet set;

    set.console = new QAction(QObject::tr("&Python Console"), parent);
    set.console->setObjectName(QStringLiteral("python.console"));
    QObject::connect(set.console, &QAction::triggered, parent, []() {
        runOrReport(QStringLiteral("Python Console"),
                    QString::fromLatin1(kOpenConsole));
    });

    set.scriptEditor = new QAction(QObject::tr("Python &Script Editor"), parent);
    set.scriptEditor->setObjectName(QStringLiteral("python.scriptEditor"));
    QObject::connect(set.scriptEditor, &QAction::triggered, parent, []() {
        // Upstream hosts the editor inside the console; opening the console on
        // its editor tab is QGIS's own behaviour.
        runOrReport(QStringLiteral("Script Editor"),
                    QString::fromLatin1(kOpenConsole));
    });

    set.runScript = new QAction(QObject::tr("&Run Script..."), parent);
    set.runScript->setObjectName(QStringLiteral("python.runScript"));
    QObject::connect(set.runScript, &QAction::triggered, parent, [parent]() {
        const QString path = QFileDialog::getOpenFileName(
            qobject_cast<QWidget*>(parent), QObject::tr("Run Python script"),
            QString(), QObject::tr("Python scripts (*.py)"));
        if (path.isEmpty()) {
            return;
        }
        QString error;
        if (!PythonRuntime::instance().runFile(path, &error)) {
            log(QStringLiteral("Run Script '%1' failed: %2")
                    .arg(path, error.isEmpty() ? QStringLiteral("unknown error")
                                               : error));
        }
    });

    set.processingScripts =
        new QAction(QObject::tr("Processing &Scripts"), parent);
    set.processingScripts->setObjectName(
        QStringLiteral("python.processingScripts"));

    set.plugins = new QAction(QObject::tr("Python &Plugins"), parent);
    set.plugins->setObjectName(QStringLiteral("python.plugins"));

    set.diagnostics =
        new QAction(QObject::tr("Python Environment &Diagnostics"), parent);
    set.diagnostics->setObjectName(QStringLiteral("python.diagnostics"));
    QObject::connect(set.diagnostics, &QAction::triggered, parent, []() {
        log(QStringLiteral("Python environment diagnostics:\n%1")
                .arg(PythonDiagnostics::reportText()));
    });

    refreshPythonActions(set, PythonRuntime::instance().capability());
    return set;
}

void refreshPythonActions(const PythonActionSet& actions,
                          const PythonCapability& capability) {
    const QString unavailable =
        QStringLiteral("QGIS Python runtime is not available");

    if (actions.console) {
        actions.console->setEnabled(capability.consoleAvailable);
        actions.console->setToolTip(capability.consoleAvailable
                                        ? QStringLiteral("Open the QGIS Python "
                                                         "console")
                                        : unavailable);
    }
    if (actions.scriptEditor) {
        actions.scriptEditor->setEnabled(capability.consoleAvailable);
        actions.scriptEditor->setToolTip(
            capability.consoleAvailable
                ? QStringLiteral("Open the Python script editor")
                : unavailable);
    }
    if (actions.runScript) {
        actions.runScript->setEnabled(capability.usable());
        actions.runScript->setToolTip(capability.usable()
                                          ? QStringLiteral("Run a Python file")
                                          : unavailable);
    }
    if (actions.processingScripts) {
        actions.processingScripts->setEnabled(false);
        actions.processingScripts->setToolTip(
            QStringLiteral("Wired with the Processing script provider "
                           "(Phase E)"));
    }
    if (actions.plugins) {
        actions.plugins->setEnabled(false);
        actions.plugins->setToolTip(
            QStringLiteral("Wired with the QGIS plugin manager backend "
                           "(Phase F)"));
    }
    if (actions.diagnostics) {
        actions.diagnostics->setEnabled(true);
        actions.diagnostics->setToolTip(
            QStringLiteral("Show the QGIS Python environment report"));
    }
}

}  // namespace pwb::qgis_python
