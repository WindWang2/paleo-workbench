// platform.app_context — the composition root's service layer
// (native-product closure): AppContext constructs and shuts down cleanly
// around a real QGIS runtime, the capability matrix mirrors the build
// table, and the service audit passes for every hard capability this
// build carries. No MainWindow involved (that is ui_wiring/self-check).

#include <qgsapplication.h>

#include <pwb/qgis/qgis_runtime.hpp>

#include "app_context.hpp"
#include "diagnostics.hpp"

#include "test_framework.hpp"

using pwb::app::AppContext;

int main(int argc, char** argv) {
    QgsApplication app(argc, argv, true);
    pwb::qgis::QgisRuntime::acquire();

    {
        AppContext context;
        PWB_CHECK(context.session().map().project() != nullptr);

        // Capability matrix: one entry per compile-time table row, hard
        // entries in this build must be linked.
        const QVector<AppContext::RuntimeCapability> caps =
            context.capabilities();
        PWB_CHECK(caps.size()
                  == static_cast<int>(
                      pwb::app::capabilities::kBuildCapabilityCount));
        int hard = 0;
        for (const auto& cap : caps) {
            if (cap.cls != pwb::app::capabilities::BuildClass::hard) continue;
            ++hard;
            if (cap.in_closure) {
                PWB_CHECK_MSG(cap.runtime_ok,
                              "hard capability runtime-degraded: "
                                  + cap.id.toStdString());
            }
        }
        PWB_CHECK(hard > 0);

        // Service audit: all hard services reachable.
        const AppContext::ServiceAudit audit = context.auditServices();
        PWB_CHECK_MSG(audit.ok, "service audit failed");
        PWB_CHECK(audit.entries.size() == hard);

        context.shutdown();
        // Idempotent shutdown + the session survives for callers that
        // already closed it (double close is a documented no-op).
        context.shutdown();
    }

    // Diagnostics collector round trip: install, emit, collect.
    pwb::app::diagnostics::install_message_collector(64);
    pwb::app::diagnostics::warning(pwb::app::diagnostics::LogArea::Project,
                                   QStringLiteral("probe-message"));
    const QStringList tail = pwb::app::diagnostics::collected_tail();
    bool found = false;
    for (const QString& line : tail) {
        if (line.contains(QStringLiteral("pwb.project"))
            && line.contains(QStringLiteral("probe-message"))) {
            found = true;
        }
    }
    PWB_CHECK_MSG(found, "log collector lost the categorized line");

    return pwb::test::report("platform.app_context");
}
