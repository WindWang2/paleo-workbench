#include <pwb/qgis/qgis_runtime.hpp>

#include <atomic>
#include <cstdlib>
#include <stdexcept>

#include <qgsversion.h>
#include <qgsapplication.h>

namespace pwb::qgis {
namespace {
std::atomic<bool> g_initialized{false};
const std::string g_prefix = PALEO_QGIS_PREFIX_PATH;
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
    QgsApplication::setPrefixPath(QString::fromStdString(g_prefix), true);
    QgsApplication::init();
    QgsApplication::initQgis();
}

void QgisRuntime::release() {
    bool expected = true;
    if (!g_initialized.compare_exchange_strong(expected, false)) return;
    QgsApplication::exitQgis();
}

bool QgisRuntime::initialized() { return g_initialized.load(); }

const std::string& QgisRuntime::prefix_path() { return g_prefix; }

// Generated qgsversion.h of the vendored build tree ("dev" for local
// builds); the authoritative version provenance is UPSTREAM.md (4.2.0).
std::string QgisRuntime::qgis_version() { return QGSVERSION; }

}  // namespace pwb::qgis
