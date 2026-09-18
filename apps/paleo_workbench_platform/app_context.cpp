#include "app_context.hpp"

#include "diagnostics.hpp"

#include <pwb/application/adapters/data_store.hpp>

#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
#include <pwb/seismic_attributes/attributes.hpp>
#endif

namespace pwb::app {

struct AppContext::Impl {
    std::unique_ptr<pwb::application::ProjectSession> session;
    std::shared_ptr<pwb::application::PwbDataStore> project_store;
#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
    std::unique_ptr<pwb::application::AlgorithmRunner> attribute_runner;
#endif
    bool closed = false;
};

AppContext::AppContext() : impl_(std::make_unique<Impl>()) {
    impl_->session = std::make_unique<pwb::application::ProjectSession>();
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

void AppContext::setProjectStore(
    std::shared_ptr<pwb::application::PwbDataStore> store) {
    impl_->project_store = std::move(store);
}

std::shared_ptr<pwb::application::PwbDataStore> AppContext::projectStore() const {
    return impl_->project_store;
}

void AppContext::shutdown() {
    if (impl_->closed) return;
    impl_->closed = true;
    // Ordered teardown. ProjectSession::close() must run while the canvas
    // host (MainWindow) is still alive — MapSession teardown unsets map
    // tools and detaches the canvas, and those paths are the documented
    // shutdown order of the CPP-A contract. Idempotent when the window
    // already ran it.
    if (impl_->session != nullptr) impl_->session->close();
#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
    impl_->attribute_runner.reset();
#endif
    impl_->project_store.reset();
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
        cap.detail = build.in_closure ? QStringLiteral("linked")
                                      : QStringLiteral("not in this build");
        // Runtime refinement: services this context actually owns.
        if (cap.id == QLatin1String("seismic_attributes")) {
#if defined(PWB_WITH_SEISMIC_ATTRIBUTES) && defined(PWB_WITH_DATA_INTEGRATION)
            cap.runtime_ok = impl_->attribute_runner != nullptr
                             && !impl_->attribute_runner->algorithms().empty();
            cap.detail = cap.runtime_ok
                ? QStringLiteral("%1 kernels registered").arg(QString::number(
                      impl_->attribute_runner->algorithms().size()))
                : QStringLiteral("no attribute kernels registered");
#else
            cap.detail = QStringLiteral("build lacks data integration");
#endif
        } else if (cap.id == QLatin1String("data_integration")) {
            cap.detail = QStringLiteral("store handle %1")
                              .arg(impl_->project_store != nullptr
                                       ? QStringLiteral("attached")
                                       : QStringLiteral("idle"));
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
        if (cap.cls != capabilities::BuildClass::hard) continue;
        AuditEntry entry;
        entry.id = cap.id;
        entry.ok = cap.in_closure && cap.runtime_ok;
        entry.detail = cap.detail;
        if (!entry.ok) audit.ok = false;
        audit.entries.append(entry);
    }
    return audit;
}

}  // namespace pwb::app
