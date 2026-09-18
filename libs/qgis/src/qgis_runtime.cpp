#include <pwb/qgis/qgis_runtime.hpp>

#include <atomic>
#include <cstdlib>
#include <stdexcept>

#include <qgsversion.h>
#include <qgsapplication.h>

namespace pwb::qgis {
namespace {
std::atomic<bool> g_initialized{false};

// The deploy seam (native-product closure): the compile-time vendor SDK
// path is the dev-tree default; a deployed tree carries its own QGIS
// prefix (resources/plugins layout) and points the process at it via
// PWB_QGIS_PREFIX. Unset → baked path, exactly the previous behavior.
const std::string& prefix_path() {
    static const std::string resolved = [] {
        if (const char* env = std::getenv("PWB_QGIS_PREFIX")) {
            if (env[0] != '\0') return std::string(env);
        }
        return std::string(PALEO_QGIS_PREFIX_PATH);
    }();
    return resolved;
}
}  // namespace

void QgisRuntime::acquire() {
    bool expected = false;
    if (!g_initialized.compare_exchange_strong(expected, true)) {
        throw std::logic_error(
            "QgisRuntime::acquire called twice — QGIS must init exactly once per process");
    }
    if (QgsApplication::instance() == nullptr) {
        g_initialized.store(false);
        throw std::logic_error(
            "QgisRuntime::acquire requires an existing QCoreApplication");
    }
    QgsApplication::setPrefixPath(QString::fromStdString(prefix_path()), true);
    QgsApplication::init();
    QgsApplication::initQgis();
}

void QgisRuntime::release() {
    bool expected = true;
    if (!g_initialized.compare_exchange_strong(expected, false)) return;
    QgsApplication::exitQgis();
}

bool QgisRuntime::initialized() { return g_initialized.load(); }

const std::string& QgisRuntime::prefix_path() { return prefix_path(); }

// Generated qgsversion.h of the vendored build tree ("dev" for local
// builds); the authoritative version provenance is UPSTREAM.md (4.2.0).
std::string QgisRuntime::qgis_version() { return QGSVERSION; }

}  // namespace pwb::qgis
