// PythonRunner — conduit from QGIS core to QgsPythonUtils (see header).
//
// Upstream provenance: behaviour transcribed from QGIS's QgsPythonRunnerImpl
// (src/app/qgisapp.cpp, upstream tag final-4_2_0 lineage; GPL-2.0-or-later,
// QGIS contributors). Change: the QGIS Desktop version logs to its own message
// bar; this version stays silent on success and lets the caller own reporting.

#include <pwb/qgis_python/python_runner.hpp>

#include <qgspythonutils.h>

using pwb::qgis_python::PythonRunner;

PythonRunner::PythonRunner(QgsPythonUtils* utils) : utils_(utils) {}

bool PythonRunner::runCommand(QString command, QString messageOnError) {
    if (utils_ && utils_->isEnabled()) {
        return utils_->runString(command, messageOnError, false);
    }
    Q_UNUSED(messageOnError)
    return false;
}

bool PythonRunner::runFileCommand(const QString& filename,
                                  const QString& messageOnError) {
    if (utils_ && utils_->isEnabled()) {
        return utils_->runFile(filename, messageOnError);
    }
    Q_UNUSED(filename)
    Q_UNUSED(messageOnError)
    return false;
}

bool PythonRunner::evalCommand(QString command, QString& result) {
    if (utils_ && utils_->isEnabled()) {
        return utils_->evalString(command, result);
    }
    Q_UNUSED(command)
    return false;
}

bool PythonRunner::setArgvCommand(const QStringList& arguments,
                                  const QString& messageOnError) {
    if (utils_ && utils_->isEnabled()) {
        return utils_->setArgv(arguments, messageOnError);
    }
    Q_UNUSED(arguments)
    Q_UNUSED(messageOnError)
    return false;
}
