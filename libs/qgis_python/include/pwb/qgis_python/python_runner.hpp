#pragma once

// The paleo implementation of QGIS's abstract QgsPythonRunner (Prompt 7,
// Phase A). Ported in behaviour from upstream QGIS's own
// `QgsPythonRunnerImpl` (src/app/qgisapp.cpp, tag final-4_2_0 lineage,
// GPL-2.0-or-later, QGIS contributors) — it is a conduit to QgsPythonUtils and
// holds no interpreter state of its own.
//
// Installed with QgsPythonRunner::setInstance() AFTER initPython() and only
// when QgsPythonUtils::isEnabled(). Uninstalled with setInstance(nullptr).

#include <qgspythonrunner.h>

class QgsPythonUtils;

namespace pwb::qgis_python {

class PythonRunner : public QgsPythonRunner {
public:
    explicit PythonRunner(QgsPythonUtils* utils);

protected:
    bool runCommand(QString command, QString messageOnError = QString()) override;
    bool runFileCommand(const QString& filename,
                        const QString& messageOnError = QString()) override;
    bool evalCommand(QString command, QString& result) override;
    bool setArgvCommand(const QStringList& arguments,
                        const QString& messageOnError = QString()) override;

private:
    QgsPythonUtils* utils_ = nullptr;
};

}  // namespace pwb::qgis_python
