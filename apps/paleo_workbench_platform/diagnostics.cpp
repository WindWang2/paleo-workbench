#include "diagnostics.hpp"

#include <QDateTime>
#include <QDir>
#include <QGuiApplication>
#include <QFile>
#include <QTemporaryFile>
#include <QTextStream>

#include <qgsapplication.h>
#include <qgscoordinatereferencesystem.h>
#include <qgsproviderregistry.h>

#include <pwb/qgis/qgis_runtime.hpp>

#include <atomic>
#include <mutex>

#ifdef __linux__
#include <fstream>
#include <unordered_set>
#endif

namespace pwb::app::diagnostics {
namespace {

const char* area_tag(LogArea area) {
    switch (area) {
    case LogArea::Startup: return "pwb.startup";
    case LogArea::Qgis: return "pwb.qgis";
    case LogArea::Project: return "pwb.project";
    case LogArea::Workflow: return "pwb.workflow";
    case LogArea::Data: return "pwb.data";
    case LogArea::Science: return "pwb.science";
    }
    return "pwb.unknown";
}

const char* level_tag(QtMsgType level) {
    switch (level) {
    case QtDebugMsg: return "debug";
    case QtInfoMsg: return "info";
    case QtWarningMsg: return "warning";
    case QtCriticalMsg: return "critical";
    case QtFatalMsg: return "fatal";
    }
    return "?";
}

// ---- message collector ring ----------------------------------------------
struct LogRing {
    std::mutex mutex;
    QStringList lines;
    int capacity = 512;
};

LogRing& ring() {
    static LogRing instance;
    return instance;
}

QtMessageHandler chained_handler = nullptr;

void product_message_handler(QtMsgType type, const QMessageLogContext& context,
                             const QString& message) {
    {
        LogRing& r = ring();
        std::lock_guard<std::mutex> lock(r.mutex);
        const QString tag = QString::fromLatin1(context.category)
                                .isEmpty()
                                ? QStringLiteral("default")
                                : QString::fromLatin1(context.category);
        r.lines.append(QStringLiteral("[%1] [%2] %3")
                           .arg(QString::fromLatin1(level_tag(type)), tag,
                                message));
        while (r.lines.size() > r.capacity) r.lines.removeFirst();
    }
    if (chained_handler != nullptr) {
        chained_handler(type, context, message);
    } else if (type == QtFatalMsg) {
        // No prior handler: preserve Qt's abort semantics for fatal.
        qt_message_output(type, context, message);
    }
}

#ifdef __linux__
// Product invariant: the native entry never maps a Python runtime. Scan
// the process image for python shared objects (covers PySide/libpython —
// anything that slipped in through a plugin).
QString scan_python_runtime() {
    std::ifstream maps("/proc/self/maps");
    if (!maps.is_open()) return QStringLiteral("not-probed");
    std::unordered_set<std::string> hits;
    std::string line;
    while (std::getline(maps, line)) {
        const auto pos = line.find('/');
        if (pos == std::string::npos) continue;
        const std::string path = line.substr(pos);
        if (path.find("python") != std::string::npos
            || path.find("pyside") != std::string::npos) {
            hits.insert(path);
        }
    }
    if (hits.empty()) return QStringLiteral("verified");
    QStringList leaked;
    for (const auto& path : hits) leaked << QString::fromStdString(path);
    return QStringLiteral("leaked:") + leaked.join(QStringLiteral(","));
}
#else
QString scan_python_runtime() {
    return QStringLiteral("not-probed");
}
#endif

}  // namespace

void log(LogArea area, QtMsgType level, const QString& message) {
    // Route through the category system so the collector keeps the area
    // tag (pwb.<area>) regardless of which handler is installed.
    QMessageLogger logger(nullptr, 0, nullptr, area_tag(area));
    switch (level) {
    case QtDebugMsg: logger.debug("%s", qUtf8Printable(message)); break;
    case QtInfoMsg: logger.info("%s", qUtf8Printable(message)); break;
    case QtWarningMsg: logger.warning("%s", qUtf8Printable(message)); break;
    case QtCriticalMsg: logger.critical("%s", qUtf8Printable(message)); break;
    case QtFatalMsg: logger.fatal("%s", qUtf8Printable(message)); break;
    }
}

void install_message_collector(int keep_lines) {
    ring().capacity = keep_lines;
    chained_handler = qInstallMessageHandler(product_message_handler);
}

QStringList collected_tail() {
    LogRing& r = ring();
    std::lock_guard<std::mutex> lock(r.mutex);
    return r.lines;
}

EnvironmentReport probe_environment() {
    EnvironmentReport report;
    report.qt_version = QString::fromLatin1(qVersion());
    report.qgis_version = pwb::qgis::QgisRuntime::qgis_version();
    report.qgis_prefix_path =
        QString::fromStdString(pwb::qgis::QgisRuntime::prefix_path());
    report.qt_platform = QGuiApplication::platformName();
    report.executable_dir = QGuiApplication::applicationDirPath();

    QgsProviderRegistry* registry = QgsProviderRegistry::instance();
    if (registry != nullptr) {
        report.vector_providers = registry->providerList();
        report.vector_providers.sort();
    }

    const QgsCoordinateReferenceSystem crs(QStringLiteral("EPSG:4326"));
    report.crs_lookup_ok = crs.isValid();
    if (!report.crs_lookup_ok) {
        report.crs_lookup_error = QStringLiteral(
            "EPSG:4326 lookup failed (PROJ database unreachable?)");
    }

    QTemporaryFile probe;
    report.temp_writable = probe.open();
    report.temp_dir = QDir::tempPath();

    report.python_runtime_state = scan_python_runtime();
    return report;
}

QString render_report(const EnvironmentReport& environment,
                      const QStringList& log_tail) {
    QString text;
    QTextStream out(&text);
    out << "Paleo Workbench native platform — diagnostics report\n";
    out << "generated: "
        << QDateTime::currentDateTime().toString(Qt::ISODate) << "\n";
    out << "\n[versions]\n";
    out << "  qt: " << environment.qt_version << "\n";
    out << "  qgis: " << environment.qgis_version << "\n";
    out << "  qgis prefix: " << environment.qgis_prefix_path << "\n";
    out << "  qt platform: " << environment.qt_platform << "\n";
    out << "  executable dir: " << environment.executable_dir << "\n";
    out << "\n[vector providers] "
        << environment.vector_providers.join(QStringLiteral(", ")) << "\n";
    out << "\n[probes]\n";
    out << "  crs EPSG:4326: "
        << (environment.crs_lookup_ok
                ? QStringLiteral("ok")
                : QStringLiteral("FAILED: ") + environment.crs_lookup_error)
        << "\n";
    out << "  temp writable: "
        << (environment.temp_writable ? QStringLiteral("ok")
                                      : QStringLiteral("FAILED"))
        << " (" << environment.temp_dir << ")\n";
    out << "  python runtime: " << environment.python_runtime_state << "\n";
    if (!log_tail.isEmpty()) {
        out << "\n[log tail]\n";
        for (const QString& line : log_tail) {
            out << "  " << line << "\n";
        }
    }
    return text;
}

}  // namespace pwb::app::diagnostics
