// QGIS-native Python runtime host (Prompt 7, Phase A).
//
// Bootstrap chain transcribed from upstream QGIS Desktop
// (src/app/qgisapp.cpp :: QgisApp::loadPythonSupport, upstream tag
// final-4_2_0 lineage, GPL-2.0-or-later, QGIS contributors) and from the
// headless variant (src/process/qgsprocess.cpp :: loadPythonSupport).
//
// Order matters:
//   QLibrary("qgispython") with ResolveAllSymbolsHint|ExportExternalSymbolsHint
//   -> resolve("instance") -> QgsPythonUtils
//   -> initPython(iface, true, faultHandlerLogPath)
//   -> (bindings only) neuter QgsApplication.initQgis/exitQgis
//   -> QgsPythonRunner::setInstance(...)
//   -> initGDAL()
// Shutdown is the reverse; see 04-pyqgis-host-contract.md §3.

#include <pwb/qgis_python/python_runtime.hpp>

#include <memory>
#include <utility>

#include <QCoreApplication>
#include <QLibrary>
#include <QStandardPaths>
#include <QString>

#include <qgis.h>
#include <qgsapplication.h>
#include <qgsmessagelog.h>
#include <qgspythonrunner.h>
#include <qgspythonutils.h>

#include <pwb/qgis_python/python_runner.hpp>

namespace pwb::qgis_python {

namespace {

// Upstream safety transplant: calling QgsApplication.initQgis()/exitQgis()
// from Python inside a running QGIS application crashes the process. QGIS
// neutralises both methods after initPython(); paleo inherits the hazard and
// therefore the same guard. Only meaningful once the bindings are importable.
const char* kNeuterAppInit =
    "from qgis.core import QgsApplication as _QgsApplication\n"
    "\n"
    "def _paleo_app_init_qgis():\n"
    "  raise RuntimeError('QgsApplication.initQgis() must never be called "
    "from within the application. This method is exclusively for standalone "
    "scripts.')\n"
    "\n"
    "_QgsApplication.initQgis = _paleo_app_init_qgis\n"
    "\n"
    "def _paleo_app_exit_qgis():\n"
    "  raise RuntimeError('QgsApplication.exitQgis() must never be called "
    "from within the application. This method is exclusively for standalone "
    "scripts.')\n"
    "\n"
    "_QgsApplication.exitQgis = _paleo_app_exit_qgis\n";

void logPython(const QString& message) {
    QgsMessageLog::logMessage(message, QStringLiteral("Python"));
}

}  // namespace

struct PythonRuntime::Impl {
    QgsPythonUtils* utils = nullptr;
    std::unique_ptr<QLibrary> library;
    PythonCapability cap;
    bool initialized = false;
    QString lastTraceback;
    QString libraryError;  // mirrored into cap.libraryError for the public API
};

PythonRuntime::PythonRuntime() : impl_(std::make_unique<Impl>()) {}

PythonRuntime::~PythonRuntime() { shutdown(); }

PythonRuntime& PythonRuntime::instance() {
    static PythonRuntime runtime;
    return runtime;
}

bool PythonRuntime::initialize(QgisInterface* iface, QString* error) {
    Impl& d = *impl_;

    // Single initialisation: a second call reports the existing state and
    // never starts a second interpreter (non-regression guarantee N1).
    if (d.initialized) {
        if (error && !d.cap.pythonEnabled) {
            *error = d.libraryError.isEmpty()
                         ? QStringLiteral("QGIS Python runtime is not enabled")
                         : d.libraryError;
        }
        return d.cap.pythonEnabled;
    }
    d.initialized = true;

    QString libraryName(QStringLiteral("qgispython"));
#if defined(Q_OS_UNIX)
    libraryName.prepend(QgsApplication::libraryPath());
#endif
#ifdef __MINGW32__
    libraryName.prepend(QStringLiteral("lib"));
#endif

    const int v = Qgis::versionInt();
    const QString version = QStringLiteral("%1.%2.%3")
                                .arg(v / 10000)
                                .arg(v / 100 % 100)
                                .arg(v % 100);
    d.cap.qgisVersion = version;

    auto library = std::make_unique<QLibrary>(libraryName, version);
    // Required: without these hints the Python shared library's symbols are
    // not exported globally and extension modules fail to resolve.
    library->setLoadHints(QLibrary::ResolveAllSymbolsHint |
                          QLibrary::ExportExternalSymbolsHint);
    if (!library->load()) {
        library->setFileName(libraryName);
        if (!library->load()) {
            d.libraryError = library->errorString();
            d.cap.libraryError = d.libraryError;
            logPython(QStringLiteral(
                          "Couldn't load Python support library '%1': %2")
                          .arg(libraryName, d.libraryError));
            if (error) *error = d.libraryError;
            return false;
        }
    }

    // QLibrary::resolve() returns QFunctionPointer (void(*)()), not void*.
    const QFunctionPointer symbol = library->resolve("instance");
    if (!symbol) {
        d.libraryError =
            QStringLiteral("Couldn't resolve Python support library's "
                           "instance() symbol.");
        d.cap.libraryError = d.libraryError;
        logPython(d.libraryError);
        if (error) *error = d.libraryError;
        return false;
    }

    using InstanceFn = QgsPythonUtils* (*)();
    const auto instanceFn = reinterpret_cast<InstanceFn>(symbol);
    d.utils = instanceFn();
    if (!d.utils) {
        d.libraryError =
            QStringLiteral("Python support library returned no QgsPythonUtils "
                           "instance.");
        d.cap.libraryError = d.libraryError;
        logPython(d.libraryError);
        if (error) *error = d.libraryError;
        return false;
    }

    d.cap.runtimeAvailable = true;
    d.cap.libraryPath = library->fileName();

    const QString faultLogPath =
        QStandardPaths::standardLocations(QStandardPaths::TempLocation)
            .value(0) +
        QStringLiteral("/paleo-python-crash-info-") +
        QString::number(QCoreApplication::applicationPid());

    d.utils->initPython(iface, true, faultLogPath);
    d.cap.pythonEnabled = d.utils->isEnabled();

    if (!d.cap.pythonEnabled) {
        d.lastTraceback.clear();
        QString errorClass;
        QString errorText;
        if (d.utils->getError(errorClass, errorText)) {
            d.lastTraceback = errorClass + QStringLiteral(": ") + errorText;
        }
        d.libraryError = d.lastTraceback.isEmpty()
                             ? QStringLiteral("Python support not enabled")
                             : d.lastTraceback;
        d.cap.libraryError = d.libraryError;
        logPython(d.libraryError);
        if (error) *error = d.libraryError;
        return false;
    }

    // The library must stay loaded for the process lifetime.
    d.library = std::move(library);

    d.cap.bindingsAvailable =
        d.utils->runString(QStringLiteral("import qgis.core"), QString(), true);
    if (d.cap.bindingsAvailable) {
        d.utils->runString(QString::fromLatin1(kNeuterAppInit), QString(),
                           false);
    }

    QString pythonVersion;
    if (d.utils->evalString(
            QStringLiteral("__import__('platform').python_version()"),
            pythonVersion)) {
        d.cap.pythonVersion = pythonVersion;
    }

    d.cap.processingAvailable =
        d.cap.bindingsAvailable &&
        d.utils->runString(QStringLiteral("import processing"), QString(),
                           true);
    d.cap.consoleAvailable =
        d.cap.bindingsAvailable &&
        d.utils->runString(QStringLiteral("import console.console"), QString(),
                           true);

    // Runner last: it is only valid once Python is enabled.
    QgsPythonRunner::setInstance(new PythonRunner(d.utils));
    d.cap.runnerInstalled = QgsPythonRunner::isValid();

    d.utils->initGDAL();

    return true;
}

bool PythonRuntime::isEnabled() const { return impl_->cap.pythonEnabled; }

bool PythonRuntime::isInitialized() const { return impl_->initialized; }

void PythonRuntime::shutdown() {
    Impl& d = *impl_;
    if (!d.initialized) {
        return;
    }

    // Runner first (it holds QgsPythonUtils), then Python, then the library.
    if (d.cap.runnerInstalled) {
        QgsPythonRunner::setInstance(nullptr);
        d.cap.runnerInstalled = false;
    }
    if (d.utils) {
        d.utils->exitPython();
        delete d.utils;
        d.utils = nullptr;
    }
    d.library.reset();
    d.cap = PythonCapability{};
    d.initialized = false;
}

const PythonCapability& PythonRuntime::capability() const { return impl_->cap; }

bool PythonRuntime::runString(const QString& command, QString* error) {
    Impl& d = *impl_;
    if (!d.utils || !d.cap.pythonEnabled) {
        if (error) {
            *error = QStringLiteral("QGIS Python runtime is not available");
        }
        return false;
    }
    const bool ok = d.utils->runString(command, QString(), true);
    if (!ok) {
        QString errorClass;
        QString errorText;
        if (d.utils->getError(errorClass, errorText)) {
            d.lastTraceback = errorClass + QStringLiteral(": ") + errorText;
        }
        if (error) *error = d.lastTraceback;
    }
    return ok;
}

bool PythonRuntime::evalString(const QString& expression, QString* result,
                               QString* error) {
    Impl& d = *impl_;
    if (!d.utils || !d.cap.pythonEnabled) {
        if (error) {
            *error = QStringLiteral("QGIS Python runtime is not available");
        }
        return false;
    }
    QString value;
    const bool ok = d.utils->evalString(expression, value);
    if (!ok) {
        QString errorClass;
        QString errorText;
        if (d.utils->getError(errorClass, errorText)) {
            d.lastTraceback = errorClass + QStringLiteral(": ") + errorText;
        }
        if (error) *error = d.lastTraceback;
        return false;
    }
    if (result) *result = value;
    return true;
}

bool PythonRuntime::runFile(const QString& path, QString* error) {
    Impl& d = *impl_;
    if (!d.utils || !d.cap.pythonEnabled) {
        if (error) {
            *error = QStringLiteral("QGIS Python runtime is not available");
        }
        return false;
    }
    const bool ok = d.utils->runFile(path, QString());
    if (!ok) {
        QString errorClass;
        QString errorText;
        if (d.utils->getError(errorClass, errorText)) {
            d.lastTraceback = errorClass + QStringLiteral(": ") + errorText;
        }
        if (error) *error = d.lastTraceback;
    }
    return ok;
}

QString PythonRuntime::lastTraceback() const { return impl_->lastTraceback; }

}  // namespace pwb::qgis_python
