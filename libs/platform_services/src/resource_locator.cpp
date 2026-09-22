#include <pwb/platform_services/resource_locator.hpp>

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QStandardPaths>

#include <cstdlib>

namespace pwb::platform_services {
namespace {

QString first_existing_dir(const QStringList& candidates) {
    for (const QString& candidate : candidates) {
        if (candidate.isEmpty()) continue;
        const QFileInfo info(candidate);
        if (info.isDir() && info.exists()) return info.canonicalFilePath();
    }
    return QString();
}

}  // namespace

QString resources_root() {
    // 1. Explicit override always wins.
    if (const char* override_dir = std::getenv("PALEO_RESOURCES_DIR")) {
        if (override_dir[0] != '\0') {
            const QFileInfo info(QString::fromLocal8Bit(override_dir));
            if (info.isDir() && info.exists()) {
                return info.canonicalFilePath();
            }
        }
    }
    // 2. Compile-time source tree (dev runs and tests). Two dev layouts:
    //    a) <source>/resources — the staged resource tree;
    //    b) <source>/paleo_workbench — the Python product package whose
    //       ui/assets/icons tree IS the canonical icon asset set (the C++
    //       ribbon/toolbar tables reference these names verbatim; no
    //       staged copy exists on a dev tree).
    QStringList source_candidates;
    source_candidates << QStringLiteral(PWB_SOURCE_DIR)
                             + QStringLiteral("/paleo_workbench")
                      << QStringLiteral(PWB_SOURCE_DIR)
                             + QStringLiteral("/resources");
    // 3. Install layout: <prefix>/share/paleo-workbench/resources.
    QStringList install_candidates;
    const QString app_dir = QCoreApplication::applicationDirPath();
    if (!app_dir.isEmpty()) {
        install_candidates
            << app_dir + QStringLiteral("/../share/paleo-workbench/resources")
            << app_dir + QStringLiteral("/resources");
    }
    // 4. User-deployed data location.
    install_candidates
        << QStandardPaths::standardLocations(
               QStandardPaths::AppLocalDataLocation)
               .value(0)
        + QStringLiteral("/resources");
    install_candidates = source_candidates + install_candidates;
    return first_existing_dir(install_candidates);
}

QString resource_file(const QString& relative_path) {
    if (relative_path.isEmpty()) return QString();
    const QString root = resources_root();
    if (root.isEmpty()) return QString();
    // Refuse traversal outside the root (.. segments resolve elsewhere).
    const QString joined = root + QLatin1Char('/') + relative_path;
    const QFileInfo info(joined);
    if (!info.exists() || !info.isFile()) return QString();
    if (!info.canonicalFilePath().startsWith(root + QLatin1Char('/'))) {
        return QString();
    }
    return info.canonicalFilePath();
}

QString icon_file(const QString& icon_name) {
    return resource_file(QStringLiteral("icons/") + icon_name);
}

QStringList resource_roots_probed() {
    QStringList probed;
    if (const char* override_dir = std::getenv("PALEO_RESOURCES_DIR")) {
        probed << QString::fromLocal8Bit(override_dir);
    }
    probed << QStringLiteral(PWB_SOURCE_DIR) +
                  QStringLiteral("/paleo_workbench")
           << QStringLiteral(PWB_SOURCE_DIR) + QStringLiteral("/resources");
    const QString app_dir = QCoreApplication::applicationDirPath();
    if (!app_dir.isEmpty()) {
        probed << app_dir
                       + QStringLiteral("/../share/paleo-workbench/resources")
               << app_dir + QStringLiteral("/resources");
    }
    probed << QStandardPaths::standardLocations(
                    QStandardPaths::AppLocalDataLocation)
                    .value(0)
        + QStringLiteral("/resources");
    return probed;
}

}  // namespace pwb::platform_services
