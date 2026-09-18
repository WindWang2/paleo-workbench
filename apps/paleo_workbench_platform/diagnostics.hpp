#pragma once

// diagnostics — the product error/log chain (native-product closure, task D).
//
// One place for:
//   * categorized product logging (LogArea) — every subsystem funnels its
//     errors through pwb::app::log_* so reports can attribute failures;
//   * a Qt message-handler collector keeping the last N lines for
//     diagnostics/self-check reports (no qDebug soup in a bug report);
//   * environment probing (versions, providers, CRS/PROJ reachability,
//     writable temp, python-free process evidence) without touching
//     fixtures — safe for --diagnostics on a user machine.

#include <QString>
#include <QStringList>
#include <QtGlobal>

namespace pwb::app::diagnostics {

// Product subsystem areas. Keep in sync with the category strings in
// diagnostics.cpp (single mapping point).
enum class LogArea {
    Startup,
    Qgis,
    Project,
    Workflow,
    Data,
    Science,
};

void log(LogArea area, QtMsgType level, const QString& message);

inline void info(LogArea area, const QString& message) {
    log(area, QtInfoMsg, message);
}
inline void warning(LogArea area, const QString& message) {
    log(area, QtWarningMsg, message);
}
inline void critical(LogArea area, const QString& message) {
    log(area, QtCriticalMsg, message);
}

// Installs the product message handler: lines are formatted
// `[level] [pwb.<area>] message` and the tail is kept for reports. The
// previously installed handler (if any) is chained after the collector, so
// stderr behavior is preserved. Call exactly once, before QgsApplication.
void install_message_collector(int keep_lines = 512);

// The collected tail (oldest first). Thread-safe.
QStringList collected_tail();

// Environment report gathered from live runtime state. Preconditions:
// QgsApplication exists and QgisRuntime::acquire() has run (the probes
// need QGIS providers and the PROJ database).
struct EnvironmentReport {
    QString qt_version;
    QString qgis_version;
    QString qgis_prefix_path;
    QString qt_platform;
    QString executable_dir;
    QStringList vector_providers;      // provider keys, sorted
    bool crs_lookup_ok = false;        // EPSG:4326 built through PROJ
    QString crs_lookup_error;
    bool temp_writable = false;
    QString temp_dir;
    // "verified" (POSIX /proc scan), "not-probed" (non-POSIX), or
    // "leaked:<paths>" when a python shared object is mapped — the last
    // is a product defect, surfaced loudly by self-check.
    QString python_runtime_state;
};

EnvironmentReport probe_environment();

// Renders the human-readable diagnostics report (versions, providers,
// probes, capability table context and the log tail).
QString render_report(const EnvironmentReport& environment,
                      const QStringList& log_tail);

}  // namespace pwb::app::diagnostics
