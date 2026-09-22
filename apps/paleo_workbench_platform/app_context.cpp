#include "app_context.hpp"

#include "diagnostics.hpp"

#ifdef PWB_WITH_DATA_INTEGRATION
#include <pwb/application/adapters/data_store.hpp>
#endif

#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
#include <pwb/science/algorithms/coherence_c3.hpp>
#include <pwb/seismic_attributes/attributes.hpp>
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
    // The context is the composition root: E's contract has the host
    // register kernels explicitly (no static auto-registration into a
    // shared registry).
    impl_->attribute_runner = std::make_unique<pwb::application::AlgorithmRunner>();
    const std::string rejections[] = {
        impl_->attribute_runner->register_kernel(
            pwb::seismic_attributes::make_envelope("pwb-platform")),
        impl_->attribute_runner->register_kernel(
            pwb::seismic_attributes::make_instantaneous_phase("pwb-platform")),
        impl_->attribute_runner->register_kernel(
            pwb::seismic_attributes::make_instantaneous_frequency("pwb-platform")),
        impl_->attribute_runner->register_kernel(
            pwb::seismic_attributes::make_rms_amplitude("pwb-platform")),
        // S line: the volume-structural production kernels.
        impl_->attribute_runner->register_kernel(
            pwb::seismic_attributes::make_sweetness("pwb-platform")),
        impl_->attribute_runner->register_kernel(
            pwb::seismic_attributes::make_relative_impedance("pwb-platform")),
        impl_->attribute_runner->register_kernel(
            pwb::seismic_attributes::make_dip_inline("pwb-platform")),
        impl_->attribute_runner->register_kernel(
            pwb::seismic_attributes::make_dip_crossline("pwb-platform")),
        impl_->attribute_runner->register_kernel(
            pwb::seismic_attributes::make_dip_azimuth("pwb-platform")),
        impl_->attribute_runner->register_kernel(
            pwb::seismic_attributes::make_curvature_mean("pwb-platform")),
        // C3 eigenstructure coherence — the science-suite kernel
        // (pwb_science, oracle-frozen in tests/cpp/science/
        // coherence_c3_oracle_test.cpp) joins the product runner; before
        // this registration the kernel existed but no product path could
        // run it (Python parity: seismic_view exposes 相干(C3)).
        impl_->attribute_runner->register_kernel(
            pwb::science::algorithms::make_coherence_c3("pwb-platform")),
    };
    for (const std::string& rejection : rejections) {
        if (!rejection.empty()) {
            diagnostics::warning(diagnostics::LogArea::Science,
                                 QStringLiteral("attribute kernel registration: %1")
                                     .arg(QString::fromStdString(rejection)));
        }
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
            cap.runtime_ok = impl_->attribute_runner != nullptr
                             && !impl_->attribute_runner->algorithms().empty();
            cap.detail = cap.runtime_ok
                ? QStringLiteral("%1 kernels registered").arg(QString::number(
                      impl_->attribute_runner->algorithms().size()))
                : QStringLiteral("no attribute kernels registered");
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
