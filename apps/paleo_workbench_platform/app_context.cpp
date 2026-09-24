#include "app_context.hpp"

#include "diagnostics.hpp"

#ifdef PWB_WITH_DATA_INTEGRATION
#include <pwb/application/adapters/data_store.hpp>
#endif

#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
#include <pwb/application/algorithm_runner.hpp>
#include <pwb/qgis_processing/provider.hpp>
#include <pwb/qgis_processing/runner.hpp>
#endif
#ifdef PWB_WITH_PROVIDERS
#include <pwb/providers/service.hpp>
#endif

namespace pwb::app {

struct AppContext::Impl {
    std::unique_ptr<pwb::application::ProjectSession> session;
#ifdef PWB_WITH_DATA_INTEGRATION
    std::shared_ptr<pwb::application::PwbDataStore> project_store;
#endif
#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
    std::unique_ptr<pwb::application::AlgorithmRunner> attribute_runner;
#endif
#ifdef PWB_WITH_PROVIDERS
    std::unique_ptr<pwb::providers::ProviderService> provider_service;
#endif
    bool closed = false;
};

AppContext::AppContext() : impl_(std::make_unique<Impl>()) {
    impl_->session = std::make_unique<pwb::application::ProjectSession>();
#ifdef PWB_WITH_PROVIDERS
    impl_->provider_service = std::make_unique<pwb::providers::ProviderService>();
#endif
    registerProductKernels();
    diagnostics::info(diagnostics::LogArea::Startup,
                      QStringLiteral("app context started"));
}

AppContext::~AppContext() {
    shutdown();
}

void AppContext::registerProductKernels() {
#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
    // CONV-QGIS-PROCESSING phase 4: kernels are no longer registered into
    // the runner by the host — the Paleo Processing provider inside
    // QgsProcessingRegistry is the single algorithm authority. Constructing
    // the runner installs the provider idempotently (belt-and-braces with
    // JobCenter's ctor install: AppContext is constructed BEFORE any
    // window/JobCenter exists, so this is the first install in practice).
    impl_->attribute_runner = std::make_unique<pwb::application::AlgorithmRunner>();
    const bool installed = pwb::qgis_processing::paleo_provider_installed();
    if (!installed) {
        diagnostics::warning(diagnostics::LogArea::Science,
                             QStringLiteral("paleo Processing provider is "
                                            "not registered"));
    }
#endif
}

pwb::application::ProjectSession& AppContext::session() const {
    return *impl_->session;
}

#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
pwb::application::AlgorithmRunner& AppContext::attributeRunner() const {
    return *impl_->attribute_runner;
}
#endif

#ifdef PWB_WITH_DATA_INTEGRATION
void AppContext::setProjectStore(
    std::shared_ptr<pwb::application::PwbDataStore> store) {
    impl_->project_store = std::move(store);
}

std::shared_ptr<pwb::application::PwbDataStore> AppContext::projectStore() const {
    return impl_->project_store;
}
#endif

void AppContext::shutdown() {
    if (impl_->closed) return;
    impl_->closed = true;
    // Ordered teardown. ProjectSession::close() must run while the canvas
    // host (MainWindow) is still alive — MapSession teardown unsets map
    // tools and detaches the canvas, and those paths are the documented
    // shutdown order of the CPP-A contract. Idempotent when the window
    // already ran it.
    if (impl_->session != nullptr) impl_->session->close();
    // attribute_runner stays alive: attributeRunner() must remain valid for
    // the whole context lifetime (same contract as session()); its worker
    // set drains naturally once nothing submits. The store handle is the
    // only service whose lifetime follows the open project.
#ifdef PWB_WITH_DATA_INTEGRATION
    impl_->project_store.reset();
#endif
    diagnostics::info(diagnostics::LogArea::Startup,
                      QStringLiteral("app context shut down"));
}

QVector<AppContext::RuntimeCapability> AppContext::capabilities() const {
    QVector<RuntimeCapability> result;
    for (const auto& build : capabilities::kBuildCapabilities) {
        RuntimeCapability cap;
        cap.id = QString::fromLatin1(build.id);
        cap.title = QString::fromUtf8(build.title);
        cap.cls = build.cls;
        cap.in_closure = build.in_closure;
        cap.runtime_ok = build.in_closure;
        if (build.cls == capabilities::BuildClass::kernel) {
            cap.detail = build.in_closure
                ? QStringLiteral("kernel present, not wired into the product")
                : QStringLiteral("not in this build");
        } else {
            cap.detail = build.in_closure
                ? QStringLiteral("linked")
                : QStringLiteral("not in this build");
        }
        // Runtime refinement: services this context actually owns.
        if (cap.id == QLatin1String("geomodel_kernel") &&
            build.in_closure) {
#if defined(PWB_WITH_JOINT_ANALYSIS)
            // The joint-analysis install consumes the lithology tables /
            // advisor rules at runtime (round-2 review: the generic
            // kernel detail had gone stale).
            cap.detail =
                QStringLiteral("kernel present — consumed by the joint "
                               "analysis hooks");
#else
            cap.detail =
                QStringLiteral("kernel present, not wired into the "
                               "product");
#endif
        }
        if (cap.id == QLatin1String("seismic_attributes")) {
#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
            // Registry-backed probe: count the seismic-family algorithms
            // the Paleo Processing provider exposes (the runner holds no
            // kernel map since the phase-4 convergence).
            int seismic_algorithms = 0;
            for (const pwb::qgis_processing::PaleoAlgorithmInfo& info :
                 pwb::qgis_processing::paleo_algorithm_infos()) {
                if (info.group_id == QLatin1String("seismic")) {
                    ++seismic_algorithms;
                }
            }
            cap.runtime_ok = impl_->attribute_runner != nullptr
                             && seismic_algorithms > 0;
            cap.detail = cap.runtime_ok
                ? QStringLiteral("%1 processing algorithms registered")
                      .arg(QString::number(seismic_algorithms))
                : QStringLiteral("no paleo processing algorithms registered");
#else
            // The switch is ON but the runner needs the data-integration
            // macro pair — without it no kernel can even register, so a
            // runtime-ok here would be a silent false positive.
            cap.runtime_ok = false;
            cap.detail = QStringLiteral("build lacks data integration");
#endif
        } else if (cap.id == QLatin1String("data_integration")) {
#ifdef PWB_WITH_DATA_INTEGRATION
            cap.detail = QStringLiteral("store handle %1")
                              .arg(impl_->project_store != nullptr
                                       ? QStringLiteral("attached")
                                       : QStringLiteral("idle"));
#else
            cap.detail = QStringLiteral("module-only build");
#endif
        } else if (cap.id == QLatin1String("provider_runtime")) {
#ifdef PWB_WITH_PROVIDERS
            if (impl_->provider_service != nullptr) {
                const auto report = impl_->provider_service->capability_report();
                cap.runtime_ok = !report.empty();
                cap.detail = cap.runtime_ok
                    ? QStringLiteral("%1 providers registered")
                          .arg(QString::number(report.size()))
                    : QStringLiteral("no native providers registered");
            } else {
                cap.runtime_ok = false;
                cap.detail = QStringLiteral("provider service is not available");
            }
#else
            cap.runtime_ok = false;
            cap.detail = QStringLiteral("provider service is not linked");
#endif
        }
        result.append(cap);
    }
    return result;
}

AppContext::ServiceAudit AppContext::auditServices() const {
    ServiceAudit audit;
    audit.ok = true;
    audit.entries.reserve(static_cast<int>(capabilities::kBuildCapabilityCount));
    for (const RuntimeCapability& cap : capabilities()) {
        // Module-only builds are legal: a hard capability not in this
        // build's closure is a capabilities()-reported fact, not a service
        // failure. The audit asks "is every service this binary carries
        // actually reachable", never "did you build everything".
        if (cap.cls != capabilities::BuildClass::hard || !cap.in_closure) {
            continue;
        }
        AuditEntry entry;
        entry.id = cap.id;
        entry.ok = cap.runtime_ok;
        entry.detail = cap.detail;
        if (!entry.ok) audit.ok = false;
        audit.entries.append(entry);
    }
    return audit;
}

}  // namespace pwb::app
